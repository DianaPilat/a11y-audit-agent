"""HTTP API for the review UI: start an audit, poll its progress, list findings, approve or reject them.

Handlers are `async` on purpose: the audit task and every handler then share the event loop thread,
which is what the single SQLite connection in `FindingStore` requires.
"""

import asyncio
import logging
from collections.abc import Sequence
import uuid
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent import DEFAULT_MAX_PAGES, audit_site
from app.findings import FindingStore

log = logging.getLogger("api")

app = FastAPI(title="Accessibility Audit Agent")
_tasks: set[asyncio.Task] = set()  # hold references so running audits aren't garbage collected


def get_store(request: Request) -> FindingStore:
    if not hasattr(request.app.state, "store"):
        request.app.state.store = FindingStore()
    return request.app.state.store


class AuditRequest(BaseModel):
    url: str = Field(min_length=1)
    max_pages: int = Field(default=DEFAULT_MAX_PAGES, ge=1, le=DEFAULT_MAX_PAGES)


class ReviewRequest(BaseModel):
    status: Literal["pending", "approved", "rejected"]


async def _run_audit(store: FindingStore, audit_id: str, url: str, max_pages: int) -> None:
    try:
        await audit_site(url, max_pages=max_pages, store=store, audit_id=audit_id)
    except Exception as e:
        log.exception("audit %s failed", audit_id)
        store.update_audit(audit_id, status="failed", phase="failed", error=str(e) or type(e).__name__)


def _audit_or_404(store: FindingStore, audit_id: str) -> dict:
    if (audit := store.get_audit(audit_id)) is None:
        raise HTTPException(404, "audit not found")
    return audit


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/audits", status_code=202)
async def start_audit(body: AuditRequest, request: Request) -> dict:
    parsed = urlparse(body.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(422, "url must be an http(s) URL")
    store = get_store(request)
    audit_id = uuid.uuid4().hex
    store.create_audit(audit_id, body.url, body.max_pages)
    task = asyncio.create_task(_run_audit(store, audit_id, body.url, body.max_pages))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return store.get_audit(audit_id)


@app.get("/audits")
async def list_audits(request: Request) -> Sequence[dict]:
    return get_store(request).list_audits()


@app.get("/audits/{audit_id}")
async def get_audit(audit_id: str, request: Request) -> dict:
    store = get_store(request)
    audit = _audit_or_404(store, audit_id)
    findings = store.list(audit_id)
    counts = {s: sum(f["review_status"] == s for f in findings) for s in ("pending", "approved", "rejected")}
    return {**audit, "findings_count": len(findings), "review_counts": counts}


@app.get("/audits/{audit_id}/findings")
async def list_findings(audit_id: str, request: Request) -> list[dict]:
    store = get_store(request)
    _audit_or_404(store, audit_id)
    return store.list(audit_id)


@app.patch("/audits/{audit_id}/findings/{finding_id}")
async def review_finding(audit_id: str, finding_id: int, body: ReviewRequest, request: Request) -> dict:
    store = get_store(request)
    if (finding := store.set_review_status(audit_id, finding_id, body.status)) is None:
        raise HTTPException(404, "finding not found")
    return finding
