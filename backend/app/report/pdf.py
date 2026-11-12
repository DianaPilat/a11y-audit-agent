"""Tagged PDF (PDF/UA-1) report, rendered from an HTML template with WeasyPrint.

WeasyPrint needs the Pango libraries. On Windows they come from MSYS2 (`pacman -S mingw-w64-x86_64-pango`);
point `WEASYPRINT_DLL_DIRECTORIES` at its `mingw64/bin` if it isn't in the default place.
"""

import os
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.report.model import SEVERITY_ORDER, SOURCE_LABELS, UNREVIEWED_NOTICE, Report

TEMPLATES = Path(__file__).parent / "templates"
_MSYS2_BIN = Path(r"C:\msys64\mingw64\bin")


def render_html(report: Report) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    return env.get_template("report.html").render(
        r=report, severities=SEVERITY_ORDER, source_labels=SOURCE_LABELS, unreviewed_notice=UNREVIEWED_NOTICE
    )


def render_pdf(report: Report) -> bytes:
    if os.name == "nt" and "WEASYPRINT_DLL_DIRECTORIES" not in os.environ and _MSYS2_BIN.is_dir():
        os.environ["WEASYPRINT_DLL_DIRECTORIES"] = str(_MSYS2_BIN)
    from weasyprint import HTML  # imported late: it loads native libraries

    return HTML(string=render_html(report), base_url=str(TEMPLATES)).write_pdf(pdf_variant="pdf/ua-1")


def find_verapdf() -> str | None:
    """The veraPDF command: $VERAPDF, then PATH, then ~/tools/verapdf."""
    if env := os.environ.get("VERAPDF"):
        return env
    if found := shutil.which("verapdf"):
        return found
    local = Path.home() / "tools" / "verapdf" / ("verapdf.bat" if os.name == "nt" else "verapdf")
    return str(local) if local.exists() else None


def validate_pdf(path: Path | str) -> tuple[bool, str]:
    """Check a PDF against PDF/UA-1 with veraPDF. Returns (passed, output); raises if veraPDF isn't installed."""
    if (exe := find_verapdf()) is None:
        raise FileNotFoundError("veraPDF not found; set VERAPDF or put it on PATH")
    proc = subprocess.run(
        [exe, "--flavour", "ua1", "--format", "text", str(path)], capture_output=True, text=True, timeout=300
    )
    output = (proc.stdout + proc.stderr).strip()
    return output.startswith("PASS"), output
