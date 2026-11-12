import pytest
from fastapi.testclient import TestClient

from app import main
from app.findings import Finding, FindingStore

FINDING = Finding(
    url="http://x/", rule_id="image-alt", wcag_criterion="1.1.1", severity="critical",
    element="img.hero", explanation="Screen reader users hear no description of this image. Add alt text.",
    source="axe-core", confidence="high",
)


@pytest.fixture
def client(monkeypatch, tmp_path):
    db = tmp_path / "api.db"
    monkeypatch.setattr(main, "FindingStore", lambda: FindingStore(db))  # created lazily on the app's thread
    store = FindingStore(db)  # the test's own connection to the same file

    async def fake_audit(url, max_pages, store, audit_id):
        store.update_audit(audit_id, status="done", phase="done", pages_total=1, pages_done=1)
        store.save(audit_id, FINDING)

    monkeypatch.setattr(main, "audit_site", fake_audit)
    with TestClient(main.app) as c:
        yield c, store
    if hasattr(main.app.state, "store"):
        del main.app.state.store


def test_start_audit_and_review(client):
    c, _ = client
    r = c.post("/audits", json={"url": "http://x/", "max_pages": 3})
    assert r.status_code == 202
    audit_id = r.json()["id"]

    audit = c.get(f"/audits/{audit_id}").json()
    assert audit["status"] == "done" and audit["pages_total"] == 1
    assert audit["review_counts"] == {"pending": 1, "approved": 0, "rejected": 0}

    [finding] = c.get(f"/audits/{audit_id}/findings").json()
    assert finding["review_status"] == "pending"

    r = c.patch(f"/audits/{audit_id}/findings/{finding['id']}", json={"status": "approved"})
    assert r.json()["review_status"] == "approved"
    assert c.get(f"/audits/{audit_id}").json()["review_counts"]["approved"] == 1


def test_rejects_bad_input(client):
    c, _ = client
    assert c.post("/audits", json={"url": "ftp://x"}).status_code == 422
    assert c.post("/audits", json={"url": "http://x", "max_pages": 99}).status_code == 422
    assert c.get("/audits/nope").status_code == 404
    assert c.patch("/audits/nope/findings/1", json={"status": "approved"}).status_code == 404


def test_invalid_review_status(client):
    c, store = client
    store.create_audit("a", "http://x", 1)
    fid, _ = store.save("a", FINDING)
    assert c.patch(f"/audits/a/findings/{fid}", json={"status": "maybe"}).status_code == 422


def test_failed_audit_is_recorded(client, monkeypatch):
    c, _ = client

    async def boom(**kwargs):
        raise RuntimeError("browser died")

    monkeypatch.setattr(main, "audit_site", lambda *a, **k: boom())
    audit_id = c.post("/audits", json={"url": "http://x/"}).json()["id"]
    audit = c.get(f"/audits/{audit_id}").json()
    assert audit["status"] == "failed" and "browser died" in audit["error"]
