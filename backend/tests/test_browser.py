import json
from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError

from app.browser import audit_page, load_page, run_axe, save_results

FIXTURES = Path(__file__).parent / "fixtures"
BAD = (FIXTURES / "bad.html").as_uri()
CLEAN = (FIXTURES / "clean.html").as_uri()


async def test_run_axe_reports_known_violations():
    async with load_page(BAD) as page:
        results = await run_axe(page)
    ids = {v["id"] for v in results["violations"]}
    assert {"image-alt", "label"} <= ids
    image_alt = next(v for v in results["violations"] if v["id"] == "image-alt")
    assert image_alt["nodes"][0]["target"]
    assert image_alt["nodes"][0]["html"].startswith("<img")


async def test_run_axe_clean_page_has_no_violations():
    async with load_page(CLEAN) as page:
        results = await run_axe(page)
    assert results["violations"] == []
    assert results["passes_count"] > 0
    assert isinstance(results["incomplete"], list)
    assert "passes" not in results and "inapplicable" not in results


def test_save_results_round_trips(tmp_path):
    results = {"axe_version": "4.10.2", "violations": []}
    path = save_results("https://example.com/a?b=1", results, tmp_path)
    assert path.parent == tmp_path
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["url"] == "https://example.com/a?b=1"
    assert saved["violations"] == []
    assert "audited_at" in saved


async def test_audit_page_writes_file(tmp_path):
    path = await audit_page(BAD, tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["violations"]


async def test_load_page_bad_url_raises():
    with pytest.raises(PlaywrightError):
        async with load_page("http://localhost:1/nothing", timeout_ms=3000):
            pass


NO_MAIN = (FIXTURES / "no_main.html").as_uri()
BG_IMAGE = (FIXTURES / "bg_image.html").as_uri()


async def test_tags_are_carried_through_unchanged():
    async with load_page(BAD) as page:
        results = await run_axe(page)
    image_alt = next(v for v in results["violations"] if v["id"] == "image-alt")
    assert image_alt["tags"]
    assert any(t.startswith("wcag") for t in image_alt["tags"])
    assert "best-practice" not in image_alt["tags"]


async def test_category_separates_wcag_from_best_practice():
    async with load_page(NO_MAIN) as page:
        results = await run_axe(page)
    by_id = {v["id"]: v for v in results["violations"]}
    assert by_id["region"]["category"] == "best-practice"
    assert by_id["landmark-one-main"]["category"] == "best-practice"
    assert by_id["image-alt"]["category"] == "wcag"
    assert "wcag111" in by_id["image-alt"]["wcag_criteria"]
    assert by_id["region"]["wcag_criteria"] == []


async def test_nodes_include_failure_summary():
    async with load_page(BAD) as page:
        results = await run_axe(page)
    image_alt = next(v for v in results["violations"] if v["id"] == "image-alt")
    node = image_alt["nodes"][0]
    assert set(node) == {"target", "html", "failureSummary"}
    assert node["failureSummary"]


async def test_incomplete_results_are_captured_with_same_fields():
    async with load_page(BG_IMAGE) as page:
        results = await run_axe(page)
    contrast = next((i for i in results["incomplete"] if i["id"] == "color-contrast"), None)
    assert contrast is not None, "color-contrast missing from incomplete"
    assert contrast["category"] == "wcag"
    assert contrast["tags"]
    node = contrast["nodes"][0]
    assert node["target"] and node["html"] and node["failureSummary"]

