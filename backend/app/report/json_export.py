"""JSON export: every included finding with every schema field, plus report context."""

import json

from app.report.model import UNREVIEWED, Report


def to_json(report: Report) -> str:
    findings = [{**f, "unreviewed": f["review_status"] == "pending"} for f in report.findings]
    doc = {
        "report": {
            "audit_id": report.audit_id, "site": report.site, "standard": report.standard,
            "assessment_date": report.audit_date, "generated_on": report.generated_on,
            "pages_audited": report.pages, "include_unreviewed": report.include_unreviewed,
            "unreviewed_label": UNREVIEWED if report.include_unreviewed else None,
            "counts": report.counts, "limitations": report.limitations,
        },
        "issues": [
            {
                "rule_id": i.rule_id, "wcag_criterion": i.criterion, "criterion_name": i.criterion_name, "level": i.level,
                "section_508": i.section_508, "severity": i.severity, "source": i.source, "confidence": i.confidence,
                "status": i.status, "pages_affected": len(i.urls), "urls": i.urls, "elements": i.elements,
                "ticket_ids": i.ticket_ids, "tickets": i.tickets,
            }
            for i in report.issues
        ],
        "findings": findings,
    }
    return json.dumps(doc, indent=2, ensure_ascii=False)

