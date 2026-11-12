import csv
import io
import json
import re

import pytest

from app.findings import Finding, FindingStore
from app.report import config
from app.report.csv_export import COLUMNS, FIRST_URLS, NOTE_LABEL
from app.report.export import render
from app.report.fixture import SAMPLE_AUDIT_ID, load_sample
from app.report.model import build_report
from app.report.pdf import render_html
from app.tickets import Ticket

SCHEMA_FIELDS = {
    "id", "audit_id", "url", "rule_id", "wcag_criterion", "severity", "element", "explanation",
    "source", "confidence", "created_at", "review_status",
}


@pytest.fixture
def store():
    s = FindingStore(":memory:")
    load_sample(s)
    return s


def _by_status(store, status):
    return {r["id"] for r in store.list(SAMPLE_AUDIT_ID) if r["review_status"] == status}


def _json(store, **kw):
    return json.loads(render(build_report(store, SAMPLE_AUDIT_ID, **kw), "json").content)


def _csv(store, **kw):
    text = render(build_report(store, SAMPLE_AUDIT_ID, **kw), "csv").content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows[-1]["criterion"] == NOTE_LABEL and "not a legal determination" in rows[-1]["explanation"]
    return rows[:-1]


# --- JSON ---

def test_json_has_every_schema_field_for_every_approved_finding(store):
    doc = _json(store)
    approved = _by_status(store, "approved")
    assert {f["id"] for f in doc["findings"]} == approved
    for f in doc["findings"]:
        assert SCHEMA_FIELDS <= set(f)
        assert f["source"] in ("axe-core", "ai-assessed") and f["confidence"] in ("high", "medium", "low")
    assert "not a legal determination" in doc["report"]["limitations"]
    assert doc["report"]["counts"]["excluded_rejected"] == 2


def test_json_findings_link_their_ticket(store):
    doc = _json(store)
    assert any(f["ticket_id"] for f in doc["findings"]) and any(f["ticket_id"] is None for f in doc["findings"])


# --- CSV ---

def test_csv_one_row_per_issue_with_url_count_and_first_urls(store):
    rows = _csv(store)
    report = build_report(store, SAMPLE_AUDIT_ID)
    assert len(rows) == len(report.issues) == 12
    assert list(rows[0]) == COLUMNS
    long_row = next(r for r in rows if r["rule_id"] == "meta-viewport")
    assert long_row["url_count"] == "12"
    shown = long_row["first_urls"].split(" | ")
    assert shown[:FIRST_URLS] == report.issues[[i.rule_id for i in report.issues].index("meta-viewport")].urls[:FIRST_URLS]
    assert shown[-1] == "(+9 more)"
    assert {r["source"] for r in rows} == {"axe-core (automated rule)", "AI-assessed"}


def test_csv_neutralizes_spreadsheet_formulas(store):
    store.save(SAMPLE_AUDIT_ID, Finding(
        url="https://portal.riverton.example/x", rule_id="image-alt", wcag_criterion="1.1.1", severity="minor",
        element="img", explanation='=HYPERLINK("http://evil.example","click") is not a real explanation',
        source="axe-core", confidence="high"))
    fid = store.list(SAMPLE_AUDIT_ID)[-1]["id"]
    store.set_review_status(SAMPLE_AUDIT_ID, fid, "approved")
    for row in _csv(store):
        assert not row["explanation"].startswith("=")


# --- inclusion rules ---

def test_default_excludes_unapproved_and_rejected(store, monkeypatch):
    monkeypatch.delenv(config.INCLUDE_UNREVIEWED_ENV, raising=False)
    included = {f["id"] for f in _json(store)["findings"]}
    assert included == _by_status(store, "approved")
    assert not included & (_by_status(store, "pending") | _by_status(store, "rejected"))


def test_unreviewed_flag_adds_only_unreviewed_and_labels_them(store):
    default = {f["id"] for f in _json(store)["findings"]}
    doc = _json(store, include_unreviewed=True)
    flagged = {f["id"] for f in doc["findings"]}
    assert flagged - default == _by_status(store, "pending")
    assert not flagged & _by_status(store, "rejected")
    assert all(f["unreviewed"] == (f["review_status"] == "pending") for f in doc["findings"])
    assert doc["report"]["unreviewed_label"] == "Unreviewed"
    assert any(r["status"] == "Unreviewed" for r in _csv(store, include_unreviewed=True))
    assert not any(r["status"] == "Unreviewed" for r in _csv(store))
    html = render_html(build_report(store, SAMPLE_AUDIT_ID, include_unreviewed=True))
    assert "Unreviewed" in html and "Demonstration copy" in html
    assert "Demonstration copy" not in render_html(build_report(store, SAMPLE_AUDIT_ID))


