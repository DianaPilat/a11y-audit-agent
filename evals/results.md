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

## Run 2: 2026-11-11

Change: auditor prompt (`AUDITOR_PROMPT` in `backend/app/agent.py`). The "skip an issue if axe already reported the same element" rule now has an exception: axe's `heading-order` is not saved under its own rule id; each skipped heading level is reported as `judgment-heading-structure` (1.3.1), one finding per skipped heading. Reason: the baseline's only seeded false positive and both seeded recall misses were this one gap (page 07).
Raw run: `runs/2026-11-11T20-11-34+00-00.json`. Same model and pages as the baseline. Cost $1.03, about $0.052 and 36s per page.

| | Baseline | Run 2 |
| --- | --- | --- |
| Seeded precision | 96% (24/25) | 100% (26/26) |
| Seeded recall | 94% (29/31) | 100% (31/31) |
| Seeded judgment recall | 82% (9/11) | 100% (11/11) |
| Seeded WCAG mapping | 100% | 100% |
| Clean-page findings | 0 | 0 |
| BAD precision | 100% (28/28) | 100% (27/27) |
| BAD recall, in scope | 46% (23/50) | 48% (24/50) |
| Cost per page | $0.047 | $0.052 |

Effect:
- **Seeded:** the heading-structure label type went from 0/2 recall to 2/2, and the `heading-order` false positive is gone. This is the intended effect.
- **BAD:** one more in-scope label found (24 vs 23); the gain is survey.html now finding 4.1.2. The same criteria (1.3.1, 1.4.1, 2.4.1, 2.4.6) are still missed on every page, so the change did not touch the main BAD gap. Given run-to-run variation (the baseline was a single run), treat the +1 as noise.
- **Cost:** about 10% more per page, mostly from the longer prompt and the extra judgment findings. Within the noise of a single run.
- **Caveat:** the prompt change was written after reading the page 07 results, so 100% seeded is partly tuned to that page. The BAD pages are the held-out check and barely moved.

Next to try: the BAD misses. Candidates are a bypass-blocks check (2.4.1), colour-only cues (1.4.1) and a heading-text check (2.4.6) on pages with many issues.

## Single agent vs subagents: 2026-11-11

Change: none to the prompts. New `--single-agent` mode (`python -m app.evals run --single-agent`): one agent with the auditor prompt audits all pages of a set in one context (15 seeded pages in one run, 5 BAD pages in another), instead of a fresh auditor per page. Compared against Run 2 (same prompt, model and pages). The crawler and ticket writer are not part of the comparison; evals do not use them.
Raw run: `runs/2026-11-11T20-50-28+00-00.json`. Time per page is the run's total split evenly.

| | Subagents (Run 2) | Single agent |
| --- | --- | --- |
| Seeded precision | 100% (26/26) | 100% (21/21) |
| Seeded recall | 100% (31/31) | 100% (31/31) |
| Seeded judgment recall | 100% (11/11) | 100% (11/11) |
| Seeded WCAG mapping | 100% | 100% |
| Clean-page findings | 0 | 0 |
| BAD precision | 100% (27/27) | 100% (26/26) |
| BAD recall, in scope | 48% (24/50) | 46% (23/50) |
| Total cost (20 pages) | $1.03 | $0.75 |
| Cost per page | $0.052 | $0.038 |
| Time (20 pages) | about 720s | 330s |

Effect:
- **Cost:** about 27% cheaper and about twice as fast. The per-page auditor re-sends the system prompt and tool definitions and starts a new MCP server for every page; the single agent pays for that once.
- **Accuracy:** same recall on the seeded pages and one fewer in-scope BAD label (23 vs 24, within run-to-run noise). The single agent saved fewer findings on the seeded pages (21 vs 26): judgment findings dropped from 11 to 6 (link text 4 to 2, label clarity 2 to 1, alt text 3 to 1). Recall did not drop because it counts a label as found if any finding matches it, so one finding that covers several elements still scores. That points to the single agent grouping or skipping repeated judgment issues late in the run; per-element recall would show it.
- **Limits of this test:** one run each, 15 and 5 pages. A single context grows with every page, so at 20 pages it still worked on Haiku, but a larger site will hit the context limit or force summarizing, which the per-page design avoids. The subagent design also keeps one failed page from affecting the others, and lets the crawler run on a different model.

Decision: keep the subagent design for the product (isolated failures, bounded context, per-page progress for the UI). The single agent is the cheaper option for small sites; revisit if cost matters more than the per-element thoroughness.
