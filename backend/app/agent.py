"""Site audit: a crawler run, one auditor run per page, then one ticket writer run that groups all findings by root cause.

The crawl-then-audit loop is plain Python, so every crawled page is audited. Each
step is its own agent run with only the tools it needs: the crawler gets navigation
tools, the auditor gets axe, get_page_content, lookup_wcag and save_finding. All page access goes through the
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
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from app.observability import UsageTracker
from app.findings import SAVE_FINDING_TOOL, SERVER_NAME as FINDINGS_SERVER, FindingStore, build_findings_server
from app.tickets import CREATE_TICKET_TOOL, SERVER_NAME as TICKETS_SERVER, build_tickets_server, export_json, export_markdown
from app.wcag import LOOKUP_WCAG_TOOL, SERVER_NAME as WCAG_SERVER, build_wcag_server

log = logging.getLogger("agent")

BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
CRAWLER_MODEL = "claude-haiku-4-5-20251001"  # always the smallest model
DEFAULT_MAX_PAGES = 20
CRAWLER_MAX_TURNS = 30
AUDITOR_MAX_TURNS = 40  # about 2 calls (lookup_wcag + save_finding) per distinct rule, plus navigate, axe and page content

WRITER_MAX_TURNS = 60  # one create_ticket per root cause, plus navigate and a few snippets

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
    _browser_tool("get_page_content"),
    _browser_tool("get_dom_snippet"),
    LOOKUP_WCAG_TOOL,
    SAVE_FINDING_TOOL,
]

WRITER_TOOLS = [
    _browser_tool("navigate"),
    _browser_tool("get_dom_snippet"),
    CREATE_TICKET_TOOL,
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
3. Call get_page_content once, and make the judgment checks below. axe can only tell
   that alt text, a link name or a label exists, not whether it is any good.
4. Call get_dom_snippet at most 3 times, only with selectors axe or get_page_content
   gave you, and only when you need to see the element to explain the issue.
5. Call lookup_wcag once per distinct rule, describing the issue in one plain sentence
   (e.g. "form input has no label"). It returns the closest WCAG 2.1 criteria; choose the
   one whose requirement the issue really violates. If axe's wcag_criteria for the rule
   agrees with one of the matches, prefer it. Never use a criterion number that neither
   lookup_wcag nor axe gave you.
6. Call save_finding once per issue: the page url, rule id, WCAG criterion number
   (e.g. 1.1.1), severity (axe impact; for judgment issues use "moderate", or "serious"
   when the content is unusable), the affected element's selector, and a plain-language
   explanation of who it affects and how to fix it. If it returns errors, fix the
   fields and call it again.

Judgment checks (rule ids to use; flag only clear problems, never nitpick):
- judgment-alt-text (1.1.1): alt text that is a file name, "image", "photo", "graphic",
  or placeholder text; alt that repeats nearby text without adding meaning; a linked or
  informative image with empty alt. Do not flag empty alt on a plainly decorative image.
- judgment-link-text (2.4.4): link text that does not say where the link goes on its own,
  such as "click here", "read more", "learn more", "here", "link", or a bare URL.
- judgment-heading-structure (1.3.1, or 2.4.6 for unclear text): no h1, more than one h1
  that is not justified, skipped levels (h2 then h4), headings used only for styling,
  or heading text that is empty or does not describe its section.
- judgment-form-label (3.3.2, or 1.3.1 when no programmatic label): a field whose only
  label is a placeholder or title, or whose label text is vague ("Field 1", "Input").

Skip an issue if axe already reported the same element, with one exception: axe's
heading-order is a best-practice rule with no WCAG criterion of its own. Do not save it
under that rule id. Report each skipped heading level as judgment-heading-structure
(1.3.1) instead, one finding per skipped heading, using that heading's selector. Do not
invent issues: every judgment finding must cite an element from get_page_content.

Save axe issues for axe violations only, grouping nodes of the same rule into one
finding with the first node's selector. Finish with one line: the page url and how many
findings you saved. If there are no axe violations and no judgment issues, say so and
save nothing.
"""

SINGLE_AGENT_NOTE = """

You are given several pages, not one. Audit them one after another in the order given,
following the steps above for each page (navigate, run_axe, get_page_content, ...). Use
each page's own url in save_finding. Do not stop until every page has been audited.
Finish with one line per page: the page url and how many findings you saved.
"""

