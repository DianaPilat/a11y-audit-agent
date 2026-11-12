"""One entry point for every format, used by the CLI and the API."""

from dataclasses import dataclass

from app.findings import FindingStore
from app.report.csv_export import to_csv
from app.report.json_export import to_json
from app.report.model import Report, build_report
from app.report.pdf import render_pdf

FORMATS = ("pdf", "json", "csv")


@dataclass
class Rendered:
    content: bytes
    media_type: str
    extension: str


def render(report: Report, fmt: str) -> Rendered:
    if fmt == "pdf":
        return Rendered(render_pdf(report), "application/pdf", "pdf")
    if fmt == "json":
        return Rendered(to_json(report).encode("utf-8"), "application/json", "json")
    if fmt == "csv":  # BOM so Excel reads it as UTF-8
        return Rendered(to_csv(report).encode("utf-8-sig"), "text/csv; charset=utf-8", "csv")
    raise ValueError(f"format must be one of {FORMATS}")


def generate(store: FindingStore, audit_id: str, fmt: str, include_unreviewed: bool | None = None) -> Rendered:
    return render(build_report(store, audit_id, include_unreviewed), fmt)
