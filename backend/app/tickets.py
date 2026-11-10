"""Remediation tickets: the `Ticket` schema, the in-process `create_ticket` tool, and exports.

A ticket is one root cause (one or more findings) plus a suggested code fix. Tickets live in the same SQLite
store as findings (see `FindingStore.save_ticket`); `export_markdown` and
`export_json` render them, with their findings, for people and other tools.
"""

import json
from typing import Any

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.findings import FindingStore, _reply

SERVER_NAME = "tickets"
CREATE_TICKET_TOOL = f"mcp__{SERVER_NAME}__create_ticket"


class Ticket(BaseModel):
    finding_ids: list[int] = Field(
        min_length=1,
        description="ids of every saved finding that this one fix resolves (the findings of one root cause)",
    )
    title: str = Field(min_length=10, max_length=120, description="Short imperative title, e.g. 'Add alt text to the hero image'")
    fix_description: str = Field(min_length=20, description="What to change and why, for the developer who will fix it")
    code_before: str = Field(default="", description="The current HTML, if known; empty if not seen")
    code_after: str = Field(min_length=1, description="The suggested replacement HTML/CSS/ARIA, ready to paste")

    @field_validator("finding_ids")
    @classmethod
    def _valid_ids(cls, ids: list[int]) -> list[int]:
        if any(i < 1 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("finding ids must be positive and listed once each")
        return ids


def make_create_ticket_tool(store: FindingStore, audit_id: str) -> SdkMcpTool:
    @tool(
        "create_ticket",
        "Store one remediation ticket with a suggested code fix, covering every finding that "
        "shares its root cause. Each finding goes in exactly one ticket. On a validation error, fix the listed fields and call again.",
        Ticket.model_json_schema(),
    )
    async def create_ticket(args: dict[str, Any]) -> dict[str, Any]:
        try:
            ticket = Ticket.model_validate(args)
        except ValidationError as e:
            errors = [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
            return _reply({"saved": False, "errors": errors}, is_error=True)
        known = {f["id"] for f in store.list(audit_id)}
        if missing := [i for i in ticket.finding_ids if i not in known]:
            return _reply({"saved": False, "errors": [f"finding_ids: no such finding(s) {missing} in this audit"]}, is_error=True)
        covered = store.ticketed_finding_ids(audit_id)
        if dupes := {i: covered[i] for i in ticket.finding_ids if i in covered}:
            detail = ", ".join(f"finding {i} is in ticket {t}" for i, t in dupes.items())
            return _reply({"saved": False, "errors": [f"finding_ids: already ticketed ({detail})"]}, is_error=True)
        return _reply({"saved": True, "id": store.save_ticket(audit_id, ticket)})

    return create_ticket


def build_tickets_server(store: FindingStore, audit_id: str):
    return create_sdk_mcp_server(SERVER_NAME, tools=[make_create_ticket_tool(store, audit_id)])


def export_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2)


_SEVERITY_ORDER = ["critical", "serious", "moderate", "minor"]


def _worst(findings: list[dict[str, Any]]) -> str:
    return min((f["severity"] for f in findings), key=_SEVERITY_ORDER.index)


def _distinct(findings: list[dict[str, Any]], key: str) -> list[str]:
    return list(dict.fromkeys(f[key] for f in findings))




def export_markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "# Accessibility remediation tickets\n\nNo tickets.\n"
    parts = ["# Accessibility remediation tickets\n"]
    for r in rows:
        fs = r["findings"]
        occurrences = "\n".join(f"  - {f['url']}: `{f['element']}`" for f in fs)
        parts.append(
            f"## {r['title']}\n\n"
            f"- **Severity:** {_worst(fs)}\n"
            f"- **WCAG 2.1:** {', '.join(_distinct(fs, 'wcag_criterion'))}\n"
            f"- **Rules:** {', '.join(_distinct(fs, 'rule_id'))}\n"
            f"- **Occurrences ({len(fs)}):**\n{occurrences}\n\n"
            f"**Issue:** {fs[0]['explanation']}\n\n"
            f"**Fix:** {r['fix_description']}\n"
        )
        if r["code_before"]:
            parts.append(f"Before:\n\n```html\n{r['code_before']}\n```\n")
        parts.append(f"After:\n\n```html\n{r['code_after']}\n```\n")
    return "\n".join(parts)
