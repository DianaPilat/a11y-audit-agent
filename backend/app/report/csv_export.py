"""CSV export: one row per issue (findings sharing a rule and criterion), safe to open in a spreadsheet.

The final row, labeled "Limitations" in the criterion column, carries the limitations statement; skip it when
loading findings."""

import csv
import io

from app.report.model import SOURCE_LABELS, Report

FIRST_URLS = 3
NOTE_LABEL = "Limitations"  # criterion cell of the final row; not a finding
COLUMNS = [
    "criterion", "criterion_name", "level", "rule_id", "severity", "source", "confidence", "status",
    "finding_count", "url_count", "first_urls", "explanation", "suggested_fix", "ticket_ids",
]


def _cell(value: object) -> str:
    """Neutralize spreadsheet formulas: a cell that starts with = + - @ would run as a formula in Excel."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(report: Report) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for i in report.issues:
        fix = i.fix_description + (f"\nAfter: {i.code_after}" if i.code_after else "")
        urls = " | ".join(i.urls[:FIRST_URLS]) + (f" | (+{len(i.urls) - FIRST_URLS} more)" if len(i.urls) > FIRST_URLS else "")
        writer.writerow([_cell(v) for v in [
            i.criterion, i.criterion_name, i.level, i.rule_id, i.severity, SOURCE_LABELS[i.source], i.confidence,
            i.status, len(i.findings), len(i.urls), urls, i.explanation, fix, ", ".join(map(str, i.ticket_ids)),
        ]])
    note = [""] * len(COLUMNS)  # last row: the limitations statement every report carries
    note[0], note[COLUMNS.index("explanation")] = NOTE_LABEL, f"{report.limitations} (Assessment date {report.audit_date}; {report.standard}.)"
    writer.writerow(note)
    return out.getvalue()
