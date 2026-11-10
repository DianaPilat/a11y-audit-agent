import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from app import browser
from app.mcp_server import _Session, session
from tests.test_mcp_server import BAD, connected, payload


class FakeResponse:
    def __init__(self, status):
        self.status = status


class FlakyPage:
    """Stands in for a Playwright page: goto raises or returns each scripted outcome in turn."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def goto(self, url, **kw):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(browser, "RETRY_BACKOFF_S", 0.0)


async def test_navigate_retries_transient_errors_then_succeeds():
    page = FlakyPage([PlaywrightTimeoutError("Timeout 30000ms exceeded"), PlaywrightError("net::ERR_CONNECTION_RESET"), FakeResponse(200)])
    response = await browser.goto_with_retry(page, "https://x.com/")
    assert response.status == 200 and page.calls == 3


async def test_navigate_retries_bad_gateway_and_returns_last_response():
    page = FlakyPage([FakeResponse(503)] * 3)
    response = await browser.goto_with_retry(page, "https://x.com/")
    assert response.status == 503 and page.calls == 3


async def test_navigate_does_not_retry_permanent_errors():
    page = FlakyPage([PlaywrightError("net::ERR_NAME_NOT_RESOLVED at https://nope.invalid/")])
    with pytest.raises(PlaywrightError):
        await browser.goto_with_retry(page, "https://nope.invalid/")
    assert page.calls == 1


async def test_navigate_gives_up_after_the_last_attempt():
    page = FlakyPage([PlaywrightTimeoutError("Timeout")] * 3)
    with pytest.raises(PlaywrightTimeoutError):
        await browser.goto_with_retry(page, "https://x.com/")
    assert page.calls == 3


async def test_guard_turns_a_hang_into_a_tool_error():
    async def hang():
        await asyncio.sleep(10)

    with pytest.raises(ToolError, match="timed out"):
        await _Session().guard(hang(), "run_axe", timeout_s=0.05)


async def test_navigate_recovers_after_the_browser_crashes():
    async with connected() as client:
        await client.call_tool("navigate", {"url": BAD})
        await session._browser.close()  # simulate Chromium dying
        failed = await client.call_tool("run_axe", {})
        assert failed.is_error  # the page is gone; the agent is told to navigate again
        nav = payload(await client.call_tool("navigate", {"url": BAD}))
        assert nav["title"] == "Bad page"
        assert "image-alt" in {v["id"] for v in payload(await client.call_tool("run_axe", {}))["violations"]}
