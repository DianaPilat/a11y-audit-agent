import os
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, ToolResultBlock, ToolUseBlock, UserMessage

from app import agent
from app.findings import Finding, FindingStore

FIXTURES = Path(__file__).parent / "fixtures"


def _result(**kw) -> ResultMessage:
    base = dict(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=2,
        session_id="s", total_cost_usd=0.01, usage={"input_tokens": 5}, result="final report",
    )
    return ResultMessage(**{**base, **kw})


def test_crawler_options_are_scoped():
    opts = agent.crawler_options()
    assert opts.tools == []
    assert opts.allowed_tools == [
        "mcp__a11y-browser__navigate",
        "mcp__a11y-browser__list_links",
    ]
    assert set(opts.mcp_servers) == {"a11y-browser"}
    assert opts.model == agent.CRAWLER_MODEL
    server = opts.mcp_servers["a11y-browser"]
    assert server["args"] == ["-m", "app.mcp_server"]
    assert Path(server["env"]["PYTHONPATH"]) == agent.BACKEND


def test_auditor_options_are_scoped():
    opts = agent.auditor_options(FindingStore(":memory:"), "a1")
    assert opts.tools == []
    assert opts.allowed_tools == [
        "mcp__a11y-browser__navigate",
        "mcp__a11y-browser__run_axe",
        "mcp__a11y-browser__get_page_content",
        "mcp__a11y-browser__get_dom_snippet",
        "mcp__wcag__lookup_wcag",
        "mcp__findings__save_finding",
    ]
    assert set(opts.mcp_servers) == {"a11y-browser", "findings", "wcag"}


def test_writer_options_are_scoped():
    opts = agent.writer_options(FindingStore(":memory:"), "a1")
    assert opts.tools == []
    assert opts.allowed_tools == [
        "mcp__a11y-browser__navigate",
        "mcp__a11y-browser__get_dom_snippet",
        "mcp__tickets__create_ticket",
    ]
    assert set(opts.mcp_servers) == {"a11y-browser", "tickets"}


def test_parse_page_urls_drops_urls_list_links_never_returned():
    reply = "https://x.com/\nhttps://x.com/about\nhttps://x.com/real"
    seen = {"https://x.com/", "https://x.com/real"}
    assert agent.parse_page_urls(reply, "https://x.com/", 10, seen) == ["https://x.com/", "https://x.com/real"]


def test_parse_page_urls_keeps_start_first_same_origin_deduped_and_capped():
    reply = """\
Pages found:
1. https://x.com/a
- https://x.com/b.
https://other.com/c
https://x.com/a
https://x.com/a#top
`https://x.com/d`
"""
    assert agent.parse_page_urls(reply, "https://x.com/", 10) == [
        "https://x.com/", "https://x.com/a", "https://x.com/b", "https://x.com/d",
    ]
    assert agent.parse_page_urls(reply, "https://x.com/", 2) == ["https://x.com/", "https://x.com/a"]
    assert agent.parse_page_urls("", "https://x.com/", 5) == ["https://x.com/"]


def _fake_query(store, crawl_reply, calls, fail_on=()):
    """Stands in for the SDK: the crawler returns crawl_reply; each auditor saves one finding."""

    async def fake_query(prompt, options):
        calls.append(prompt)
        if prompt.startswith("Find pages"):
            yield AssistantMessage(
                content=[ToolUseBlock(id="1", name="mcp__a11y-browser__list_links", input={})], model="m"
            )
            # list_links returned every URL the crawler goes on to report
            yield UserMessage(
                content=[ToolResultBlock(tool_use_id="1", content=[{"type": "text", "text": crawl_reply}])]
            )
            yield _result(result=crawl_reply)
            return
        if prompt.startswith("Write tickets"):
            yield _result(result="tickets written")
            return
        page = prompt.removeprefix("Audit this page: ")
        if page in fail_on:
            raise RuntimeError("boom")
        store.save(
            "a1",
            Finding(
                url=page, rule_id="image-alt", wcag_criterion="1.1.1", severity="critical",
                element="img", explanation="Screen reader users get no description. Add alt text.",
            ),
        )
        yield _result(result=f"{page}: 1 finding")

    return fake_query


@pytest.fixture
def fixed_audit_id(monkeypatch):
    monkeypatch.setattr(agent.uuid, "uuid4", lambda: type("U", (), {"hex": "a1"})())


async def test_audit_site_audits_every_crawled_page(monkeypatch, fixed_audit_id):
    store = FindingStore(":memory:")
    calls: list[str] = []
    reply = "https://x.com/\nhttps://x.com/a\nhttps://x.com/b\nhttps://off.com/z"
    monkeypatch.setattr(agent, "query", _fake_query(store, reply, calls))

    run = await agent.audit_site("https://x.com/", max_pages=5, store=store)

    assert run.pages == ["https://x.com/", "https://x.com/a", "https://x.com/b"]
    assert [c for c in calls if c.startswith("Audit")] == [f"Audit this page: {u}" for u in run.pages]
    assert "Start URL: https://x.com/" in calls[0] and "Page limit: 5" in calls[0]
    assert {f["url"] for f in run.findings} == set(run.pages)
    assert run.cost_usd == pytest.approx(0.05)  # crawler + 3 auditors + 1 ticket writer
    writer_calls = [c for c in calls if c.startswith("Write tickets")]
    assert len(writer_calls) == 1 and "3 findings" in writer_calls[0]
    assert run.tool_calls == ["mcp__a11y-browser__list_links"]
    assert "Audited 3 of 3 pages, saved 3 findings and 0 tickets." in run.report


async def test_audit_site_single_page_skips_crawler(monkeypatch, fixed_audit_id):
    store = FindingStore(":memory:")
    calls: list[str] = []
    monkeypatch.setattr(agent, "query", _fake_query(store, "", calls))
    run = await agent.audit_site("http://x", max_pages=1, store=store)
    assert calls[0] == "Audit this page: http://x"
    assert run.pages == ["http://x"]


async def test_audit_site_falls_back_to_start_url_when_crawler_fails(monkeypatch, fixed_audit_id):
    store = FindingStore(":memory:")
    calls: list[str] = []
    inner = _fake_query(store, "", calls)

    async def fake_query(prompt, options):
        if prompt.startswith("Find pages"):
            raise RuntimeError("crawler down")
        async for m in inner(prompt, options):
            yield m

    monkeypatch.setattr(agent, "query", fake_query)
    run = await agent.audit_site("https://x.com/", max_pages=5, store=store)
    assert run.pages == ["https://x.com/"]
    assert len(run.findings) == 1


async def test_audit_site_continues_after_a_failed_page(monkeypatch, fixed_audit_id):
    store = FindingStore(":memory:")
    calls: list[str] = []
    reply = "https://x.com/\nhttps://x.com/a"
    monkeypatch.setattr(agent, "query", _fake_query(store, reply, calls, fail_on={"https://x.com/"}))
    run = await agent.audit_site("https://x.com/", max_pages=5, store=store)
    assert run.failed_pages == ["https://x.com/"]
    assert [f["url"] for f in run.findings] == ["https://x.com/a"]
    assert "Failed pages: https://x.com/" in run.report


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 (costs API tokens)")
async def test_live_audit_bad_page():
    run = await agent.audit_site((FIXTURES / "bad.html").as_uri(), max_pages=1)
    assert "mcp__a11y-browser__run_axe" in run.tool_calls
    assert "mcp__wcag__lookup_wcag" in run.tool_calls
    assert "mcp__findings__save_finding" in run.tool_calls
    assert {f["rule_id"] for f in run.findings} >= {"image-alt", "label", "color-contrast"}
