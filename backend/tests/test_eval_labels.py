"""Keeps evals/labels.json honest against the seeded pages in evals/pages."""

import json
from pathlib import Path

import pytest

from app.browser import load_page, run_axe
from app.wcag import is_known_criterion

EVALS = Path(__file__).resolve().parents[2] / "evals"
PAGES = EVALS / "pages"
LABELS = json.loads((EVALS / "labels.json").read_text(encoding="utf-8"))["pages"]
JUDGMENT_TYPES = {"alt-text-quality", "link-text-meaning", "heading-structure", "label-clarity"}


def test_every_page_file_is_labeled_exactly_once():
    labeled = [p["file"] for p in LABELS]
    assert len(labeled) == len(set(labeled))
    assert sorted(labeled) == sorted(f.name for f in PAGES.glob("*.html"))


def test_eval_set_size():
    assert 10 <= sum(1 for p in LABELS if p["issues"]) <= 15
    assert sum(1 for p in LABELS if not p["issues"]) >= 3


def test_label_schema():
    for page in LABELS:
        for issue in page["issues"]:
            assert issue["source"] in {"axe", "judgment"}
            assert (issue["type"] in JUDGMENT_TYPES) == (issue["source"] == "judgment")
            assert issue["selector"]
            assert issue["wcag"] and all(is_known_criterion(c) for c in issue["wcag"])


@pytest.mark.parametrize("page", LABELS, ids=lambda p: p["file"])
async def test_axe_agrees_with_labels(page):
    async with load_page((PAGES / page["file"]).as_uri()) as p:
        results = await run_axe(p)
    # Best-practice rules (e.g. heading-order) are not WCAG failures, so labels ignore them.
    found = {
        (v["id"], n["target"][0])
        for v in results["violations"]
        if any(t.startswith("wcag") for t in v.get("tags", []))
        for n in v["nodes"]
    }
    expected = {(i["type"], i["selector"]) for i in page["issues"] if i["source"] == "axe"}
    assert found == expected


BAD = json.loads((EVALS / "bad_labels.json").read_text(encoding="utf-8"))["pages"]
BAD_PAGES = {"home", "news", "tickets", "survey", "template"}


def test_bad_labels_cover_the_five_before_pages():
    assert {p["url"].rsplit("/", 1)[1].removesuffix(".html") for p in BAD} == BAD_PAGES
    for page in BAD:
        assert page["url"].startswith("https://www.w3.org/WAI/demos/bad/before/")
        assert page["report"].startswith("https://www.w3.org/WAI/demos/bad/before/reports/")
        assert len(page["page_sha256"]) == len(page["report_sha256"]) == 64


def test_bad_label_schema():
    for page in BAD:
        criteria = [i["wcag"] for i in page["issues"]]
        assert len(criteria) == len(set(criteria)), "one label per criterion per page"
        for issue in page["issues"]:
            assert is_known_criterion(issue["wcag"])
            assert issue["level"] in {"A", "AA"}
            assert issue["in_scope"] == bool(issue["detectable_by"])
            assert set(issue["detectable_by"]) <= {"axe", "judgment"}