WRITER_PROMPT = """You write remediation tickets for the accessibility findings of one site audit. You are
given every finding with its id, page, rule, WCAG criterion, element and explanation.

First group the findings by root cause: findings that one code change would fix belong
to one ticket. Typical groups: the same rule on many pages (a shared header, footer or
template, e.g. one missing <main> landmark flagged as many "region" nodes), or the same
rule on many elements of one page (e.g. every icon button lacking a name). Findings
that need different fixes stay in separate tickets, even if the rule is the same.

Then call create_ticket once per group, listing every finding id in it. Every finding
must end up in exactly one ticket.
- title: short and imperative, naming the element or component ("Add alt text to the hero image").
- fix_description: what to change and why, in plain language a developer can act on.
  For a shared cause, say where the fix goes once and that it resolves all occurrences.
- code_after: a concrete, paste-ready fix (HTML, ARIA or CSS). Use the real element
  details you have; never invent text content you cannot see, use a clear placeholder
  such as "DESCRIBE THE IMAGE" instead.
- code_before: the current HTML, only if you have seen it.

To see an element, call navigate with its page URL, then get_dom_snippet with the
finding's selector. Do this only when the fix depends on the markup, at most 5 snippets
in total. If create_ticket returns errors, fix the fields and call it again.
Finish with one line: how many tickets you created for how many findings.
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
    tickets: list[dict[str, Any]] = field(default_factory=list)
    tickets_failed: bool = False
    usage: UsageTracker = field(default_factory=UsageTracker)


def parse_page_urls(text: str, start_url: str, max_pages: int, seen: set[str] | None = None) -> list[str]:
    """Pull page URLs out of the crawler's reply: start URL first, same origin, deduped, capped.

    If `seen` is given, only URLs the browser actually returned from list_links are kept, so a
    URL the model invented (e.g. /about on a one-page site) is never audited."""
    origin = urlparse(start_url)[:2]
    urls = [start_url]
    for match in _URL.findall(text):
        url = urldefrag(match.rstrip(".,;:"))[0]
        if urlparse(url)[:2] == origin and url not in urls and (seen is None or url in seen):
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


def single_agent_options(store: FindingStore, audit_id: str, pages: int, model: str = DEFAULT_MODEL) -> ClaudeAgentOptions:
    """One agent that audits every page in a single context (the baseline for the subagent design)."""
    options = auditor_options(store, audit_id, model)
    options.system_prompt = AUDITOR_PROMPT + SINGLE_AGENT_NOTE
    options.max_turns = AUDITOR_MAX_TURNS * pages
    return options


def writer_options(store: FindingStore, audit_id: str, model: str = DEFAULT_MODEL) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=model,
        system_prompt=WRITER_PROMPT,
        mcp_servers={
            SERVER_NAME: SERVER_CONFIG,
            TICKETS_SERVER: build_tickets_server(store, audit_id),
        },
        strict_mcp_config=True,
        tools=[],
        allowed_tools=WRITER_TOOLS,
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=WRITER_MAX_TURNS,
    )


def writer_prompt(findings: list[dict[str, Any]]) -> str:
    lines = [f"Write tickets for these {len(findings)} findings, grouped by root cause:"]
    for f in sorted(findings, key=lambda f: (f["rule_id"], f["id"])):
        lines.append(
            f"- finding_id {f['id']}: {f['url']} | rule {f['rule_id']} | WCAG {f['wcag_criterion']} | "
            f"severity {f['severity']} | element {f['element']}\n  {f['explanation']}"
        )
    return "\n".join(lines)


def _tool_result_text(block: ToolResultBlock) -> str:
    if isinstance(block.content, str):
        return block.content
    return "\n".join(part.get("text", "") for part in block.content or [] if isinstance(part, dict))


async def _run(
    prompt: str, options: ClaudeAgentOptions, run: AuditRun, agent: str, target: str = "", seen_urls: set[str] | None = None
) -> str:
    """Run one agent to completion; add its tool calls, tokens and cost to the run; return its final text."""
    texts: list[str] = []
    tracking = run.usage.start_agent(agent, target)
    options.hooks = tracking.hooks()
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            tracking.on_assistant(message)
            for block in message.content:
                if isinstance(block, TextBlock):
                    texts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    run.tool_calls.append(block.name)
                    log.info("tool call: %s %s", block.name, block.input)
        elif isinstance(message, UserMessage) and seen_urls is not None and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    seen_urls.update(urldefrag(u)[0] for u in _URL.findall(_tool_result_text(block)))
        elif isinstance(message, ResultMessage):
            tracking.on_result(message)
            run.cost_usd = (run.cost_usd or 0) + (message.total_cost_usd or 0)
            if message.result:
                texts = [message.result]
    return "\n\n".join(texts).strip()


async def audit_pages_single_agent(
    pages: list[str], model: str = DEFAULT_MODEL, store: FindingStore | None = None, audit_id: str | None = None
) -> AuditRun:
    """Audit all `pages` in one agent run and one context, with no crawl and no tickets.

    Compare with `audit_site`, which runs a fresh auditor per page."""
    store = store or FindingStore()
    run = AuditRun(url=pages[0], max_pages=len(pages), pages=list(pages), audit_id=audit_id or uuid.uuid4().hex)
    prompt = "Audit these pages:\n" + "\n".join(f"- {p}" for p in pages)
    try:
        run.report = await _run(prompt, single_agent_options(store, run.audit_id, len(pages), model), run, "single_agent")
    except Exception:
        log.exception("single-agent audit failed")
        run.failed_pages = list(pages)
    run.findings = store.list(run.audit_id)
    return run


async def audit_site(
    url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    model: str = DEFAULT_MODEL,
    store: FindingStore | None = None,
    write_tickets: bool = True,
    audit_id: str | None = None,
) -> AuditRun:
    """Crawl, audit each page, write tickets. If the store has an audits row for `audit_id`, progress is recorded on it."""
    store = store or FindingStore()
    run = AuditRun(url=url, max_pages=max_pages, audit_id=audit_id or uuid.uuid4().hex)

    def progress(**fields: Any) -> None:
        if audit_id:
            store.update_audit(audit_id, **fields)

    progress(status="running", phase="crawling")

    seen_urls: set[str] = set()
    if max_pages > 1:
        crawl_prompt = f"Find pages to audit.\nStart URL: {url}\nPage limit: {max_pages}"
        try:
            crawl_reply = await _run(crawl_prompt, crawler_options(), run, "crawler", seen_urls=seen_urls)
        except Exception:
            log.exception("crawl failed; auditing only the start URL")
            crawl_reply = ""
    else:
        crawl_reply = ""
    run.pages = parse_page_urls(crawl_reply, url, max_pages, seen_urls)
    progress(phase="auditing", pages_total=len(run.pages))

    summaries: list[str] = []
    for page in run.pages:
        try:
            summaries.append(
                await _run(f"Audit this page: {page}", auditor_options(store, run.audit_id, model), run, "auditor", page)
            )
        except Exception:
            log.exception("audit of %s failed", page)
            run.failed_pages.append(page)
        progress(pages_done=len(summaries) + len(run.failed_pages), pages_failed=len(run.failed_pages))
    run.findings = store.list(run.audit_id)

    if run.findings and write_tickets:
        progress(phase="writing_tickets")
        try:
            await _run(writer_prompt(run.findings), writer_options(store, run.audit_id, model), run, "ticket_writer")
        except Exception:
            log.exception("ticket writing failed")
            run.tickets_failed = True
    run.tickets = store.list_tickets(run.audit_id)
    progress(status="done", phase="done")

    lines = [
        f"Audited {len(run.pages) - len(run.failed_pages)} of {len(run.pages)} pages, "
        f"saved {len(run.findings)} findings and {len(run.tickets)} tickets."
    ]
    if run.failed_pages:
        lines.append("Failed pages: " + ", ".join(run.failed_pages))
    unticketed = len(run.findings) - sum(len(t["findings"]) for t in run.tickets)
    if run.tickets_failed or unticketed:
        lines.append(f"Ticket writing incomplete: {unticketed} findings have no ticket.")
    run.report = "\n\n".join(lines + summaries)
    return run


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: python -m app.agent <url> [max_pages]")
    result = asyncio.run(audit_site(sys.argv[1], int(sys.argv[2]) if len(sys.argv) == 3 else DEFAULT_MAX_PAGES))
    print(result.report)
    out = BACKEND / "data"
    out.mkdir(exist_ok=True)
    (out / f"tickets-{result.audit_id}.md").write_text(export_markdown(result.tickets), encoding="utf-8")
    (out / f"tickets-{result.audit_id}.json").write_text(export_json(result.tickets), encoding="utf-8")
    print(f"\nsaved {len(result.findings)} findings, {len(result.tickets)} tickets (audit {result.audit_id}); exports in {out}")
    print(f"\n--- cost: ${result.cost_usd} | tool calls: {len(result.tool_calls)}")
