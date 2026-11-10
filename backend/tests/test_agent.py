import os
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from app import agent
from app.findings import FindingStore

FIXTURES = Path(__file__).parent / "fixtures"


def _result(**kw) -> ResultMessage:
    base = dict(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=2,
        session_id="s", total_cost_usd=0.01, usage={"input_tokens": 5}, result="final report",
    )
    return ResultMessage(**{**base, **kw})


def test_build_options_scopes_tools():
    opts = agent.build_options(FindingStore(":memory:"), "a1", "http://x")
    assert opts.tools == []
    assert opts.allowed_tools == [
        "mcp__a11y-browser__navigate",
        "mcp__a11y-browser__list_links",
        "mcp__a11y-browser__run_axe",
        "mcp__a11y-browser__get_dom_snippet",
        "mcp__findings__save_finding",
    ]
    assert set(opts.mcp_servers) == {"a11y-browser", "findings"}
    server = opts.mcp_servers["a11y-browser"]
    assert server["args"] == ["-m", "app.mcp_server"]
    assert Path(server["env"]["PYTHONPATH"]) == agent.BACKEND


async def test_audit_page_collects_report_tools_and_cost(monkeypatch):
    seen = {}

    async def fake_query(prompt, options):
        seen["prompt"] = prompt
        yield AssistantMessage(
            content=[
                ToolUseBlock(id="1", name="mcp__a11y-browser__navigate", input={"url": "x"}),
                TextBlock(text="draft"),
            ],
            model="m",
        )
        yield _result()

    monkeypatch.setattr(agent, "query", fake_query)
    store = FindingStore(":memory:")
    run = await agent.audit_page("http://x", store=store)
    assert "http://x" in seen["prompt"]
    assert run.report == "final report"
    assert run.tool_calls == ["mcp__a11y-browser__navigate"]
    assert run.cost_usd == 0.01
    assert run.usage == {"input_tokens": 5}
    assert run.findings == []


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 (costs API tokens)")
async def test_live_audit_bad_page():
    run = await agent.audit_page((FIXTURES / "bad.html").as_uri())
    for rule in ("image-alt", "label", "color-contrast"):
        assert rule in run.report
    assert "mcp__a11y-browser__navigate" in run.tool_calls
    assert "mcp__a11y-browser__run_axe" in run.tool_calls
    assert "mcp__findings__save_finding" in run.tool_calls
    assert {f["rule_id"] for f in run.findings} >= {"image-alt", "label", "color-contrast"}
