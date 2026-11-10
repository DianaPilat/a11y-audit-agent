"""Single-agent audit of one page, using the Claude Agent SDK.

Connects to the a11y-browser MCP server over stdio and returns a plain-language
report. Holds no browser logic; all page access goes through the MCP tools.
"""

import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from app.findings import SAVE_FINDING_TOOL, SERVER_NAME as FINDINGS_SERVER, FindingStore, build_findings_server

log = logging.getLogger("agent")

BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TURNS = 15

SERVER_NAME = "a11y-browser"
SERVER_CONFIG = {
    "type": "stdio",
    "command": sys.executable,
    "args": ["-m", "app.mcp_server"],
    "env": {"PYTHONPATH": str(BACKEND)},
}
ALLOWED_TOOLS = [
    f"mcp__{SERVER_NAME}__{name}"
    for name in ("navigate", "list_links", "run_axe", "get_dom_snippet")
] + [SAVE_FINDING_TOOL]

SYSTEM_PROMPT = """\
You audit one web page for accessibility (WCAG 2.1 AA / Section 508).

Steps:
1. Call navigate with the URL.
2. Call run_axe.
3. Call get_dom_snippet only for flagged elements you need to see to explain the issue.
4. Call save_finding once per issue: rule id, WCAG criterion number (e.g. 1.1.1),
   severity (axe impact), the affected element's selector, and a plain-language
   explanation of who it affects and how to fix it. If it returns errors, fix the
   fields and call it again.

Save only issues axe reported. Do not invent issues. Group nodes of the same rule into
one finding, using the first node's selector. Finish with a short summary of what you saved.
If axe reports no violations, say so plainly and save nothing.
"""


@dataclass
class AuditRun:
    url: str
    report: str = ""
    tool_calls: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    audit_id: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)


def build_options(
    store: FindingStore, audit_id: str, url: str, model: str = DEFAULT_MODEL
) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={
            SERVER_NAME: SERVER_CONFIG,
            FINDINGS_SERVER: build_findings_server(store, audit_id, url),
        },
        strict_mcp_config=True,
        tools=[],  # disable built-in tools (Bash, file writes, ...)
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=MAX_TURNS,
    )


async def audit_page(
    url: str, model: str = DEFAULT_MODEL, store: FindingStore | None = None
) -> AuditRun:
    store = store or FindingStore()
    run = AuditRun(url=url, audit_id=uuid.uuid4().hex)
    texts: list[str] = []
    options = build_options(store, run.audit_id, url, model)
    async for message in query(prompt=f"Audit this page: {url}", options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    texts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    run.tool_calls.append(block.name)
                    log.info("tool call: %s %s", block.name, block.input)
        elif isinstance(message, ResultMessage):
            run.cost_usd = message.total_cost_usd
            run.usage = message.usage
            if message.result:
                texts = [message.result]
    run.report = "\n\n".join(texts).strip()
    return run


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.agent <url>")
    result = asyncio.run(audit_page(sys.argv[1]))
    print(result.report)
    print(f"\n--- tools: {result.tool_calls} | cost: ${result.cost_usd} | usage: {result.usage}")
