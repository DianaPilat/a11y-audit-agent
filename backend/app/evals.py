"""Eval harness: score the audit agent's findings against the labels in evals/.

Scoring is pure and offline (`score_seeded`, `score_bad`); only `run_evals` calls the
agent, so it costs API tokens. A run is saved to evals/runs/ so it can be re-scored
without a new audit.

    python -m app.evals run [--set seeded|bad|all] [--only SUBSTRING] [--model ID]
    python -m app.evals score evals/runs/<file>.json

Matching rules (labels are never edited to fit; see PLAN.md, Eval plan):
- Seeded pages: a finding matches a label on the same page when the issue type agrees.
  Judgment labels are per element, so their selector must also agree. axe findings are
  grouped per rule by the auditor, so for axe labels the type alone is enough.
- BAD pages: W3C's reports are per criterion, so a finding matches a label when its
  WCAG criterion equals the label's.
- Precision = findings that match a label / all findings. Recall = labels with at least
  one matching finding / all labels. WCAG mapping accuracy = matched findings whose
  criterion is one of the matched label's defensible criteria / matched findings.
"""

import argparse
import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent import DEFAULT_MODEL, audit_site
from app.findings import FindingStore

EVALS = Path(__file__).resolve().parents[2] / "evals"
RUNS = EVALS / "runs"

# The auditor prompt's judgment rule ids, mapped to the label types.
JUDGMENT_RULES = {
    "judgment-alt-text": "alt-text-quality",
    "judgment-link-text": "link-text-meaning",
    "judgment-heading-structure": "heading-structure",
    "judgment-form-label": "label-clarity",
}


def load_labels(name: str) -> list[dict[str, Any]]:
    return json.loads((EVALS / name).read_text(encoding="utf-8"))["pages"]


def finding_type(finding: dict[str, Any]) -> str:
    return JUDGMENT_RULES.get(finding["rule_id"], finding["rule_id"])


def _norm(selector: str) -> str:
    return "".join(selector.lower().split())


def _selector_matches(element: str, label_selector: str) -> bool:
    a, b = _norm(element), _norm(label_selector)
    return b in a or a in b


def _label_matches(finding: dict[str, Any], label: dict[str, Any]) -> bool:
    if finding_type(finding) != label["type"]:
        return False
    return label["source"] == "axe" or _selector_matches(finding["element"], label["selector"])


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _stats(findings: int, true_pos: int, labels: int, found: int, mapped: int) -> dict[str, Any]:
    return {
        "findings": findings, "true_positives": true_pos, "labels": labels, "found": found,
        "wcag_correct": mapped,
        "precision": _ratio(true_pos, findings),
        "recall": _ratio(found, labels),
        "wcag_accuracy": _ratio(mapped, true_pos),
    }


