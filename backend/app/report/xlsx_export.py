"""XLSX export: the same rows as the CSV, formatted to read in Excel (wrapped text, set column widths, frozen header).

CSV carries no formatting, so long cells such as suggested_fix would run off as one line or a tall narrow column."""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.report.csv_export import COLUMNS, NOTE_LABEL, _cell, issue_rows, note_row
from app.report.model import Report

WIDTHS = {  # characters; columns not listed use DEFAULT_WIDTH
    "criterion": 11, "criterion_name": 26, "level": 7, "rule_id": 20, "severity": 11, "source": 16, "confidence": 12,
    "status": 12, "finding_count": 9, "url_count": 8, "first_urls": 42, "explanation": 55, "suggested_fix": 60, "ticket_ids": 12,
}
DEFAULT_WIDTH = 14
HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")


def to_xlsx(report: Report) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Issues"
    ws.append(COLUMNS)
    for row in issue_rows(report):
        ws.append([_cell(v) for v in row])
    ws.append(note_row(report))
    last = ws.max_row

    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2, max_row=last):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for n, name in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(n)].width = WIDTHS.get(name, DEFAULT_WIDTH)
    ws[f"A{last}"].font = Font(bold=True)  # the Limitations row
    assert ws[f"A{last}"].value == NOTE_LABEL

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{last - 1}"  # filter the issues, not the note
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
