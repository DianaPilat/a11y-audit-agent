# Accessibility Audit Agent — Plan

## Goal

Build an AI agent that audits a website against Section 508 and WCAG 2.1 AA, explains each finding in plain language, and drafts fix-ready remediation tickets. Deterministic rules run first; the LLM handles only what rules can't judge. A human approves findings before they become tickets.

## Scope

### In v1

- Crawl up to about 20 pages of a site with a headless browser.
- Run axe-core rule checks first, then use the LLM for judgment calls: alt text quality, link text meaning, heading structure, form label clarity.
- Map each finding to its WCAG 2.1 AA success criterion and Section 508 reference.
- Explain each issue in plain language, with severity and who it affects.
- Draft a remediation ticket per finding with a suggested code fix, exported as Markdown or JSON.
- A thin web UI: enter a URL, watch progress, approve or reject each finding.

### Out of scope for v1

Do not build these unless this file is updated:

- Legal compliance certification or replacing a manual audit.
- PDFs, native mobile apps, video captions.
- Pages behind a login.
- Changing the audited site's code automatically.

## Architecture

Pipeline, in order:

1. **Site URL** — input; up to 20 pages.
2. **Crawler** — Playwright renders each page.
3. **Rule checks** — axe-core runs on each rendered page.
4. **LLM agent** — Claude with tool use reviews the axe results and the page, adds judgment checks, maps findings to WCAG, and writes explanations.
   - Uses a **WCAG knowledge** tool: retrieval over WCAG success criteria (local embeddings).
5. **Findings store** — every finding is saved here.
   - Feeds the **Review UI**, where a human approves or rejects each finding, and approved findings go to **Ticket export** (Markdown, JSON).
   - Feeds the **Eval harness**, which scores findings against labeled test pages.

### Agent tools

- `fetch_page` — load a page via Playwright
- `run_axe` — run axe-core on the current page
- `get_dom_snippet` — return the HTML for a flagged element
- `lookup_wcag` — retrieve the relevant WCAG success criterion
- `create_ticket` — draft a remediation ticket for a finding

### Stack

| Layer | Choice |
| --- | --- |
| Backend | Python + FastAPI |
| Agent | Claude API with tool use (Anthropic Python SDK) |
| Browser | Playwright (Python) + axe-core |
| Retrieval | Local embeddings (sentence-transformers) over WCAG success criteria |
| Storage | SQLite to start, Postgres when deployed |
| Frontend | Angular + TypeScript (thin review UI) |
| Tests and evals | pytest |
| Deploy | Docker on a free-tier host |
| Observability | Structured log per tool call, with token cost per audit |

### Cost constraints

- Use only free or open-source tools, except the Claude API.
- Use the smallest Claude model during development.
- Cache fetched pages so the same HTML isn't re-sent to the API.
- Log token usage and cost for every audit run.

## Milestones

Four two-week phases. Each ends on a gate that must pass before moving on.

### Phase 1 — Foundations (weeks 1–2)

Gate: one page audited, with structured output.

**Week 1 — Setup and crawl**
- [ ] Repo, Python + FastAPI skeleton
- [ ] Playwright loads one page; axe-core results saved

**Week 2 — First agent loop**
- [ ] Claude API call with tools: `fetch_page`, `run_axe`, `get_dom_snippet`
- [ ] Structured output schema for a finding: WCAG criterion, severity, element, explanation

### Phase 2 — Core agent (weeks 3–4)

Gate: a 20-page site audited end to end.

**Week 3 — Retrieval and judgment**
- [ ] `lookup_wcag` tool: embed the success criteria, retrieve the right one per finding
- [ ] LLM checks for alt text, link text, headings, form labels
- [ ] Multi-page crawl, up to 20 pages

**Week 4 — Tickets and robustness**
- [ ] Severity and plain-language explanations
- [ ] `create_ticket` with suggested code fixes; Markdown and JSON export
- [ ] Retries, timeouts, cost logging per audit

### Phase 3 — Evals and UI (weeks 5–6)

Gate: metrics reported; evals run on every change.

**Week 5 — Eval set and baseline**
- [ ] 10–15 test pages seeded with known, labeled issues, plus a few clean pages
- [ ] Labels for the known issues on the W3C Before-After Demonstration (BAD) "before" pages
- [ ] Eval harness reporting precision, recall, and WCAG mapping accuracy
- [ ] Record the baseline in `evals/results.md`

**Week 6 — Review UI and iteration**
- [ ] Angular review screen: audit progress, findings list, approve or reject
- [ ] Improve prompts against the evals; log each change and its effect in `evals/results.md`

### Phase 4 — Ship (weeks 7–8)

Gate: public demo URL and one outside user.

**Week 7 — Deploy**
- [ ] Dockerize and deploy to a public demo URL
- [ ] Optional: export tickets to GitHub Issues

**Week 8 — Finish**
- [ ] README with problem, approach, architecture, eval numbers, and limitations
- [ ] One real user runs it on their site

## Eval plan

### Dataset

- W3C Before-After Demonstration (BAD) "before" pages, with known accessibility failures.
- 10–15 seeded test pages, each with specific labeled issues.
- A few clean pages, to measure false positives.

### Metrics

| Metric | Definition |
| --- | --- |
| Precision per issue type | Findings that match a labeled issue ÷ all findings |
| Recall per issue type | Labeled issues found ÷ all labeled issues |
| WCAG mapping accuracy | Correct success criterion ÷ matched findings |
| Explanation quality | LLM-as-judge rubric, plus a manual spot check of 20 findings |
| Cost and latency | Tokens and seconds per page |

### Process

1. Set a baseline in week 5.
2. Run the full eval on every prompt, tool, or model change.
3. Log each run's results and what changed in `evals/results.md`.
4. Never edit eval labels to make a result look better.
