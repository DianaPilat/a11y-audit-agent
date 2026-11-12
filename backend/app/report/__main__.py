"""CLI: python -m app.report generate (--fixture sample | --audit <id>) --format pdf|json|csv|all"""

import argparse
import sys
from pathlib import Path

from app.findings import DEFAULT_DB_PATH, FindingStore
from app.report.export import FORMATS, render
from app.report.fixture import SAMPLE_AUDIT_ID, load_sample
from app.report.model import build_report
from app.report.pdf import validate_pdf

DEFAULT_OUT = Path(__file__).resolve().parents[3] / "reports"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.report")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="write a report from the findings store")
    source = gen.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", choices=["sample"], help="use the built-in sample audit (no crawl needed)")
    source.add_argument("--audit", metavar="ID", help="id of a real audit in the findings database")
    gen.add_argument("--format", choices=[*FORMATS, "all"], default="pdf")
    gen.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output folder (default {DEFAULT_OUT})")
    gen.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="findings database for --audit")
    gen.add_argument("--include-unreviewed", action="store_true", default=None,
                     help="demo only: also list unreviewed findings, labeled (default: REPORT_INCLUDE_UNREVIEWED, else off)")
    gen.add_argument("--validate", action="store_true", help="check a PDF against PDF/UA-1 with veraPDF")
    args = parser.parse_args(argv)

    if args.fixture:
        store = FindingStore(":memory:")
        audit_id = load_sample(store)
    else:
        if not args.db.exists():
            parser.error(f"no findings database at {args.db}")
        store, audit_id = FindingStore(args.db), args.audit
    try:
        report = build_report(store, audit_id, args.include_unreviewed)
    except LookupError as e:
        parser.error(str(e))

    args.out.mkdir(parents=True, exist_ok=True)
    code = 0
    for fmt in FORMATS if args.format == "all" else [args.format]:
        rendered = render(report, fmt)
        path = args.out / f"{'sample' if args.fixture else 'audit-' + audit_id[:8]}-assessment.{rendered.extension}"
        path.write_bytes(rendered.content)
        print(f"wrote {path}")
        if fmt == "pdf" and args.validate:
            try:
                passed, output = validate_pdf(path)
            except FileNotFoundError as e:
                print(f"validation skipped: {e}", file=sys.stderr)
                code = 1
                continue
            print(f"veraPDF PDF/UA-1: {'PASS' if passed else 'FAIL'}")
            if not passed:
                print(output)
                code = 1
    print(f"included {report.counts['included']} of {report.counts['total']} findings "
          f"({report.counts['excluded']} excluded)" + ("; includes UNREVIEWED findings" if report.include_unreviewed else ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
