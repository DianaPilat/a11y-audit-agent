import io
import re

import pytest

from app.findings import FindingStore
from app.report.fixture import load_sample
from app.report.model import LIMITATIONS, UNREVIEWED_NOTICE, build_report
from app.report.pdf import find_verapdf, render_html, render_pdf, validate_pdf

pypdf = pytest.importorskip("pypdf")
pytest.importorskip("weasyprint", exc_type=OSError)  # needs Pango; see app/report/pdf.py


@pytest.fixture(scope="module")
def report():
    s = FindingStore(":memory:")
    load_sample(s)
    return build_report(s, "sample", generated_on="2026-11-12")


@pytest.fixture(scope="module")
def pdf_bytes(report):
    return render_pdf(report)


def _struct_types(reader) -> dict[str, int]:
    counts: dict[str, int] = {}

    def walk(node):
        node = node.get_object()
        if "/S" in node:
            counts[str(node["/S"])] = counts.get(str(node["/S"]), 0) + 1
        kids = node.get("/K")
        for kid in kids if isinstance(kids, list) else [kids] if kids is not None else []:
            kid = kid.get_object() if hasattr(kid, "get_object") else kid
            if hasattr(kid, "get"):
                walk(kid)

    walk(reader.trailer["/Root"]["/StructTreeRoot"])
    return counts


def test_html_sections_and_wording(report):
    html = render_html(report)
    for heading in ("Executive summary", "Findings by WCAG criterion", "Finding details", "Limitations"):
        assert f">{heading}</h2>" in html
    assert report.limitations in html or "not a legal" in html
    text = re.sub(r"<[^>]+>", " ", html).lower()
    assert "certif" not in text and "compliant" not in text
    assert "unreviewed" not in text.replace(".unreviewed", "")  # default report has no unreviewed material


def test_unreviewed_report_is_labeled():
    s = FindingStore(":memory:")
    load_sample(s)
    html = render_html(build_report(s, "sample", include_unreviewed=True))
    assert UNREVIEWED_NOTICE.split(":")[0] in html
    assert '<span class="unreviewed">Unreviewed</span>' in html


def test_pdf_is_tagged_with_title_language_headings_and_table_headers(pdf_bytes):
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    root = reader.trailer["/Root"]
    assert root["/Lang"] == "en"
    assert bool(root["/MarkInfo"]["/Marked"])
    assert bool(root["/ViewerPreferences"]["/DisplayDocTitle"])
    assert "Accessibility Assessment Report" in reader.metadata.title
    types = _struct_types(reader)
    assert types["/H1"] == 1 and types["/H2"] >= 4 and types["/H3"] >= 10
    assert types["/Table"] >= 2 and types["/TH"] > 0 and types["/THead"] >= 2
    text = " ".join(p.extract_text() for p in reader.pages)
    assert LIMITATIONS[:40] in text


@pytest.mark.skipif(find_verapdf() is None, reason="veraPDF not installed")
def test_pdf_passes_verapdf_ua1(pdf_bytes, tmp_path):
    path = tmp_path / "r.pdf"
    path.write_bytes(pdf_bytes)
    passed, output = validate_pdf(path)
    assert passed, output
