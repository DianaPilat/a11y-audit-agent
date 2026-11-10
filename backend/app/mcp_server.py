"""a11y-browser: a standalone stdio MCP server wrapping the Playwright + axe-core functions.

Holds one headless Chromium page between calls: `navigate` loads it, and the other
tools act on the current page. No LLM logic lives here.

Run: python -m app.mcp_server
"""

import asyncio
from collections.abc import Awaitable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from playwright.async_api import Browser, Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeoutError, Playwright, async_playwright

from app import browser

mcp = MCPServer(
    "a11y-browser",
    instructions="Call navigate first; list_links, run_axe, get_page_content and get_dom_snippet act on the current page.",
)


class _Session:
    """Lazily launched browser and the single current page."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None

    async def open_page(self) -> Page:
        if self._browser is not None and not self._browser.is_connected():
            await self.close()  # Chromium died since the last call: start a fresh one
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        if self.page is not None:
            try:
                await self.page.close()
            except PlaywrightError:
                pass  # the old page is already gone
        self.page = await self._browser.new_page()
        self.page.set_default_timeout(browser.PAGE_TOOL_TIMEOUT_S * 1000)
        return self.page

    def browser_alive(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def guard(self, work: Awaitable, what: str, timeout_s: float = browser.PAGE_TOOL_TIMEOUT_S):
        """Await work with a time budget. A hang or a dead browser becomes a ToolError the agent can act on."""
        try:
            return await asyncio.wait_for(work, timeout_s)
        except (asyncio.TimeoutError, PlaywrightTimeoutError):
            raise ToolError(f"{what} timed out after {timeout_s:g}s. Skip this page or call navigate again.") from None
        except PlaywrightError as e:
            if _is_crash(e) or (self._browser is not None and not self._browser.is_connected()):
                await self.close()
                raise ToolError(f"{what} failed because the browser closed. Call navigate to start again.") from e
            raise

    def require_page(self) -> Page:
        if self.page is None:
            raise ToolError("No page loaded. Call navigate first.")
        return self.page

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._playwright = self._browser = self.page = None


session = _Session()

_CRASH_MARKERS = ("Target closed", "has been closed", "Browser closed", "Connection closed")


def _is_crash(error: PlaywrightError) -> bool:
    return any(m in error.message for m in _CRASH_MARKERS)


def _annotations(*, open_world: bool) -> ToolAnnotations:
    """All four tools only read: they never modify anything and are safe to repeat."""
    return ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=open_world,
    )


@mcp.tool(annotations=_annotations(open_world=True))
async def navigate(url: str) -> dict:
    """Load a page in headless Chromium and make it the current page. Returns its final URL and title."""
    page = await session.open_page()
    try:
        response = await browser.goto_with_retry(page, url)
    except PlaywrightError as e:
        if _is_crash(e) or not session.browser_alive():
            await session.close()
            raise ToolError(f"Could not load {url}: the browser crashed. Try navigate again.") from e
        raise ToolError(f"Could not load {url}: {e.message.splitlines()[0]}") from e
    return {
        "url": page.url,
        "title": await page.title(),
        "status": response.status if response else None,
    }


@mcp.tool(annotations=_annotations(open_world=False))
async def list_links(limit: int = browser.MAX_LINKS) -> dict:
    """List unique same-site links on the current page (fragments stripped)."""
    return {"links": await session.guard(browser.list_links(session.require_page(), limit), "list_links")}


@mcp.tool(annotations=_annotations(open_world=False))
async def run_axe() -> dict:
    """Run axe-core on the current page. Returns compact violations and incomplete items, plus a passes count."""
    return await session.guard(browser.run_axe(session.require_page()), "run_axe", browser.AXE_TIMEOUT_S)


@mcp.tool(annotations=_annotations(open_world=False))
async def get_dom_snippet(selector: str) -> str:
    """Return the outer HTML (truncated) of the first element matching a CSS selector, e.g. a violation's target."""
    try:
        html = await session.guard(browser.get_dom_snippet(session.require_page(), selector), "get_dom_snippet")
    except PlaywrightError as e:
        raise ToolError(f"Invalid selector {selector!r}: {e.message.splitlines()[0]}") from e
    if html is None:
        raise ToolError(f"No element matches {selector!r}")
    return html


@mcp.tool(annotations=_annotations(open_world=False))
async def get_page_content() -> dict:
    """Compact lists of the current page's images (alt), links (text), headings (level, text) and form fields (labels),
    each with a selector. Use it for judgment checks axe cannot make: alt quality, link purpose, heading structure, label clarity."""
    return await session.guard(browser.get_page_content(session.require_page()), "get_page_content")


if __name__ == "__main__":
    mcp.run()
