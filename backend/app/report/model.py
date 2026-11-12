"""The one data path for every export: findings store -> `Report`.

Inclusion rules live here and nowhere else. Approved findings are always included, rejected never, and
pending (unreviewed) findings only when `include_unreviewed` is on, in which case they are labeled.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.findings import FindingStore
from app.report.config import include_unreviewed_default
from app.report.redact import redact, redact_url
from app.report.wcag_508 import section_508
from app.wcag import load_criteria

STANDARD = "WCAG 2.1 Level AA and Revised Section 508"
SEVERITY_ORDER = ["critical", "serious", "moderate", "minor"]
CONFIDENCE_ORDER = ["low", "medium", "high"]  # lowest first: a group is only as sure as its least sure finding
SOURCE_LABELS = {"axe-core": "axe-core (automated rule)", "ai-assessed": "AI-assessed"}
UNREVIEWED = "Unreviewed"

LIMITATIONS = (
    "This report is an assessment produced with automated and AI-assisted testing. Automated rules and AI "
    "judgment cannot cover every WCAG success criterion, and some barriers, such as the quality of captions, "
    "logical keyboard flow and the meaning of content, need testing by a person with assistive technology. "
    "A criterion with no findings has not been shown to be met. The report covers only the pages listed and the date shown. It is not a legal "
    "determination of compliance with Section 508, the ADA or any other law."
)

UNREVIEWED_NOTICE = (
    "Demonstration copy: this report includes findings that no reviewer has approved. They are labeled "
    "\"Unreviewed\" and may be wrong. Do not send it to a client."
)

TEXT_FIELDS = ("explanation", "element", "code_before", "code_after", "fix_description", "title")


@dataclass
class Issue:
    """Findings that share one rule and criterion: the same defect on one or more pages."""

    rule_id: str
    criterion: str
    criterion_name: str
    level: str
    section_508: str
    severity: str  # the worst severity among the findings
    source: str
    confidence: str  # the lowest confidence among the findings
    explanation: str
    urls: list[str]
    elements: list[str]
    findings: list[dict[str, Any]]  # every included store row, redacted
    unreviewed: bool  # at least one finding is awaiting human review
    tickets: list[dict[str, Any]] = field(default_factory=list)

    @property
    def status(self) -> str:
        return UNREVIEWED if self.unreviewed else "Approved"

    @property
    def ticket_ids(self) -> list[int]:
        return [t["id"] for t in self.tickets]

    @property
    def code_before(self) -> str:
        return next((t["code_before"] for t in self.tickets if t["code_before"]), "")

    @property
    def code_after(self) -> str:
        return self.tickets[0]["code_after"] if self.tickets else ""

    @property
    def fix_description(self) -> str:
        return self.tickets[0]["fix_description"] if self.tickets else ""


@dataclass
class Report:
    audit_id: str
    site: str
    audit_date: str
    generated_on: str
    pages: list[str]
    include_unreviewed: bool
    issues: list[Issue]
    findings: list[dict[str, Any]]  # included rows, flat, in store order
    counts: dict[str, int]
    limitations: str = LIMITATIONS
    standard: str = STANDARD

    @property
    def severity_counts(self) -> dict[str, int]:
        return {s: sum(f["severity"] == s for f in self.findings) for s in SEVERITY_ORDER}

    @property
    def issue_severity_counts(self) -> dict[str, int]:
        return {s: sum(i.severity == s for i in self.issues) for s in SEVERITY_ORDER}


def summarize_counts(rows: list[dict[str, Any]], include_unreviewed: bool) -> dict[str, int]:
    """How many findings an export would include or leave out, for the export panel and the report."""
    status = [r["review_status"] for r in rows]
    approved, pending, rejected = (status.count(s) for s in ("approved", "pending", "rejected"))
    included = approved + (pending if include_unreviewed else 0)
    return {
        "total": len(rows), "included": included, "approved": approved,
        "unreviewed_included": pending if include_unreviewed else 0,
        "excluded_unreviewed": 0 if include_unreviewed else pending, "excluded_rejected": rejected,
        "excluded": len(rows) - included,
    }


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["url"] = redact_url(out["url"])
    for key in TEXT_FIELDS:
        if isinstance(out.get(key), str):
            out[key] = redact(out[key])
    return out


def build_report(
    store: FindingStore, audit_id: str, include_unreviewed: bool | None = None, generated_on: str | None = None
) -> Report:
    if (audit := store.get_audit(audit_id)) is None:
        raise LookupError(f"no audit {audit_id!r}")
    if include_unreviewed is None:
        include_unreviewed = include_unreviewed_default()
    rows = store.list(audit_id)
    allowed = {"approved", "pending"} if include_unreviewed else {"approved"}  # rejected never appears
    tickets = store.list_tickets(audit_id)
    ticket_of = {f["id"]: t for t in tickets for f in t["findings"]}

    included = [_clean(r) for r in rows if r["review_status"] in allowed]
    criteria = load_criteria()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for f in included:
        groups.setdefault((f["wcag_criterion"], f["rule_id"]), []).append(f)

    issues = []
    for (criterion, rule), fs in sorted(groups.items(), key=lambda kv: tuple(map(int, kv[0][0].split("."))) + (kv[0][1],)):
        group_tickets = list({t["id"]: _clean_ticket(t) for f in fs if (t := ticket_of.get(f["id"]))}.values())
        issues.append(Issue(
            rule_id=rule, criterion=criterion, criterion_name=criteria[criterion]["name"],
            level=criteria[criterion]["level"], section_508=section_508(criterion),
            severity=min((f["severity"] for f in fs), key=SEVERITY_ORDER.index),
            source=fs[0]["source"],
            confidence=min((f["confidence"] for f in fs), key=lambda c: CONFIDENCE_ORDER.index(c) if c in CONFIDENCE_ORDER else -1),
            explanation=fs[0]["explanation"], urls=list(dict.fromkeys(f["url"] for f in fs)),
            elements=list(dict.fromkeys(f["element"] for f in fs)), findings=fs,
            unreviewed=any(f["review_status"] == "pending" for f in fs), tickets=group_tickets,
        ))
    issues.sort(key=lambda i: (tuple(map(int, i.criterion.split("."))), SEVERITY_ORDER.index(i.severity), i.rule_id))

    pages = [redact_url(p) for p in json.loads(audit.get("pages") or "[]")] or sorted({r["url"] for r in map(_clean, rows)})
    return Report(
        audit_id=audit_id, site=redact_url(audit["url"]), audit_date=str(audit["created_at"])[:10],
        generated_on=generated_on or date.today().isoformat(), pages=pages,
        include_unreviewed=include_unreviewed, issues=issues, findings=included,
        counts=summarize_counts(rows, include_unreviewed),
    )


def _clean_ticket(t: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in t.items() if k != "findings"}
    for key in TEXT_FIELDS:
        if isinstance(out.get(key), str):
            out[key] = redact(out[key])
    return out
