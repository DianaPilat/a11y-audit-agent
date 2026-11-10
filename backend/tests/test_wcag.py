import json

import numpy as np
import pytest

from app import wcag
from app.wcag import WcagIndex, load_criteria, make_lookup_wcag_tool


def _payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def test_criteria_cover_wcag21_a_and_aa():
    criteria = load_criteria()
    assert len(criteria) == 50
    assert {c["level"] for c in criteria.values()} == {"A", "AA"}
    assert {"1.1.1", "1.4.3", "2.4.7", "4.1.2", "1.4.10", "1.4.13"} <= set(criteria)
    assert "2.2.6" not in criteria and "1.4.6" not in criteria  # WCAG 2.1 AAA, and WCAG 2.2 only
    assert all(c["text"] and c["failures"] and c["url"].startswith("https://www.w3.org/") for c in criteria.values())


def test_search_ranks_by_similarity_and_clamps_limit():
    criteria = list(load_criteria().values())
    target = criteria[7]["num"]
    vectors = np.eye(len(criteria))  # one orthogonal vector per criterion

    def fake_embed(texts):
        if len(texts) == 1:  # the query: closest to the target, then to the next criterion
            query = np.zeros(len(criteria))
            query[7], query[8] = 1.0, 0.5
            return query[None, :]
        return vectors

    index = WcagIndex(embedder=fake_embed)
    hits = index.search("anything", limit=2)
    assert [h["criterion"] for h in hits] == [target, criteria[8]["num"]]
    assert hits[0]["score"] > hits[1]["score"]
    assert len(index.search("anything", limit=99)) == wcag.MAX_LIMIT
    assert len(index.search("anything", limit=0)) == 1
    assert set(hits[0]) == {"criterion", "name", "level", "requirement", "url", "score"}


async def test_lookup_wcag_tool_returns_matches_and_rejects_empty_query():
    index = WcagIndex(embedder=lambda texts: np.ones((len(texts), 3)))
    handler = make_lookup_wcag_tool(index).handler
    ok = await handler({"query": "image has no alt text", "limit": 2})
    assert len(_payload(ok)["matches"]) == 2 and "is_error" not in ok
    default = await handler({"query": "x"})
    assert len(_payload(default)["matches"]) == wcag.DEFAULT_LIMIT
    bad = await handler({"query": "   "})
    assert bad["is_error"] and "empty" in _payload(bad)["error"]


# Real embedding model (local, no API cost). Each issue is described as the auditor would.
RETRIEVAL_CASES = [
    ("image is missing alt text", "1.1.1"),
    ("text has insufficient color contrast against its background", "1.4.3"),
    ("form input has no label", "3.3.2"),
    ("link text is just 'click here' and does not describe where it goes", "2.4.4"),
    ("html element has no lang attribute", "3.1.1"),
    ("page has no title element", "2.4.2"),
    ("keyboard focus outline is removed so focus is not visible", "2.4.7"),
    ("video has no captions", "1.2.2"),
    ("zooming is disabled with user-scalable=no", "1.4.4"),
    ("no skip link to bypass repeated navigation", "2.4.1"),
    ("iframe has no title so its accessible name is missing", "4.1.2"),
    ("moving carousel cannot be paused", "2.2.2"),
]


@pytest.fixture(scope="module")
def real_index() -> WcagIndex:
    return WcagIndex()


@pytest.mark.parametrize("query,expected", RETRIEVAL_CASES)
def test_real_retrieval_finds_the_right_criterion_in_top_3(real_index, query, expected):
    assert expected in [h["criterion"] for h in real_index.search(query, 3)]
