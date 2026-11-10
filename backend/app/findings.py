"""Findings store and the in-process `save_finding` tool.

`Finding` is the schema the auditor must satisfy; `FindingStore` persists findings
in SQLite; `build_findings_server` exposes `save_finding` to the Agent SDK as an
in-process MCP server, bound to one audit run.
"""

import json
import sqlite3
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.wcag import is_known_criterion

BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BACKEND / "data" / "findings.db"

SERVER_NAME = "findings"
SAVE_FINDING_TOOL = f"mcp__{SERVER_NAME}__save_finding"


class Severity(str, Enum):
    """Matches axe-core impact levels."""

    CRITICAL = "critical"
    SERIOUS = "serious"
    MODERATE = "moderate"
    MINOR = "minor"


class Finding(BaseModel):
    url: str = Field(min_length=1, description="URL of the audited page the issue was found on")
    rule_id: str = Field(min_length=1, description="axe rule id, e.g. image-alt")
    wcag_criterion: str = Field(
        pattern=r"^\d\.\d\.\d{1,2}$",
        description="WCAG 2.1 success criterion number, e.g. 1.1.1",
    )
    severity: Severity
    element: str = Field(min_length=1, description="CSS selector of the affected element")
    explanation: str = Field(
        min_length=20, description="Plain language: who is affected, why it matters, how to fix it"
    )

    @field_validator("wcag_criterion")
    @classmethod
    def _known_criterion(cls, value: str) -> str:
        if not is_known_criterion(value):
            raise ValueError(f"{value} is not a WCAG 2.1 level A or AA success criterion; use lookup_wcag")
        return value


_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT NOT NULL,
    url TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    wcag_criterion TEXT NOT NULL,
    severity TEXT NOT NULL,
    element TEXT NOT NULL,
    explanation TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (audit_id, url, rule_id, element)
)
"""

_TICKETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id TEXT NOT NULL,
    title TEXT NOT NULL,
    fix_description TEXT NOT NULL,
    code_before TEXT NOT NULL DEFAULT '',
    code_after TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ticket_findings (
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    finding_id INTEGER NOT NULL UNIQUE REFERENCES findings(id)
);
"""


class FindingStore:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.execute(_SCHEMA)
        if any(c["name"] == "finding_id" for c in self._db.execute("PRAGMA table_info(tickets)")):
            self._db.execute("DROP TABLE tickets")  # one-ticket-per-finding shape from before root-cause grouping
        self._db.executescript(_TICKETS_SCHEMA)
        self._db.commit()

    def save(self, audit_id: str, finding: Finding) -> tuple[int, bool]:
        """Store a finding. Returns (id, created); a repeat of the same rule + element is not duplicated."""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO findings"
            " (audit_id, url, rule_id, wcag_criterion, severity, element, explanation)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id, finding.url, finding.rule_id, finding.wcag_criterion,
                finding.severity.value, finding.element, finding.explanation,
            ),
        )
        self._db.commit()
        if cur.rowcount:
            return cur.lastrowid, True
        row = self._db.execute(
            "SELECT id FROM findings WHERE audit_id=? AND url=? AND rule_id=? AND element=?",
            (audit_id, finding.url, finding.rule_id, finding.element),
        ).fetchone()
        return row["id"], False

    def list(self, audit_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM findings WHERE audit_id=? ORDER BY id", (audit_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, audit_id: str, finding_id: int) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT * FROM findings WHERE audit_id=? AND id=?", (audit_id, finding_id)
        ).fetchone()
        return dict(row) if row else None

    def ticketed_finding_ids(self, audit_id: str) -> dict[int, int]:
        """Map finding id -> id of the ticket that already covers it."""
        rows = self._db.execute(
            "SELECT tf.finding_id, tf.ticket_id FROM ticket_findings tf"
            " JOIN tickets t ON t.id = tf.ticket_id WHERE t.audit_id=?",
            (audit_id,),
        ).fetchall()
        return {r["finding_id"]: r["ticket_id"] for r in rows}

    def save_ticket(self, audit_id: str, ticket: Any) -> int:
        """Store a ticket (a tickets.Ticket) covering ticket.finding_ids. Callers check the ids first."""
        cur = self._db.execute(
            "INSERT INTO tickets (audit_id, title, fix_description, code_before, code_after)"
            " VALUES (?, ?, ?, ?, ?)",
            (audit_id, ticket.title, ticket.fix_description, ticket.code_before, ticket.code_after),
        )
        self._db.executemany(
            "INSERT INTO ticket_findings (ticket_id, finding_id) VALUES (?, ?)",
            [(cur.lastrowid, fid) for fid in ticket.finding_ids],
        )
        self._db.commit()
        return cur.lastrowid

    def list_tickets(self, audit_id: str) -> Sequence[dict[str, Any]]:
        """Tickets in creation order, each with its findings under "findings"."""
        tickets = [
            dict(r) for r in self._db.execute(
                "SELECT id, title, fix_description, code_before, code_after FROM tickets"
                " WHERE audit_id=? ORDER BY id", (audit_id,),
            )
        ]
        for t in tickets:
            t["findings"] = [
                dict(r) for r in self._db.execute(
                    "SELECT f.* FROM findings f JOIN ticket_findings tf ON tf.finding_id = f.id"
                    " WHERE tf.ticket_id=? ORDER BY f.id", (t["id"],),
                )
            ]
        return tickets

    def close(self) -> None:
        self._db.close()


def _reply(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    if is_error:
        result["is_error"] = True
    return result


def make_save_finding_tool(store: FindingStore, audit_id: str) -> SdkMcpTool:
    @tool(
        "save_finding",
        "Validate and store one accessibility finding. Call once per distinct issue. "
        "On a validation error, fix the listed fields and call again.",
        Finding.model_json_schema(),
    )
    async def save_finding(args: dict[str, Any]) -> dict[str, Any]:
        try:
            finding = Finding.model_validate(args)
        except ValidationError as e:
            errors = [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
            return _reply({"saved": False, "errors": errors}, is_error=True)
        finding_id, created = store.save(audit_id, finding)
        return _reply({"saved": True, "id": finding_id, "duplicate": not created})

    return save_finding


def build_findings_server(store: FindingStore, audit_id: str):
    return create_sdk_mcp_server(SERVER_NAME, tools=[make_save_finding_tool(store, audit_id)])
