import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.findings import FindingStore
from app.report import config
from app.report.__main__ import main as cli
from app.report.fixture import SAMPLE_AUDIT_ID, load_sample


@pytest.fixture
def client(monkeypatch, tmp_path):
    db = tmp_path / "api.db"
    monkeypatch.delenv(config.INCLUDE_UNREVIEWED_ENV, raising=False)
    monkeypatch.setattr(main, "FindingStore", lambda: FindingStore(db))
    store = FindingStore(db)
    load_sample(store)
    with TestClient(main.app) as c:
        yield c, db
    if hasattr(main.app.state, "store"):
        del main.app.state.store


def test_api_json_report_defaults_to_approved_only(client):
    c, _ = client
    r = c.get(f"/audits/{SAMPLE_AUDIT_ID}/report", params={"format": "json"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    assert "attachment" in r.headers["content-disposition"] and r.headers["content-disposition"].endswith('.json"')
    assert {f["review_status"] for f in r.json()["findings"]} == {"approved"}


def test_api_csv_and_pdf(client):
    c, _ = client
    r = c.get(f"/audits/{SAMPLE_AUDIT_ID}/report", params={"format": "csv"})
    assert r.headers["content-type"].startswith("text/csv")
    assert len(list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))) == 1 + 12 + 1  # header, issues, limitations
    r = c.get(f"/audits/{SAMPLE_AUDIT_ID}/report")  # pdf is the default
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_api_errors(client):
    c, _ = client
    assert c.get("/audits/nope/report").status_code == 404
    assert c.get("/audits/nope/report/summary").status_code == 404
    assert c.get(f"/audits/{SAMPLE_AUDIT_ID}/report", params={"format": "docx"}).status_code == 422


def test_api_unreviewed_requires_server_flag(client, monkeypatch):
    c, _ = client
    r = c.get(f"/audits/{SAMPLE_AUDIT_ID}/report", params={"format": "json", "include_unreviewed": "true"})
    assert r.status_code == 403
    monkeypatch.setenv(config.INCLUDE_UNREVIEWED_ENV, "1")
    r = c.get(f"/audits/{SAMPLE_AUDIT_ID}/report", params={"format": "json", "include_unreviewed": "true"})
    assert r.status_code == 200 and {f["review_status"] for f in r.json()["findings"]} == {"approved", "pending"}


def test_api_summary_counts(client):
    c, _ = client
    s = c.get(f"/audits/{SAMPLE_AUDIT_ID}/report/summary").json()
    assert (s["total"], s["included"], s["excluded_unreviewed"], s["excluded_rejected"]) == (62, 53, 7, 2)
    assert s["unreviewed_allowed"] is False and s["formats"] == ["pdf", "json", "csv"]


def test_cli_fixture_all_formats(tmp_path, capsys):
    assert cli(["generate", "--fixture", "sample", "--format", "all", "--out", str(tmp_path)]) == 0
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {"sample-assessment.pdf", "sample-assessment.json", "sample-assessment.csv"}
    assert json.loads((tmp_path / "sample-assessment.json").read_text(encoding="utf-8"))["report"]["counts"]["included"] == 53
    assert "included 53 of 62" in capsys.readouterr().out


def test_cli_real_audit(client, tmp_path):
    _, db = client
    out = tmp_path / "out"
    assert cli(["generate", "--audit", SAMPLE_AUDIT_ID, "--db", str(db), "--format", "json", "--out", str(out)]) == 0
    assert (out / f"audit-{SAMPLE_AUDIT_ID[:8]}-assessment.json").exists()


def test_cli_unknown_audit_exits(client, tmp_path):
    _, db = client
    with pytest.raises(SystemExit):
        cli(["generate", "--audit", "missing", "--db", str(db), "--out", str(tmp_path)])
