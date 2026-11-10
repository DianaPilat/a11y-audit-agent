"""The eval harness's scoring, checked offline against hand-built findings."""

import json

from app.evals import format_report, load_labels, score_bad, score_seeded


def _f(rule, wcag, element="x"):
    return {"rule_id": rule, "wcag_criterion": wcag, "element": element, "severity": "serious", "explanation": "e"}


LABELS = [
    {"file": "a.html", "issues": [
        {"type": "image-alt", "selector": "#a", "wcag": ["1.1.1"], "source": "axe"},
        {"type": "image-alt", "selector": "#b", "wcag": ["1.1.1"], "source": "axe"},
        {"type": "link-text-meaning", "selector": "#more", "wcag": ["2.4.4"], "source": "judgment"},
        {"type": "link-text-meaning", "selector": "#here", "wcag": ["2.4.4"], "source": "judgment"},
    ]},
    {"file": "clean.html", "issues": []},
]


def test_seeded_scoring():
    pages = {
        "a.html": {"findings": [
            _f("image-alt", "1.1.1", "#a"),  # grouped axe finding covers both image-alt labels
            _f("judgment-link-text", "2.4.4", "a#more"),  # right element, right criterion
            _f("judgment-link-text", "1.1.1", "#other"),  # wrong element: false positive
            _f("color-contrast", "1.4.3", "#c"),  # unlabeled: false positive
        ]},
        "clean.html": {"findings": [_f("label", "1.3.1")]},
    }
    s = score_seeded(LABELS, pages)
    alt = s["by_type"]["image-alt"]
    assert (alt["precision"], alt["recall"], alt["wcag_accuracy"]) == (1.0, 1.0, 1.0)
    link = s["by_type"]["link-text-meaning"]
    assert (link["precision"], link["recall"]) == (0.5, 0.5)
    assert s["by_type"]["color-contrast"]["precision"] == 0
    assert s["overall"]["findings"] == 5
    assert s["overall"]["true_positives"] == 2
    assert s["overall"]["found"] == 3 and s["overall"]["labels"] == 4
    assert s["judgment"]["labels"] == 2 and s["axe"]["labels"] == 2
    assert s["clean_pages_false_positives"] == {"clean.html": 1}


def test_wcag_accuracy_counts_wrong_criterion_on_a_matched_finding():
    pages = {"a.html": {"findings": [_f("image-alt", "1.4.3", "#a"), _f("image-alt", "1.1.1", "#b")]}}
    s = score_seeded(LABELS, pages)["by_type"]["image-alt"]
    assert s["true_positives"] == 2 and s["wcag_correct"] == 1 and s["wcag_accuracy"] == 0.5


def test_failed_and_missing_pages_count_as_missed_not_ignored():
    pages = {"a.html": {"findings": [], "error": "boom"}}
    s = score_seeded(LABELS, pages)
    assert s["failed_pages"] == ["a.html", "clean.html"]
    assert s["overall"]["recall"] == 0 and s["overall"]["precision"] is None


BAD = [{"url": "https://w3.example/home.html", "issues": [
    {"wcag": "1.1.1", "in_scope": True}, {"wcag": "2.1.1", "in_scope": False}, {"wcag": "2.4.4", "in_scope": True},
]}]


def test_bad_scoring_matches_by_criterion():
    pages = {"https://w3.example/home.html": {"findings": [
        _f("image-alt", "1.1.1"), _f("judgment-alt-text", "1.1.1"), _f("color-contrast", "1.4.3"),
    ]}}
    s = score_bad(BAD, pages)
    assert (s["true_positives"], s["findings"]) == (2, 3)
    assert (s["found_in_scope"], s["labels_in_scope"]) == (1, 2)
    assert (s["found_all"], s["labels_all"]) == (1, 3)
    assert s["by_page"]["https://w3.example/home.html"]["missed_in_scope"] == ["2.4.4"]


def test_real_labels_score_and_report():
    seeded = {p["file"]: {"findings": [], "cost_usd": 0.01, "seconds": 5} for p in load_labels("labels.json")}
    bad = {p["url"]: {"findings": [], "cost_usd": 0.02, "seconds": 9} for p in load_labels("bad_labels.json")}
    report = format_report({"model": "m", "started": "t", "seeded": seeded, "bad": bad})
    assert "Seeded pages" in report and "W3C BAD pages" in report and "image-alt" in report
    json.dumps(score_seeded(load_labels("labels.json"), seeded))  # stays serializable for results files
