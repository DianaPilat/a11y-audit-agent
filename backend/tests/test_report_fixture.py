import json
from collections import Counter

import pytest

from app.findings import FindingStore
from app.report.fixture import GROUPS, PAGES, SAMPLE_AUDIT_ID, load_sample


@pytest.fixture
def store():
    s = FindingStore(":memory:")
    load_sample(s)
    return s


def test_fixture_shape(store):
    rows = store.list(SAMPLE_AUDIT_ID)
    assert len(GROUPS) == 15
    assert 8 <= len({r["wcag_criterion"] for r in rows}) <= 12
    assert {r["review_status"] for r in rows} == {"approved", "pending", "rejected"}
    assert {r["source"] for r in rows} == {"axe-core", "ai-assessed"}
    assert len({r["severity"] for r in rows}) >= 3
    assert max(Counter((r["rule_id"], r["wcag_criterion"]) for r in rows).values()) >= 10  # a long URL list


def test_fixture_audit_and_tickets(store):
    audit = store.get_audit(SAMPLE_AUDIT_ID)
    assert len(json.loads(audit["pages"])) == len(PAGES)
    tickets = store.list_tickets(SAMPLE_AUDIT_ID)
    assert tickets and all(t["findings"] for t in tickets)


def test_fixture_has_no_real_hosts(store):
    assert all(".example" in r["url"] for r in store.list(SAMPLE_AUDIT_ID))


def test_pages_column_migrates(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE audits (id TEXT PRIMARY KEY, url TEXT NOT NULL, max_pages INTEGER NOT NULL,"
               " status TEXT NOT NULL DEFAULT 'queued', phase TEXT NOT NULL DEFAULT 'queued',"
               " pages_total INTEGER NOT NULL DEFAULT 0, pages_done INTEGER NOT NULL DEFAULT 0,"
               " pages_failed INTEGER NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    db.execute("INSERT INTO audits (id, url, max_pages) VALUES ('a', 'http://x', 5)")
    db.commit()
    db.close()
    s = FindingStore(path)
    assert s.get_audit("a")["pages"] == "[]"
