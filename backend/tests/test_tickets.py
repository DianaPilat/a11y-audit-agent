import json

import pytest
from pydantic import ValidationError

from app.findings import Finding, FindingStore
from app.tickets import Ticket, build_tickets_server, export_json, export_markdown, make_create_ticket_tool

def _finding(url="http://x", rule="image-alt", crit="1.1.1", sev="critical", element="img.hero"):
    return Finding(
        url=url, rule_id=rule, wcag_criterion=crit, severity=sev, element=element,
        explanation="Screen reader users hear no description of this image. Add alt text.",
        source="axe-core", confidence="high",
    )


TICKET = {
    "finding_ids": [1],
    "title": "Add alt text to the hero image",
    "fix_description": "Give the hero image an alt attribute describing what it shows.",
    "code_before": '<img class="hero" src="a.png">',
    "code_after": '<img class="hero" src="a.png" alt="DESCRIBE THE IMAGE">',
}


def _payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


@pytest.fixture
def store():
    s = FindingStore(":memory:")
    s.save("a1", _finding())
    return s


@pytest.mark.parametrize(
    "override",
    [
        {"finding_ids": []}, {"finding_ids": [0]}, {"finding_ids": [1, 1]},
        {"title": "short"}, {"fix_description": "too short"}, {"code_after": ""},
    ],
)
def test_ticket_rejects_invalid(override):
    with pytest.raises(ValidationError):
        Ticket(**{**TICKET, **override})


def test_code_before_is_optional():
    assert Ticket(**{k: v for k, v in TICKET.items() if k != "code_before"}).code_before == ""


async def test_create_ticket_stores(store):
    tool = make_create_ticket_tool(store, "a1")
    result = await tool.handler(TICKET)
    assert "is_error" not in result
    assert _payload(result) == {"saved": True, "id": 1}
    (row,) = store.list_tickets("a1")
    assert row["title"] == TICKET["title"]
    assert [f["rule_id"] for f in row["findings"]] == ["image-alt"]


async def test_one_ticket_groups_findings_across_pages():
    store = FindingStore(":memory:")
    for url in ("http://x/a", "http://x/b", "http://x/c"):
        store.save("a1", _finding(url=url, rule="region", crit="1.3.1", sev="moderate", element="div"))
    result = await make_create_ticket_tool(store, "a1").handler({**TICKET, "finding_ids": [1, 2, 3]})
    assert _payload(result)["saved"] is True
    (row,) = store.list_tickets("a1")
    assert [f["url"] for f in row["findings"]] == ["http://x/a", "http://x/b", "http://x/c"]


async def test_finding_goes_in_one_ticket_only(store):
    store.save("a1", _finding(element="img.other"))
    tool = make_create_ticket_tool(store, "a1")
    await tool.handler(TICKET)
    result = await tool.handler({**TICKET, "finding_ids": [1, 2]})
    assert result["is_error"] is True
    assert "finding 1 is in ticket 1" in _payload(result)["errors"][0]
    assert len(store.list_tickets("a1")) == 1  # the rejected ticket stored nothing
    assert _payload(await tool.handler({**TICKET, "finding_ids": [2]}))["saved"] is True


async def test_create_ticket_rejects_unknown_finding(store):
    tool = make_create_ticket_tool(store, "a1")
    result = await tool.handler({**TICKET, "finding_ids": [1, 99]})
    assert result["is_error"] is True
    assert "finding_ids" in _payload(result)["errors"][0]
    # a finding from another audit is not visible either
    assert (await make_create_ticket_tool(store, "other").handler(TICKET))["is_error"] is True
    assert store.list_tickets("a1") == []


async def test_create_ticket_reports_validation_errors(store):
    tool = make_create_ticket_tool(store, "a1")
    result = await tool.handler({**TICKET, "title": "x", "code_after": ""})
    assert result["is_error"] is True
    errors = _payload(result)["errors"]
    assert any(e.startswith("title") for e in errors) and any(e.startswith("code_after") for e in errors)


def test_server_config(store):
    server = build_tickets_server(store, "a1")
    assert server["type"] == "sdk" and server["name"] == "tickets"


def test_old_per_finding_tickets_table_is_replaced(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE tickets (id INTEGER PRIMARY KEY, audit_id TEXT, finding_id INTEGER)")
    db.commit()
    db.close()
    store = FindingStore(path)
    assert store.list_tickets("a1") == []


async def test_exports():
    store = FindingStore(":memory:")
    store.save("a1", _finding(url="http://x/a", rule="region", crit="1.3.1", sev="moderate", element="div"))
    store.save("a1", _finding(url="http://x/b", rule="landmark", crit="2.4.1", sev="serious", element="body"))
    await make_create_ticket_tool(store, "a1").handler({**TICKET, "finding_ids": [1, 2]})
    rows = store.list_tickets("a1")
    assert json.loads(export_json(rows))[0]["code_after"] == TICKET["code_after"]
    md = export_markdown(rows)
    assert "## Add alt text to the hero image" in md
    assert "**Severity:** serious" in md  # the worst of the group
    assert "**WCAG 2.1:** 1.3.1, 2.4.1" in md
    assert "**Occurrences (2):**" in md and "http://x/a: `div`" in md and "http://x/b: `body`" in md
    assert TICKET["code_before"] in md and TICKET["code_after"] in md
    assert "No tickets" in export_markdown([])
