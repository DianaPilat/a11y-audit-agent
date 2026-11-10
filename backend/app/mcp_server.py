"""a11y-browser: a standalone stdio MCP server wrapping the Playwright + axe-core functions.

Holds one headless Chromium page between calls: `navigate` loads it, and the other
tools act on the current page. No LLM logic lives here.

Run: python -m app.mcp_server
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from playwright.async_api import Browser, Error as PlaywrightError, Page, Playwright, async_playwright

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
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        if self.page is not None:
            await self.page.close()
        self.page = await self._browser.new_page()
        return self.page

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
        response = await page.goto(url, wait_until="load", timeout=browser.NAVIGATION_TIMEOUT_MS)
    except PlaywrightError as e:
        raise ToolError(f"Could not load {url}: {e.message.splitlines()[0]}") from e
    return {
        "url": page.url,
        "title": await page.title(),
        "status": response.status if response else None,
    }


@mcp.tool(annotations=_annotations(open_world=False))
async def list_links(limit: int = browser.MAX_LINKS) -> dict:
    """List unique same-site links on the current page (fragments stripped)."""
    return {"links": await browser.list_links(session.require_page(), limit)}


@mcp.tool(annotations=_annotations(open_world=False))
async def run_axe() -> dict:
    """Run axe-core on the current page. Returns compact violations and incomplete items, plus a passes count."""
    return await browser.run_axe(session.require_page())


@mcp.tool(annotations=_annotations(open_world=False))
async def get_dom_snippet(selector: str) -> str:
    """Return the outer HTML (truncated) of the first element matching a CSS selector, e.g. a violation's target."""
    try:
        html = await browser.get_dom_snippet(session.require_page(), selector)
    except PlaywrightError as e:
        raise ToolError(f"Invalid selector {selector!r}: {e.message.splitlines()[0]}") from e
    if html is None:
        raise ToolError(f"No element matches {selector!r}")
    return html


@mcp.tool(annotations=_annotations(open_world=False))
async def get_page_content() -> dict:
    """Compact lists of the current page's images (alt), links (text), headings (level, text) and form fields (labels),
    each with a selector. Use it for judgment checks axe cannot make: alt quality, link purpose, heading structure, label clarity."""
    return await browser.get_page_content(session.require_page())


if __name__ == "__main__":
    mcp.run()
