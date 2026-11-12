import json

import pytest
from pydantic import ValidationError

from app.findings import Finding, FindingStore, Severity, build_findings_server, make_save_finding_tool

VALID = {
    "url": "http://x",
    "rule_id": "image-alt",
    "wcag_criterion": "1.1.1",
    "severity": "critical",
    "element": "img.hero",
    "explanation": "Screen reader users hear no description of this image. Add meaningful alt text.",
    "source": "axe-core",
    "confidence": "high",
}


def _payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def test_finding_accepts_valid():
    assert Finding(**VALID).severity is Severity.CRITICAL


@pytest.mark.parametrize(
    "override",
    [
        {"wcag_criterion": "WCAG 1.1.1"},
        {"wcag_criterion": "1.1"},
        {"wcag_criterion": "1.1.9"},  # well-formed but not a real criterion
        {"wcag_criterion": "1.4.6"},  # AAA: out of scope
        {"severity": "urgent"},
        {"element": ""},
        {"explanation": "too short"},
        {"rule_id": ""},
        {"url": ""},
    ],
)
def test_finding_rejects_invalid(override):
    with pytest.raises(ValidationError):
        Finding(**{**VALID, **override})


def test_store_saves_and_dedupes():
    store = FindingStore(":memory:")
    finding = Finding(**VALID)
    first_id, created = store.save("a1", finding)
    again_id, created_again = store.save("a1", finding)
    assert created and not created_again
    assert first_id == again_id
    assert [f["rule_id"] for f in store.list("a1")] == ["image-alt"]
    assert store.list("other") == []


def test_store_creates_parent_dir(tmp_path):
    path = tmp_path / "nested" / "f.db"
    FindingStore(path).close()
    assert path.exists()


async def test_save_finding_tool_stores():
    store = FindingStore(":memory:")
    tool = make_save_finding_tool(store, "a1")
    result = await tool.handler(VALID)
    assert "is_error" not in result
    assert _payload(result) == {"saved": True, "id": 1, "duplicate": False}
    assert store.list("a1")[0]["url"] == "http://x"
    assert _payload(await tool.handler(VALID))["duplicate"] is True


async def test_save_finding_tool_reports_validation_errors():
    store = FindingStore(":memory:")
    tool = make_save_finding_tool(store, "a1")
    result = await tool.handler({**VALID, "wcag_criterion": "nope", "severity": "urgent"})
    assert result["is_error"] is True
    errors = _payload(result)["errors"]
    assert any(e.startswith("wcag_criterion") for e in errors)
    assert any(e.startswith("severity") for e in errors)
    assert store.list("a1") == []


def test_tool_schema_lists_required_fields():
    tool = make_save_finding_tool(FindingStore(":memory:"), "a1")
    assert set(tool.input_schema["required"]) == {
        "url", "rule_id", "wcag_criterion", "severity", "element", "explanation", "source", "confidence",
    }


def test_server_config():
    server = build_findings_server(FindingStore(":memory:"), "a1")
    assert server["type"] == "sdk" and server["name"] == "findings"


@pytest.mark.parametrize(
    "override",
    [
        {"source": "ai-assessed"},  # axe rule id but claims AI
        {"rule_id": "judgment-alt-text"},  # judgment rule id but claims axe
        {"confidence": "unknown"},
        {"confidence": "certain"},
        {"source": "manual"},
    ],
)
def test_finding_rejects_bad_source_or_confidence(override):
    with pytest.raises(ValidationError):
        Finding(**{**VALID, **override})


def test_finding_requires_source_and_confidence():
    for field in ("source", "confidence"):
        with pytest.raises(ValidationError):
            Finding(**{k: v for k, v in VALID.items() if k != field})


def test_store_round_trips_source_and_confidence():
    store = FindingStore(":memory:")
    store.save("a1", Finding(**{**VALID, "rule_id": "judgment-alt-text", "source": "ai-assessed", "confidence": "low"}))
    row = store.list("a1")[0]
    assert (row["source"], row["confidence"]) == ("ai-assessed", "low")


def test_migration_adds_columns_to_old_database(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE findings (id INTEGER PRIMARY KEY AUTOINCREMENT, audit_id TEXT NOT NULL, url TEXT NOT NULL,"
        " rule_id TEXT NOT NULL, wcag_criterion TEXT NOT NULL, severity TEXT NOT NULL, element TEXT NOT NULL,"
        " explanation TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " UNIQUE (audit_id, url, rule_id, element))"
    )
    for rule in ("image-alt", "judgment-link-text"):
        db.execute("INSERT INTO findings (audit_id, url, rule_id, wcag_criterion, severity, element, explanation)"
                   " VALUES ('a', 'http://x', ?, '1.1.1', 'minor', 'a', 'x')", (rule,))
    db.commit()
    db.close()
    for _ in range(2):  # a second open must be a no-op
        store = FindingStore(path)
        rows = {r["rule_id"]: r for r in store.list("a")}
        store.close()
    assert rows["image-alt"]["source"] == "axe-core"
    assert rows["judgment-link-text"]["source"] == "ai-assessed"
    assert {r["confidence"] for r in rows.values()} == {"unknown"}  # not invented for old rows
