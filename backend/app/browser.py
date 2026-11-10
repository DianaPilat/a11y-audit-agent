"""Playwright + axe-core as plain async functions.

No LLM or MCP logic lives here; week 2 wraps these as the a11y-browser MCP server.
"""

import asyncio
import json
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Page, async_playwright

AXE_PATH = Path(__file__).parent / "vendor" / "axe.min.js"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "results"
NAVIGATION_TIMEOUT_MS = 30_000


@asynccontextmanager
async def load_page(url: str, timeout_ms: int = NAVIGATION_TIMEOUT_MS) -> AsyncIterator[Page]:
    """Launch headless Chromium, navigate to url, and yield the loaded page."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="load", timeout=timeout_ms)
            yield page
        finally:
            await browser.close()


async def run_axe(page: Page) -> dict:
    """Run axe-core on the page and return compact results, not the raw axe output.

    Keeps violations (failed rules) and incomplete (axe couldn't decide; needs
    judgment). Drops passes and inapplicable, keeping only a count of passes.
    """
    await page.add_script_tag(path=str(AXE_PATH))
    raw = await page.evaluate("axe.run()")
    return {
        "axe_version": raw["testEngine"]["version"],
        "violations": _compact(raw["violations"]),
        "incomplete": _compact(raw["incomplete"]),
        "passes_count": len(raw["passes"]),
    }


WCAG_CRITERION = re.compile(r"^wcag\d{3,}$")


def _compact(rules: list[dict]) -> list[dict]:
    return [
        {
            "id": r["id"],
            "impact": r["impact"],
            "help": r["help"],
            "help_url": r["helpUrl"],
            "tags": r["tags"],
            "category": "wcag" if any(t.startswith("wcag") for t in r["tags"]) else "best-practice",
            "wcag_criteria": [t for t in r["tags"] if WCAG_CRITERION.match(t)],
            "nodes": [
                {"target": n["target"], "html": n["html"], "failureSummary": n.get("failureSummary")}
                for n in r["nodes"]
            ],
        }
        for r in rules
    ]


MAX_LINKS = 100
MAX_SNIPPET_CHARS = 1_000

_LINKS_JS = """
() => [...document.querySelectorAll('a[href]')]
    .map(a => new URL(a.href))
    .filter(u => ['http:', 'https:', 'file:'].includes(u.protocol)
        && u.protocol === location.protocol && u.host === location.host)
    .map(u => { u.hash = ''; return u.href; })
"""


async def list_links(page: Page, limit: int = MAX_LINKS) -> list[str]:
    """Return unique same-origin links on the page (fragments stripped), in document order."""
    hrefs = await page.evaluate(_LINKS_JS)
    return list(dict.fromkeys(hrefs))[:limit]


async def get_dom_snippet(page: Page, selector: str, max_chars: int = MAX_SNIPPET_CHARS) -> str | None:
    """Return the outer HTML of the first element matching selector, truncated; None if no match."""
    locator = page.locator(selector)
    if await locator.count() == 0:
        return None
    html = await locator.first.evaluate("el => el.outerHTML")
    if len(html) > max_chars:
        return html[:max_chars] + f"... [truncated, {len(html)} chars total]"
    return html


MAX_ITEMS = 40
MAX_TEXT_CHARS = 120

_CONTENT_JS = r"""
([maxItems, maxText]) => {
    const clip = s => (s || '').replace(/\s+/g, ' ').trim().slice(0, maxText);
    const sel = el => {
        if (el.id) return '#' + CSS.escape(el.id);
        const parts = [];
        for (; el && el.nodeType === 1 && el !== document.body; el = el.parentElement) {
            const same = [...el.parentElement.children].filter(c => c.tagName === el.tagName);
            parts.unshift(el.tagName.toLowerCase() + (same.length > 1 ? `:nth-of-type(${same.indexOf(el) + 1})` : ''));
        }
        return 'body > ' + parts.join(' > ');
    };
    const cap = list => ({ total: list.length, items: list.slice(0, maxItems) });
    const named = (el, ids) => ids.split(/\s+/).map(i => document.getElementById(i)).filter(Boolean)
        .map(e => clip(e.textContent)).join(' ');
    const label = el => {
        const labels = [...(el.labels || [])].map(l => clip(l.textContent)).filter(Boolean);
        return {
            label: labels.join(' | ') || null,
            aria_label: el.getAttribute('aria-label'),
            aria_labelledby: el.hasAttribute('aria-labelledby') ? named(el, el.getAttribute('aria-labelledby')) : null,
            title: el.getAttribute('title'),
            placeholder: el.getAttribute('placeholder'),
        };
    };
    return {
        images: cap([...document.querySelectorAll('img, [role=img]')].map(e => ({
            selector: sel(e),
            alt: e.hasAttribute('alt') ? e.getAttribute('alt') : null,
            aria_label: e.getAttribute('aria-label'),
            src: clip((e.getAttribute('src') || '').split('?')[0].split('/').pop()),
            in_link: !!e.closest('a'),
        }))),
        links: cap([...document.querySelectorAll('a[href]')].map(e => ({
            selector: sel(e),
            text: clip(e.textContent),
            aria_label: e.getAttribute('aria-label'),
            img_alt: clip([...e.querySelectorAll('img[alt]')].map(i => i.alt).join(' ')),
            href: clip(e.getAttribute('href')),
        }))),
        headings: cap([...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading]')].map(e => ({
            selector: sel(e),
            level: e.getAttribute('aria-level') ? +e.getAttribute('aria-level') : (/^H\d$/.test(e.tagName) ? +e.tagName[1] : null),
            text: clip(e.textContent),
        }))),
        form_fields: cap([...document.querySelectorAll(
            'input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), select, textarea'
        )].map(e => ({
            selector: sel(e),
            type: e.type || e.tagName.toLowerCase(),
            name: e.getAttribute('name'),
            ...label(e),
        }))),
    };
}
"""


async def get_page_content(page: Page, max_items: int = MAX_ITEMS) -> dict:
    """Compact view of what the judgment checks need: images, links, headings and form fields.

    Each section is {total, items}; items are capped at max_items. Text is clipped, never full HTML.
    """
    return await page.evaluate(_CONTENT_JS, [max_items, MAX_TEXT_CHARS])


def save_results(url: str, results: dict, out_dir: Path = DEFAULT_OUT_DIR) -> Path:
    """Write results as JSON, named after the URL, and return the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-")[:100]
    path = out_dir / f"{slug}.json"
    record = {
        "url": url,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        **results,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


async def audit_page(url: str, out_dir: Path = DEFAULT_OUT_DIR) -> Path:
    """Load a page, run axe on it, save the results, and return the file path."""
    async with load_page(url) as page:
        results = await run_axe(page)
    return save_results(url, results, out_dir)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.browser <url>")
    print(asyncio.run(audit_page(sys.argv[1])))
