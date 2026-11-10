# Evals

Seeded test pages and ground-truth labels for scoring the audit agent.

- `pages/` — 12 pages with known issues (01–12) and 3 clean pages (13–15), used to measure false positives. Each page is self-contained (no network).
- `labels.json` — the labeled issues per page. Clean pages have an empty `issues` list.
- Labels are ground truth. Never edit one to make a result look better.

`backend/tests/test_eval_labels.py` keeps the labels honest: every `axe` label must be flagged by axe-core at its selector, axe must not flag anything unlabeled, and clean pages must have no violations. `judgment` labels (alt text quality, link text meaning, heading structure, label clarity) are issues axe cannot see, so only the LLM can find them.

## W3C Before-After Demonstration (BAD)

`bad_labels.json` labels the five inaccessible "before" pages at https://www.w3.org/WAI/demos/bad/before/ (home, news, tickets, survey, template).

- The ground truth is W3C's own evaluation report for each page. Every label is a success criterion (Level A or AA) the report marks Fail. The reports are per criterion, not per element, so findings are matched to labels by `(url, wcag)`.
- Each label has `in_scope`: whether one of the agent's v1 checks (an axe rule, or one of the four judgment checks) can see it. Report recall over in-scope labels as the headline number, and over all labels for context. Out-of-scope labels (keyboard, focus, layout-table reading order, consistency across pages) need behavioural testing that v1 does not do.
- The reports list only what W3C's evaluator found, so a finding on an unlisted criterion counts against precision.
- The live pages are labeled, not copies. `page_sha256` records the HTML as retrieved on 2026-11-10 so drift can be detected.

## Running the harness

`backend/app/evals.py` audits the pages (one page each, no ticket writing), scores the findings, and saves the run to `evals/runs/`.

```
cd backend
python -m app.evals run --set seeded      # or bad / all; --only 09 to pick pages; costs API tokens
python -m app.evals score ../evals/runs/<file>.json   # re-score a saved run, free
```

Matching: seeded pages match a finding to a label by issue type (plus selector for judgment labels, since axe findings are grouped per rule); BAD pages match by WCAG criterion. WCAG mapping accuracy is the share of matched findings whose criterion is in the label's list. `tests/test_evals.py` checks the scoring offline.
