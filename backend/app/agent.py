"""Site audit: a crawler run, then one auditor run per page, using the Claude Agent SDK.

The crawl-then-audit loop is plain Python, so every crawled page is audited. Each
step is its own agent run with only the tools it needs: the crawler gets navigation
tools, the auditor gets axe, lookup_wcag and save_finding. All page access goes through the
a11y-browser MCP server and all findings through the in-process save_finding tool.
"""

import asyncio
import logging
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urlparse

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from app.findings import SAVE_FINDING_TOOL, SERVER_NAME as FINDINGS_SERVER, FindingStore, build_findings_server
from app.wcag import LOOKUP_WCAG_TOOL, SERVER_NAME as WCAG_SERVER, build_wcag_server

log = logging.getLogger("agent")

BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
CRAWLER_MODEL = "claude-haiku-4-5-20251001"  # always the smallest model
DEFAULT_MAX_PAGES = 20
CRAWLER_MAX_TURNS = 30
AUDITOR_MAX_TURNS = 40  # about 2 calls (lookup_wcag + save_finding) per distinct rule, plus navigate and axe

SERVER_NAME = "a11y-browser"
SERVER_CONFIG = {
    "type": "stdio",
    "command": sys.executable,
    "args": ["-m", "app.mcp_server"],
    "env": {"PYTHONPATH": str(BACKEND)},
}


def _browser_tool(name: str) -> str:
    return f"mcp__{SERVER_NAME}__{name}"


CRAWLER_TOOLS = [_browser_tool("navigate"), _browser_tool("list_links")]
AUDITOR_TOOLS = [
    _browser_tool("navigate"),
    _browser_tool("run_axe"),
    _browser_tool("get_dom_snippet"),
    LOOKUP_WCAG_TOOL,
    SAVE_FINDING_TOOL,
]

CRAWLER_PROMPT = """\
You find the pages of one website to audit.

1. Call navigate with the start URL, then list_links.
2. Visit only URLs that list_links returned. Never guess or invent a URL. Pick links that
   look like distinct pages (not anchors, not the current page), navigate to each, and
   call list_links again, until you have the page limit you were given or there are no
   new links. If the site has few links, stop early; that is fine.
3. Use at most 12 navigate calls in total.
4. Reply with only the page URLs, one per line, start URL first, no duplicates, never
   more than the limit. Stay on the same site.
"""

AUDITOR_PROMPT = """\
You audit one web page for accessibility (WCAG 2.1 AA / Section 508).

Steps:
1. Call navigate with the page URL.
2. Call run_axe.
3. Call get_dom_snippet at most 3 times, only with selectors axe reported, and only when
   you need to see the element to explain the issue.
4. Call lookup_wcag once per distinct rule, describing the issue in one plain sentence
   (e.g. "form input has no label"). It returns the closest WCAG 2.1 criteria; choose the
   one whose requirement the issue really violates. If axe's wcag_criteria for the rule
   agrees with one of the matches, prefer it. Never use a criterion number that neither
   lookup_wcag nor axe gave you.
5. Call save_finding once per issue: the page url, rule id, WCAG criterion number
   (e.g. 1.1.1), severity (axe impact), the affected element's selector, and a
   plain-language explanation of who it affects and how to fix it. If it returns
   errors, fix the fields and call it again.

Save only issues axe reported. Do not invent issues. Group nodes of the same rule into
one finding, using the first node's selector. Finish with one line: the page url and how
many findings you saved. If axe reports no violations, say so and save nothing.
"""

_URL = re.compile(r"""(?:https?|file)://[^\s<>"'`)\]]+""")


@dataclass
class AuditRun:
    url: str
    max_pages: int = DEFAULT_MAX_PAGES
    report: str = ""
    pages: list[str] = field(default_factory=list)
    failed_pages: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    audit_id: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)


def parse_page_urls(text: str, start_url: str, max_pages: int) -> list[str]:
    """Pull page URLs out of the crawler's reply: start URL first, same origin, deduped, capped."""
    origin = urlparse(start_url)[:2]
    urls = [start_url]
    for match in _URL.findall(text):
        url = urldefrag(match.rstrip(".,;:"))[0]
        if urlparse(url)[:2] == origin and url not in urls:
            urls.append(url)
    return urls[:max_pages]


def crawler_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=CRAWLER_MODEL,
        system_prompt=CRAWLER_PROMPT,
        mcp_servers={SERVER_NAME: SERVER_CONFIG},
        strict_mcp_config=True,
        tools=[],  # disable built-in tools (Bash, file writes, ...)
        allowed_tools=CRAWLER_TOOLS,
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=CRAWLER_MAX_TURNS,
    )


def auditor_options(store: FindingStore, audit_id: str, model: str = DEFAULT_MODEL) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=model,
        system_prompt=AUDITOR_PROMPT,
        mcp_servers={
            SERVER_NAME: SERVER_CONFIG,
            FINDINGS_SERVER: build_findings_server(store, audit_id),
            WCAG_SERVER: build_wcag_server(),
        },
        strict_mcp_config=True,
        tools=[],
        allowed_tools=AUDITOR_TOOLS,
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=AUDITOR_MAX_TURNS,
    )


async def _run(prompt: str, options: ClaudeAgentOptions, run: AuditRun) -> str:
    """Run one agent to completion; add its tool calls and cost to the run; return its final text."""
    texts: list[str] = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    texts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    run.tool_calls.append(block.name)
                    log.info("tool call: %s %s", block.name, block.input)
        elif isinstance(message, ResultMessage):
            run.cost_usd = (run.cost_usd or 0) + (message.total_cost_usd or 0)
            if message.result:
                texts = [message.result]
    return "\n\n".join(texts).strip()


async def audit_site(
    url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    model: str = DEFAULT_MODEL,
    store: FindingStore | None = None,
) -> AuditRun:
    store = store or FindingStore()
    run = AuditRun(url=url, max_pages=max_pages, audit_id=uuid.uuid4().hex)

    if max_pages > 1:
        crawl_prompt = f"Find pages to audit.\nStart URL: {url}\nPage limit: {max_pages}"
        try:
            crawl_reply = await _run(crawl_prompt, crawler_options(), run)
        except Exception:
            log.exception("crawl failed; auditing only the start URL")
            crawl_reply = ""
    else:
        crawl_reply = ""
    run.pages = parse_page_urls(crawl_reply, url, max_pages)

    summaries: list[str] = []
    for page in run.pages:
        try:
            summaries.append(
                await _run(f"Audit this page: {page}", auditor_options(store, run.audit_id, model), run)
            )
        except Exception:
            log.exception("audit of %s failed", page)
            run.failed_pages.append(page)
    run.findings = store.list(run.audit_id)

    lines = [f"Audited {len(run.pages) - len(run.failed_pages)} of {len(run.pages)} pages, saved {len(run.findings)} findings."]
    if run.failed_pages:
        lines.append("Failed pages: " + ", ".join(run.failed_pages))
    run.report = "\n\n".join(lines + summaries)
    return run


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: python -m app.agent <url> [max_pages]")
    result = asyncio.run(audit_site(sys.argv[1], int(sys.argv[2]) if len(sys.argv) == 3 else DEFAULT_MAX_PAGES))
    print(result.report)
    print(f"\nsaved {len(result.findings)} findings (audit {result.audit_id})")
    print(f"\n--- cost: ${result.cost_usd} | tool calls: {len(result.tool_calls)}")