def score_seeded(labels: list[dict[str, Any]], pages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Score a run over the seeded pages. `pages` maps a page file name to {"findings": [...], "error": str | None}."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    clean_false_positives: dict[str, int] = {}
    failed: list[str] = []
    for page in labels:
        run = pages.get(page["file"])
        if run is None or run.get("error"):
            failed.append(page["file"])
        findings = (run or {}).get("findings", [])
        if not page["issues"]:
            clean_false_positives[page["file"]] = len(findings)
        found_labels: set[int] = set()
        for f in findings:
            t = finding_type(f)
            counts[t]["findings"] += 1
            matched = [i for i, label in enumerate(page["issues"]) if _label_matches(f, label)]
            if not matched:
                continue
            counts[t]["true_positives"] += 1
            found_labels.update(matched)
            if any(f["wcag_criterion"] in page["issues"][i]["wcag"] for i in matched):
                counts[t]["wcag_correct"] += 1
        for i, label in enumerate(page["issues"]):
            counts[label["type"]]["labels"] += 1
            counts[label["type"]]["found"] += i in found_labels

    def total(keys: list[str]) -> dict[str, Any]:
        s = lambda k: sum(counts[t][k] for t in keys)  # noqa: E731
        return _stats(s("findings"), s("true_positives"), s("labels"), s("found"), s("wcag_correct"))

    all_types = sorted(counts)
    by_type = {t: total([t]) for t in all_types}
    judgment = [t for t in all_types if t in JUDGMENT_RULES.values()]
    axe = [t for t in all_types if t not in judgment]
    return {
        "overall": total(all_types),
        "axe": total(axe),
        "judgment": total(judgment),
        "by_type": by_type,
        "clean_pages_false_positives": clean_false_positives,
        "failed_pages": failed,
    }


def score_bad(labels: list[dict[str, Any]], pages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Score a run over the BAD pages. `pages` maps a page URL to {"findings": [...], "error": str | None}."""
    findings_n = true_pos = 0
    all_labels = all_found = scoped = scoped_found = 0
    failed: list[str] = []
    by_page: dict[str, dict[str, Any]] = {}
    for page in labels:
        run = pages.get(page["url"])
        if run is None or run.get("error"):
            failed.append(page["url"])
        findings = (run or {}).get("findings", [])
        label_criteria = {i["wcag"] for i in page["issues"]}
        found_criteria = {f["wcag_criterion"] for f in findings} & label_criteria
        page_tp = sum(f["wcag_criterion"] in label_criteria for f in findings)
        findings_n += len(findings)
        true_pos += page_tp
        for issue in page["issues"]:
            hit = issue["wcag"] in found_criteria
            all_labels += 1
            all_found += hit
            if issue["in_scope"]:
                scoped += 1
                scoped_found += hit
        by_page[page["url"]] = {
            "findings": len(findings), "true_positives": page_tp,
            "missed_in_scope": sorted(i["wcag"] for i in page["issues"] if i["in_scope"] and i["wcag"] not in found_criteria),
        }
    return {
        "precision": _ratio(true_pos, findings_n),
        "findings": findings_n,
        "true_positives": true_pos,
        "recall_in_scope": _ratio(scoped_found, scoped),
        "labels_in_scope": scoped,
        "found_in_scope": scoped_found,
        "recall_all": _ratio(all_found, all_labels),
        "labels_all": all_labels,
        "found_all": all_found,
        "by_page": by_page,
        "failed_pages": failed,
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def _row(name: str, s: dict[str, Any]) -> str:
    return (
        f"| {name} | {_pct(s['precision'])} ({s['true_positives']}/{s['findings']}) "
        f"| {_pct(s['recall'])} ({s['found']}/{s['labels']}) "
        f"| {_pct(s['wcag_accuracy'])} ({s['wcag_correct']}/{s['true_positives']}) |"
    )


def format_report(run: dict[str, Any]) -> str:
    """Markdown report for a saved run (only the sets it contains)."""
    lines = [f"Model: {run.get('model', '?')} | {run.get('started', '')}"]
    cost = sum(p.get("cost_usd") or 0 for s in ("seeded", "bad") for p in run.get(s, {}).values())
    seconds = sum(p.get("seconds") or 0 for s in ("seeded", "bad") for p in run.get(s, {}).values())
    n = sum(len(run.get(s, {})) for s in ("seeded", "bad"))
    if n:
        lines.append(f"Cost ${cost:.4f} and {seconds:.0f}s over {n} pages (${cost / n:.4f}, {seconds / n:.0f}s per page)")
    if run.get("seeded"):
        s = score_seeded(load_labels("labels.json"), run["seeded"])
        lines += [
            "", "## Seeded pages", "",
            "| Issue type | Precision | Recall | WCAG mapping |", "| --- | --- | --- | --- |",
            _row("**all**", s["overall"]), _row("axe rules", s["axe"]), _row("judgment checks", s["judgment"]),
            *(_row(t, v) for t, v in s["by_type"].items()),
        ]
        fp = sum(s["clean_pages_false_positives"].values())
        lines += ["", f"Clean pages: {fp} findings across {len(s['clean_pages_false_positives'])} pages (should be 0)."]
        if s["failed_pages"]:
            lines.append("Failed pages (their labels count as missed): " + ", ".join(s["failed_pages"]))
    if run.get("bad"):
        b = score_bad(load_labels("bad_labels.json"), run["bad"])
        lines += [
            "", "## W3C BAD pages (matched by criterion)", "",
            f"- Precision: {_pct(b['precision'])} ({b['true_positives']}/{b['findings']})",
            f"- Recall, in scope: {_pct(b['recall_in_scope'])} ({b['found_in_scope']}/{b['labels_in_scope']})",
            f"- Recall, all labels: {_pct(b['recall_all'])} ({b['found_all']}/{b['labels_all']})",
        ]
        for url, p in b["by_page"].items():
            lines.append(f"- {url.rsplit('/', 1)[1]}: {p['true_positives']}/{p['findings']} findings match; missed in scope: {', '.join(p['missed_in_scope']) or 'none'}")
        if b["failed_pages"]:
            lines.append("Failed pages (their labels count as missed): " + ", ".join(b["failed_pages"]))
    return "\n".join(lines)


async def _audit_one(url: str, model: str) -> dict[str, Any]:
    """Audit a single page and return its findings, cost and time. No ticket writing: evals score findings."""
    store = FindingStore(":memory:")
    start = time.monotonic()
    try:
        result = await audit_site(url, max_pages=1, model=model, store=store, write_tickets=False)
        error = f"audit of {url} failed" if result.failed_pages else None
        return {
            "findings": [
                {k: f[k] for k in ("rule_id", "wcag_criterion", "severity", "element", "explanation")}
                for f in result.findings
            ],
            "cost_usd": result.cost_usd, "seconds": round(time.monotonic() - start, 1), "error": error,
        }
    except Exception as e:  # one bad page must not lose the rest of an expensive run
        return {"findings": [], "cost_usd": None, "seconds": round(time.monotonic() - start, 1), "error": repr(e)}
    finally:
        store.close()


async def run_evals(sets: str = "all", only: str = "", model: str = DEFAULT_MODEL) -> dict[str, Any]:
    run: dict[str, Any] = {"model": model, "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if sets in ("seeded", "all"):
        run["seeded"] = {}
        for page in load_labels("labels.json"):
            if only in page["file"]:
                url = (EVALS / "pages" / page["file"]).as_uri()
                run["seeded"][page["file"]] = await _audit_one(url, model)
    if sets in ("bad", "all"):
        run["bad"] = {}
        for page in load_labels("bad_labels.json"):
            if only in page["url"]:
                run["bad"][page["url"]] = await _audit_one(page["url"], model)
    return run


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.evals")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="audit the eval pages (costs API tokens) and score the findings")
    r.add_argument("--set", choices=["seeded", "bad", "all"], default="all")
    r.add_argument("--only", default="", help="only pages whose file name or URL contains this")
    r.add_argument("--model", default=DEFAULT_MODEL)
    s = sub.add_parser("score", help="re-score a saved run without auditing")
    s.add_argument("file", type=Path)
    args = parser.parse_args()

    if args.cmd == "run":
        run = asyncio.run(run_evals(args.set, args.only, args.model))
        RUNS.mkdir(exist_ok=True)
        out = RUNS / f"{run['started'].replace(':', '-')}.json"
        out.write_text(json.dumps(run, indent=2), encoding="utf-8")
        print(f"saved {out}\n")
    else:
        run = json.loads(args.file.read_text(encoding="utf-8"))
    print(format_report(run))


if __name__ == "__main__":
    main()