def test_rejected_never_appears_in_any_format(store):
    rejected = {r["id"]: r for r in store.list(SAMPLE_AUDIT_ID) if r["review_status"] == "rejected"}
    assert rejected
    for flag in (False, True):
        ids = {f["id"] for f in _json(store, include_unreviewed=flag)["findings"]}
        assert not ids & set(rejected)
    # the rejected rows are the only ones with these rule/page combinations
    assert "aria-required-attr" not in render_html(build_report(store, SAMPLE_AUDIT_ID, include_unreviewed=True))


def test_env_flag_defaults_off_and_turns_on(store, monkeypatch):
    monkeypatch.delenv(config.INCLUDE_UNREVIEWED_ENV, raising=False)
    assert build_report(store, SAMPLE_AUDIT_ID).include_unreviewed is False
    monkeypatch.setenv(config.INCLUDE_UNREVIEWED_ENV, "true")
    assert build_report(store, SAMPLE_AUDIT_ID).include_unreviewed is True
    assert build_report(store, SAMPLE_AUDIT_ID, include_unreviewed=False).include_unreviewed is False


# --- secrets and wording ---

SECRETS = [
    "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz012345",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
    "hunter2hunter2",
    "s3cr3tPassw0rd",
]


def _seed_secrets(store):
    explanation = (
        "The page embeds a key sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz012345 and AKIAIOSFODNN7EXAMPLE in a "
        "script, which also affects screen reader users somehow."
    )
    fid, _ = store.save(SAMPLE_AUDIT_ID, Finding(
        url="https://user:s3cr3tPassw0rd@portal.riverton.example/login?session=hunter2hunter2&page=2#frag",
        rule_id="image-alt", wcag_criterion="1.1.1", severity="minor",
        element="img[data-api-key='ghp_abcdefghijklmnopqrstuvwxyz0123456789']", explanation=explanation,
        source="axe-core", confidence="high"))
    store.set_review_status(SAMPLE_AUDIT_ID, fid, "approved")
    store.save_ticket(SAMPLE_AUDIT_ID, Ticket(
        finding_ids=[fid], title="Remove the embedded credentials",
        fix_description="Move the credential out of the page. password=s3cr3tPassw0rd must not ship.",
        code_before='<script>var token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r";</script>',
        code_after="<script>/* removed */</script>"))
    return fid


def test_no_secrets_in_any_export(store, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-ENVVALUE0000000000000000000")
    _seed_secrets(store)
    report = build_report(store, SAMPLE_AUDIT_ID, include_unreviewed=True)
    outputs = [
        render(report, "json").content.decode(),
        render(report, "csv").content.decode("utf-8-sig"),
        render_html(report),
    ]
    pypdf = pytest.importorskip("pypdf")
    outputs.append(" ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(render(report, "pdf").content)).pages))
    outputs.append(str(pypdf.PdfReader(io.BytesIO(render(report, "pdf").content)).metadata))
    for text in outputs:
        for secret in [*SECRETS, "ENVVALUE0000000000000000000"]:
            assert secret not in text, secret
        assert "ANTHROPIC_API_KEY" not in text
    assert "[REDACTED]" in outputs[0]
    assert "#frag" not in outputs[0]


def test_wording_never_says_certified_or_compliant(store):
    report = build_report(store, SAMPLE_AUDIT_ID, include_unreviewed=True)
    texts = [render(report, "json").content.decode(), render(report, "csv").content.decode("utf-8-sig"), render_html(report)]
    for text in texts:
        assert not re.search(r"certif|(?<!non-)\bcompliant\b|non-compliant", text, re.I)
        assert "assessment" in text.lower()


# --- XLSX ---

def test_xlsx_matches_csv_rows_and_wraps_long_cells(store):
    import openpyxl

    report = build_report(store, SAMPLE_AUDIT_ID)
    ws = openpyxl.load_workbook(io.BytesIO(render(report, "xlsx").content)).active
    assert [c.value for c in ws[1]] == COLUMNS
    assert ws.max_row == 1 + len(report.issues) + 1  # header, issues, limitations
    assert ws.cell(ws.max_row, 1).value == NOTE_LABEL
    fix = ws.cell(2, COLUMNS.index("suggested_fix") + 1)
    assert fix.alignment.wrap_text and ws.column_dimensions["M"].width >= 50
    assert ws.freeze_panes == "A2"
