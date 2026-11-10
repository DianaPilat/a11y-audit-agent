# Eval results

Each entry is one full run of `python -m app.evals run --set all`. Labels are never edited to improve a result (PLAN.md, Eval plan). Raw findings for each run are in `runs/`.

## Baseline: 2026-11-10

Change: none (first run). Model `claude-haiku-4-5-20251001` for all subagents, 20 pages (15 seeded, 5 W3C BAD "before"), one page per audit, no ticket writing.
Raw run: `runs/2026-11-10T20-53-09+00-00.json`. Cost $0.94 total, about $0.047 and 30s per page.

Model: claude-haiku-4-5-20251001 | 2026-11-10T20:53:09+00:00
Cost $0.9365 and 606s over 20 pages ($0.0468, 30s per page)

## Seeded pages

| Issue type | Precision | Recall | WCAG mapping |
| --- | --- | --- | --- |
| **all** | 96% (24/25) | 94% (29/31) | 100% (24/24) |
| axe rules | 94% (15/16) | 100% (20/20) | 100% (15/15) |
| judgment checks | 100% (9/9) | 82% (9/11) | 100% (9/9) |
| alt-text-quality | 100% (3/3) | 100% (3/3) | 100% (3/3) |
| aria-hidden-focus | 100% (1/1) | 100% (1/1) | 100% (1/1) |
| aria-roles | 100% (1/1) | 100% (1/1) | 100% (1/1) |
| aria-valid-attr-value | 100% (1/1) | 100% (1/1) | 100% (1/1) |
| button-name | 100% (1/1) | 100% (2/2) | 100% (1/1) |
| color-contrast | 100% (2/2) | 100% (3/3) | 100% (2/2) |
| document-title | 100% (1/1) | 100% (1/1) | 100% (1/1) |
| heading-order | 0% (0/1) | n/a (0/0) | n/a (0/0) |
| heading-structure | n/a (0/0) | 0% (0/2) | n/a (0/0) |
| html-has-lang | 100% (1/1) | 100% (1/1) | 100% (1/1) |
| image-alt | 100% (2/2) | 100% (4/4) | 100% (2/2) |
| label | 100% (2/2) | 100% (3/3) | 100% (2/2) |
| label-clarity | 100% (2/2) | 100% (2/2) | 100% (2/2) |
| link-name | 100% (2/2) | 100% (2/2) | 100% (2/2) |
| link-text-meaning | 100% (4/4) | 100% (4/4) | 100% (4/4) |
| meta-viewport | 100% (1/1) | 100% (1/1) | 100% (1/1) |

Clean pages: 0 findings across 3 pages (should be 0).

## W3C BAD pages (matched by criterion)

- Precision: 100% (28/28)
- Recall, in scope: 46% (23/50)
- Recall, all labels: 24% (23/96)
- home.html: 6/6 findings match; missed in scope: 1.3.1, 1.4.1, 2.4.1, 2.4.6, 3.3.2
- news.html: 5/5 findings match; missed in scope: 1.3.1, 1.4.1, 1.4.3, 2.4.1, 2.4.6, 3.3.2
- tickets.html: 6/6 findings match; missed in scope: 1.3.1, 1.4.1, 2.4.1, 2.4.6, 3.3.2
- survey.html: 5/5 findings match; missed in scope: 1.3.1, 1.4.1, 1.4.3, 2.4.1, 2.4.6, 4.1.2
- template.html: 6/6 findings match; missed in scope: 1.3.1, 1.4.1, 2.4.1, 2.4.6, 3.3.2

## Reading the baseline

- **Seeded recall misses are both heading-structure labels (07).** The agent reported axe's `heading-order` (a best-practice rule the labels deliberately ignore) instead of a `judgment-heading-structure` finding. That one finding is also the only seeded false positive. So the real gap is that the auditor does not make the heading judgment call when axe already flags headings; it is the first prompt change to try in week 6.
- **BAD precision is flattering.** Matching is by WCAG criterion only, so any finding on a labeled criterion counts, whatever element it describes. Treat 100% as "no findings on unlisted criteria", not "every finding is right".
- **BAD recall in scope is 46% (23/50).** Every page misses the same criteria: 1.3.1, 1.4.1, 2.4.1, 2.4.6, plus 3.3.2 on most. These are mostly judgment checks (labels, heading text, structure) and bypass blocks/colour-only cues that the agent did not report on pages with many issues. Recall over all labels is 24% because 46 of the 96 labels are out of scope (keyboard, focus, layout tables, cross-page consistency).
- **WCAG mapping is 100% (24/24)** on seeded pages, but the label lists allow several criteria per issue, so this is a lenient bar.
- Single run, no repeat: model output varies between runs, so differences of a few points are not yet meaningful.
