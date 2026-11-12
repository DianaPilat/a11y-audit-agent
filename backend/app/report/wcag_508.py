"""Revised Section 508 references for WCAG success criteria.

The Revised 508 Standards (36 CFR 1194, Appendix A) require web content to meet WCAG 2.0 Level A and AA
(E205.4). Criteria that first appeared in WCAG 2.1 are therefore not part of the 508 baseline; this audit tests
them because the standard being assessed is WCAG 2.1 AA.
"""

WCAG_21_ONLY = {
    "1.3.4", "1.3.5", "1.4.10", "1.4.11", "1.4.12", "1.4.13",
    "2.1.4", "2.5.1", "2.5.2", "2.5.3", "2.5.4", "4.1.3",
}


def section_508(criterion: str) -> str:
    if criterion in WCAG_21_ONLY:
        return "Not in the Revised Section 508 baseline (WCAG 2.0); added in WCAG 2.1"
    return f"Revised Section 508 E205.4 (WCAG 2.0 {criterion})"
