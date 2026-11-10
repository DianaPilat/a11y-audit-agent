import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from app import browser
from app.mcp_server import mcp, session

FIXTURES = Path(__file__).parent / "fixtures"
BAD = (FIXTURES / "bad.html").as_uri()
LINKS = (FIXTURES / "links.html").as_uri()
JUDGMENT = (FIXTURES / "judgment.html").as_uri()


@asynccontextmanager
async def connected():
    """In-memory client connected to the server; closes the shared browser session afterwards."""
    try:
        async with Client(mcp) as client:
            yield client
    finally:
        await session.close()


def payload(result):
    """Parse a tool result's text content as JSON."""
    return json.loads(result.content[0].text)


async def test_lists_the_four_tools():
    async with connected() as client:
        tools = await client.list_tools()
        assert {t.name for t in tools.tools} == {"navigate", "list_links", "run_axe", "get_page_content", "get_dom_snippet"}


async def test_tool_annotations():
    async with connected() as client:
        tools = {t.name: t.annotations for t in (await client.list_tools()).tools}
    assert set(tools) == {"navigate", "list_links", "run_axe", "get_page_content", "get_dom_snippet"}
    for name, annotations in tools.items():
        assert annotations.read_only_hint is True, name
        assert annotations.destructive_hint is False, name
        assert annotations.idempotent_hint is True, name
    assert tools["navigate"].open_world_hint is True
    for name in ("list_links", "run_axe", "get_page_content", "get_dom_snippet"):
        assert tools[name].open_world_hint is False, name


async def test_navigate_then_run_axe():
    async with connected() as client:
        nav = payload(await client.call_tool("navigate", {"url": BAD}))
        assert nav["title"] == "Bad page"
        results = payload(await client.call_tool("run_axe", {}))
        assert {"image-alt", "label"} <= {v["id"] for v in results["violations"]}
        assert results["violations"][0]["nodes"][0]["failureSummary"]


async def test_list_links_same_site_only():
    async with connected() as client:
        await client.call_tool("navigate", {"url": LINKS})
        links = payload(await client.call_tool("list_links", {}))["links"]
        assert [Path(u).name for u in links] == ["about.html", "contact.html"]


async def test_get_dom_snippet_returns_html():
    async with connected() as client:
        await client.call_tool("navigate", {"url": BAD})
        result = await client.call_tool("get_dom_snippet", {"selector": "img"})
        assert result.content[0].text.startswith("<img")


async def test_get_dom_snippet_no_match_is_an_error():
    async with connected() as client:
        await client.call_tool("navigate", {"url": BAD})
        result = await client.call_tool("get_dom_snippet", {"selector": "#nope"})
        assert result.is_error
        assert "No element matches" in result.content[0].text


async def test_tools_before_navigate_are_errors():
    async with connected() as client:
        result = await client.call_tool("run_axe", {})
        assert result.is_error
        assert "navigate" in result.content[0].text


async def test_navigate_bad_url_is_an_error_not_a_crash():
    async with connected() as client:
        result = await client.call_tool("navigate", {"url": "http://localhost:1/nothing"})
        assert result.is_error
        assert "Could not load" in result.content[0].text


async def test_runs_as_a_stdio_server():
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"])
    async with Client(params) as client:
        tools = await client.list_tools()
        assert "run_axe" in {t.name for t in tools.tools}
        nav = payload(await client.call_tool("navigate", {"url": BAD}))
        assert nav["title"] == "Bad page"


async def test_get_page_content_gives_judgment_inputs():
    async with connected() as client:
        await client.call_tool("navigate", {"url": JUDGMENT})
        content = payload(await client.call_tool("get_page_content", {}))
    alts = {i["src"]: i["alt"] for i in content["images"]["items"]}
    assert alts == {"IMG_0042.jpg": "IMG_0042.jpg", "spacer.gif": "", "team.png": None}
    assert [l["text"] for l in content["links"]["items"]] == ["click here", "Pricing plans"]
    assert [(h["level"], h["text"]) for h in content["headings"]["items"]] == [(2, "Welcome"), (4, "Details")]
    fields = {f["name"]: f for f in content["form_fields"]["items"]}
    assert fields["email"]["label"] == "Email address"
    assert fields["q"]["label"] is None and fields["q"]["placeholder"] == "Search"
    assert fields["q"]["selector"] == "#q"


async def test_get_page_content_caps_items():
    async with connected() as client:
        await client.call_tool("navigate", {"url": JUDGMENT})
        page = session.require_page()
        content = await browser.get_page_content(page, max_items=1)
    assert content["images"]["total"] == 3 and len(content["images"]["items"]) == 1
