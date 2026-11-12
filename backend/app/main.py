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

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.agent import DEFAULT_MAX_PAGES, audit_site
from app.findings import FindingStore
from app.report.config import include_unreviewed_default
from app.report.export import FORMATS, render
from app.report.model import build_report

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


def _include_unreviewed(requested: bool | None) -> bool:
    """Unreviewed findings are a demo switch: requesting them needs REPORT_INCLUDE_UNREVIEWED on the server."""
    if requested and not include_unreviewed_default():
        raise HTTPException(403, "including unreviewed findings is disabled on this server")
    return include_unreviewed_default() if requested is None else requested


@app.get("/audits/{audit_id}/report/summary")
async def report_summary(audit_id: str, request: Request, include_unreviewed: bool | None = None) -> dict:
    """How many findings a report would include or leave out; feeds the export panel."""
    store = get_store(request)
    _audit_or_404(store, audit_id)
    include = _include_unreviewed(include_unreviewed)
    return {**build_report(store, audit_id, include).counts, "include_unreviewed": include,
            "unreviewed_allowed": include_unreviewed_default(), "formats": list(FORMATS)}


@app.get("/audits/{audit_id}/report")
async def get_report(
    audit_id: str, request: Request, format: Literal["pdf", "json", "csv", "xlsx"] = "pdf", include_unreviewed: bool | None = None
) -> Response:
    store = get_store(request)
    _audit_or_404(store, audit_id)
    report = build_report(store, audit_id, _include_unreviewed(include_unreviewed))  # reads the store on the loop thread
    try:
        rendered = await asyncio.to_thread(render, report, format)  # the PDF render is slow; the report is plain data
    except OSError as e:  # WeasyPrint could not load its native libraries
        log.exception("report render failed")
        raise HTTPException(503, "report rendering is unavailable on this server") from e
    name = f"accessibility-assessment-{audit_id[:8]}.{rendered.extension}"
    return Response(rendered.content, media_type=rendered.media_type,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
