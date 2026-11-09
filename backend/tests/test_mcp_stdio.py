"""Integration tests: the a11y-browser server as a real stdio subprocess, driven by the MCP client."""

import json
import sys
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

BACKEND = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
BAD = (FIXTURES / "bad.html").as_uri()
LINKS = (FIXTURES / "links.html").as_uri()
UNREACHABLE = "http://localhost:1/nothing"

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=BACKEND)


def payload(result):
    """Parse a successful tool result's text content as JSON."""
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


async def test_stdio_lists_tools_with_schemas():
    async with Client(SERVER) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"navigate", "list_links", "run_axe", "get_dom_snippet"}
    assert tools["navigate"].input_schema["required"] == ["url"]
    assert tools["get_dom_snippet"].input_schema["required"] == ["selector"]
    assert all(t.description for t in tools.values())


async def test_stdio_full_audit_flow_on_bad_fixture():
    async with Client(SERVER) as client:
        nav = payload(await client.call_tool("navigate", {"url": BAD}))
        assert set(nav) == {"url", "title", "status"}
        assert nav["url"] == BAD
        assert nav["title"] == "Bad page"

        axe = payload(await client.call_tool("run_axe", {}))
        assert {"axe_version", "violations", "incomplete", "passes_count"} <= set(axe)
        assert axe["passes_count"] > 0
        by_id = {v["id"]: v for v in axe["violations"]}
        assert {"image-alt", "label", "color-contrast"} <= set(by_id)
        for violation in axe["violations"]:
            assert {"id", "impact", "help", "help_url", "tags", "category", "wcag_criteria", "nodes"} <= set(violation)
            assert violation["nodes"], violation["id"]
            assert {"target", "html", "failureSummary"} <= set(violation["nodes"][0])
        assert by_id["image-alt"]["impact"] == "critical"
        assert by_id["image-alt"]["wcag_criteria"] == ["wcag111"]

        # A violation's target feeds straight back into get_dom_snippet.
        target = by_id["label"]["nodes"][0]["target"][0]
        snippet = await client.call_tool("get_dom_snippet", {"selector": target})
        assert not snippet.is_error
        assert snippet.content[0].text.startswith("<input")


async def test_stdio_list_links_on_links_fixture():
    async with Client(SERVER) as client:
        payload(await client.call_tool("navigate", {"url": LINKS}))
        links = payload(await client.call_tool("list_links", {}))
    assert set(links) == {"links"}
    assert [Path(u).name for u in links["links"]] == ["about.html", "contact.html"]


async def test_stdio_navigate_unreachable_url_is_a_clear_error_and_server_survives():
    async with Client(SERVER) as client:
        failed = await client.call_tool("navigate", {"url": UNREACHABLE})
        assert failed.is_error
        message = failed.content[0].text
        assert "Could not load" in message
        assert UNREACHABLE in message

        # The server process is still alive and usable after the failure.
        nav = payload(await client.call_tool("navigate", {"url": BAD}))
        assert nav["title"] == "Bad page"
        axe = payload(await client.call_tool("run_axe", {}))
        assert axe["violations"]
