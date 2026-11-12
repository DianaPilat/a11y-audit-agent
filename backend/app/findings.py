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
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.wcag import is_known_criterion

BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BACKEND / "data" / "findings.db"

SERVER_NAME = "findings"
SAVE_FINDING_TOOL = f"mcp__{SERVER_NAME}__save_finding"
JUDGMENT_PREFIX = "judgment-"  # rule ids the auditor invents for checks axe cannot make


class Severity(str, Enum):
    """Matches axe-core impact levels."""

    CRITICAL = "critical"
    SERIOUS = "serious"
    MODERATE = "moderate"
    MINOR = "minor"


class Source(str, Enum):
    """How a finding was produced: a deterministic axe-core rule, or the model's own judgment."""

    AXE = "axe-core"
    AI = "ai-assessed"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"  # only for rows saved before confidence was recorded; the auditor may not choose it


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
    source: Source = Field(
        description="axe-core for issues reported by an axe rule; ai-assessed for judgment-* rules the model decided itself"
    )
    confidence: Confidence = Field(
        description="high = clear-cut, medium = likely but context could change it, low = a human should look closely"
    )

    @field_validator("confidence")
    @classmethod
    def _chosen_confidence(cls, value: Confidence) -> Confidence:
        if value is Confidence.UNKNOWN:
            raise ValueError("confidence must be high, medium or low")
        return value

    @model_validator(mode="after")
    def _source_matches_rule(self) -> "Finding":
        judged = self.rule_id.startswith(JUDGMENT_PREFIX)
        if judged != (self.source is Source.AI):
            raise ValueError(f"source must be {'ai-assessed' if judged else 'axe-core'} for rule {self.rule_id}")
        return self

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
    source TEXT NOT NULL DEFAULT 'axe-core',
    confidence TEXT NOT NULL DEFAULT 'unknown',
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


_AUDITS_SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    max_pages INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    phase TEXT NOT NULL DEFAULT 'queued',
    pages_total INTEGER NOT NULL DEFAULT 0,
    pages_done INTEGER NOT NULL DEFAULT 0,
    pages_failed INTEGER NOT NULL DEFAULT 0,
    pages TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

REVIEW_STATUSES = ("pending", "approved", "rejected")
_AUDIT_FIELDS = {"status", "phase", "pages_total", "pages_done", "pages_failed", "pages", "error"}


class FindingStore:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.execute(_SCHEMA)
        if not any(c["name"] == "review_status" for c in self._db.execute("PRAGMA table_info(findings)")):
            self._db.execute("ALTER TABLE findings ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
        self._migrate_findings()
        self._db.execute(_AUDITS_SCHEMA)
        if not any(c["name"] == "pages" for c in self._db.execute("PRAGMA table_info(audits)")):
            self._db.execute("ALTER TABLE audits ADD COLUMN pages TEXT NOT NULL DEFAULT '[]'")  # JSON list of crawled URLs
        if any(c["name"] == "finding_id" for c in self._db.execute("PRAGMA table_info(tickets)")):
            self._db.execute("DROP TABLE tickets")  # one-ticket-per-finding shape from before root-cause grouping
        self._db.executescript(_TICKETS_SCHEMA)
        self._db.commit()

    def _migrate_findings(self) -> None:
        """Add source and confidence to databases created before they existed. Idempotent."""
        have = {c["name"] for c in self._db.execute("PRAGMA table_info(findings)")}
        if "source" not in have:
            self._db.execute("ALTER TABLE findings ADD COLUMN source TEXT NOT NULL DEFAULT 'axe-core'")
            self._db.execute(f"UPDATE findings SET source='ai-assessed' WHERE rule_id LIKE '{JUDGMENT_PREFIX}%'")
        if "confidence" not in have:  # old rows stay "unknown": confidence was never recorded, so don't invent it
            self._db.execute("ALTER TABLE findings ADD COLUMN confidence TEXT NOT NULL DEFAULT 'unknown'")

    def save(self, audit_id: str, finding: Finding) -> tuple[int, bool]:
        """Store a finding. Returns (id, created); a repeat of the same rule + element is not duplicated."""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO findings"
            " (audit_id, url, rule_id, wcag_criterion, severity, element, explanation, source, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id, finding.url, finding.rule_id, finding.wcag_criterion,
                finding.severity.value, finding.element, finding.explanation,
                finding.source.value, finding.confidence.value,
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

    def set_review_status(self, audit_id: str, finding_id: int, status: str) -> dict[str, Any] | None:
        """Approve, reject, or reset (pending) a finding. Returns the updated finding, or None if not found."""
        if status not in REVIEW_STATUSES:
            raise ValueError(f"status must be one of {REVIEW_STATUSES}")
        self._db.execute(
            "UPDATE findings SET review_status=? WHERE audit_id=? AND id=?", (status, audit_id, finding_id)
        )
        self._db.commit()
        return self.get(audit_id, finding_id)

    def create_audit(self, audit_id: str, url: str, max_pages: int, created_at: str | None = None) -> None:
        self._db.execute(
            "INSERT INTO audits (id, url, max_pages, created_at) VALUES (?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))",
            (audit_id, url, max_pages, created_at),
        )
        self._db.commit()

    def update_audit(self, audit_id: str, **fields: Any) -> None:
        if bad := set(fields) - _AUDIT_FIELDS:
            raise ValueError(f"unknown audit fields: {sorted(bad)}")
        if not fields:
            return
        assignments = ", ".join(f"{k}=?" for k in fields)
        self._db.execute(f"UPDATE audits SET {assignments} WHERE id=?", (*fields.values(), audit_id))
        self._db.commit()

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
        return dict(row) if row else None

    def list_audits(self) -> Sequence[dict[str, Any]]:
        return [dict(r) for r in self._db.execute("SELECT * FROM audits ORDER BY created_at DESC, rowid DESC")]

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
