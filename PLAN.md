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
- A client-ready report of approved findings: a tagged (accessible) PDF, plus JSON and CSV exports. Stretch: an ACR in the VPAT format (see Reports).

### Out of scope for v1

Do not build these unless this file is updated:

- Legal compliance certification or replacing a manual audit.
- Auditing PDF documents, native mobile apps, video captions.
- Pages behind a login. Planned after v1: saved-session login (Playwright `storage_state`) with credentials kept out of the model's context and a deny-list for destructive actions.
- Changing the audited site's code automatically.
- Review by exception (auto-verifying high-confidence axe-core findings) and cross-page dedup beyond the existing root-cause grouping.

## Architecture

The agent is built with the **Claude Agent SDK (Python)**, not raw API calls. A Python orchestrator (plain code, not an LLM) runs three subagents in turn. It was an LLM at first, but it sometimes stopped after one page; a plain loop guarantees every crawled page is audited. Browser and axe-core access comes only through our own MCP server.

Flow:

1. **Site URL** goes to the **orchestrator** (Python code).
2. The orchestrator runs:
   - **Crawler subagent** — finds up to 20 pages and returns the page list. Uses only the MCP server's navigation tools. Runs on the smallest model.
   - **Auditor subagent** — for each page, runs axe-core through the MCP server, makes judgment calls rules can't (alt text quality, link text meaning, heading structure, form label clarity), maps each issue with `lookup_wcag`, and saves it with `save_finding`.
   - **Ticket writer subagent** — drafts a ticket with a suggested code fix for each saved finding, using `create_ticket`.
3. **Findings store** holds every finding and ticket.
   - Feeds the **Review UI**, where a human approves or rejects each finding; approved ones go to **Ticket export** (Markdown, JSON).
   - Feeds the **Eval harness**, which scores findings against labeled test pages.

### Agent rules

- The orchestrator is plain Python: it loops over the crawler's pages and starts one auditor run per page, sequentially (the browser server holds one page).
- Each subagent gets only the tools listed for it (define them with `AgentDefinition`).
- Allow only our own tools. Disable the SDK's built-in tools such as Bash and file writes.
- The Agent SDK runs on the Claude Code runtime; the Docker image must include it (see the SDK's install notes).

### MCP server: `a11y-browser`

- Built with the MCP Python SDK; runs as a standalone stdio server so the agent, Claude Code, or any MCP client can use it.
- Wraps the week 1 Playwright + axe-core functions; contains no LLM logic.
- Tools:
  - `navigate` — load a page
  - `list_links` — same-site links on the current page
  - `run_axe` — run axe-core and return compact results
  - `get_dom_snippet` — return the HTML for a flagged element
- Return compact, accessibility-focused results, never full raw HTML, to keep token costs down.

### In-process tools (Agent SDK `@tool`)

- `lookup_wcag` — retrieve the relevant WCAG success criterion
- `save_finding` — validate and store a finding
- `create_ticket` — store a remediation ticket for a finding

### Reports

Exporters read only from the findings store, never from a separate data path.

- Only approved findings appear in client-facing output. A config flag controls this, so a demo can show unreviewed findings with a visible "Unreviewed" label.
- Each finding carries its source (axe-core or AI-assessed) and a confidence level. Add these fields to the findings schema if they are missing.
- Wording says "assessment", never "certification" or "compliant". Every report includes a limitations statement: automated and AI-assisted testing doesn't cover every criterion, and the report is not a legal determination of compliance.
- PDF sections: executive summary (scope, standard, date, pages audited, counts by severity); findings table by WCAG criterion; finding detail with 508 mapping, explanation, and before/after code fix; limitations.
- The PDF must be tagged and accessible (headings, table headers, document title and language, reading order, contrast). Validate it with veraPDF. If the chosen library can't produce a valid tagged PDF, pick another rather than ship an untagged one.
- ACR (stretch): VPAT layout with cover information, evaluation methods, the five standard terms (Supports, Partially Supports, Does Not Support, Not Applicable, Not Evaluated), WCAG A and AA tables with remarks, Revised Section 508 chapters, and a disclaimer. Roll-up thresholds live in an editable config file. Criteria the audit didn't cover are Not Evaluated, never Supports. A criterion is marked Supports only if a person verified it.

### Stack

| Layer           | Choice                                                                     |
| --------------- | -------------------------------------------------------------------------- |
| Backend         | Python + FastAPI                                                           |
| Agent           | Claude Agent SDK (Python): Python orchestrator + 3 subagents               |
| Browser         | Playwright (Python) + axe-core, behind our own MCP server (MCP Python SDK) |
| Retrieval       | Local embeddings (sentence-transformers) over WCAG success criteria        |
| Storage         | SQLite to start, Postgres when deployed                                    |
| Frontend        | Angular + TypeScript (thin review UI)                                      |
| Tests and evals | pytest                                                                     |
| Deploy          | Docker on a free-tier host                                                 |
| Observability   | Structured log per tool call, with token cost per audit                    |

### Cost constraints

- Use only free or open-source tools, except the Claude API (the Agent SDK uses the same API key).
- Use the smallest Claude model during development, and for the crawler subagent always.
- Each subagent has its own context, which adds tokens; keep MCP results compact.
- Cache fetched pages so the same HTML isn't re-sent to the API.
- Log token usage and cost for every audit run.

## Milestones

Four two-week phases. Each ends on a gate that must pass before moving on.

### Phase 1 — Foundations (weeks 1–2)

Gate: one page audited, with structured output.

**Week 1 — Setup and crawl**

- [x] Repo, Python + FastAPI skeleton
- [x] Playwright + axe-core as plain Python functions with tests: load a page, run axe, save results

**Week 2 — MCP server and first agent**

- [x] Wrap the week 1 functions as the `a11y-browser` MCP server: `navigate`, `list_links`, `run_axe`, `get_dom_snippet`
- [x] Test the server with the MCP Inspector and from Claude Code
- [x] Agent SDK client connects to the server and audits one page
- [x] `save_finding` tool with a schema: WCAG criterion, severity, element, explanation

### Phase 2 — Core agent (weeks 3–4)

Gate: a 20-page site audited end to end.

**Week 3 — Subagents and retrieval**

- [x] Orchestrator plus crawler and auditor subagents, each with scoped tools
- [x] Crawler finds up to 20 pages; auditor audits each one
- [x] `lookup_wcag` tool: embed the success criteria, retrieve the right one per finding
- [x] Judgment checks for alt text, link text, headings, form labels

**Week 4 — Tickets and robustness**

- [x] Ticket writer subagent with `create_ticket`: suggested code fix per finding; Markdown and JSON export
- [x] Ticket writer groups findings by root cause before drafting tickets (for example, one missing `<main>` produces many 'region' nodes but should become one ticket)
- [x] Severity and plain-language explanations
- [x] Hooks that log each tool call with tokens and cost, per subagent
- [x] Retries and timeouts in the MCP server

### Phase 3 — Evals and UI (weeks 5–6)

Gate: metrics reported; evals run on every change.

**Week 5 — Eval set and baseline**

- [x] 10–15 test pages seeded with known, labeled issues, plus a few clean pages
- [x] Labels for the known issues on the W3C Before-After Demonstration (BAD) "before" pages
- [x] Eval harness reporting precision, recall, and WCAG mapping accuracy
- [x] Record the baseline in `evals/results.md`

**Week 6 — Review UI and iteration**

- [x] Angular review screen: audit progress, findings list, approve or reject
- [x] Improve prompts against the evals; log each change and its effect in `evals/results.md`
- [x] Compare a single-agent run with the subagent design on cost and accuracy; record the result

### Phase 4 — Ship (weeks 7–8)

Gate: public demo URL and one outside user.

**Week 7 — Report output** (done before deploy; deploy moved to week 8)

- [x] Findings model additions: `source` and `confidence` (with migration; the auditor sets both), `audits.pages`, and a realistic sample audit fixture (15 issues, 62 findings) so reports can be generated without a crawl. Review status already existed (`review_status`).
- [x] Tagged PDF report from approved findings (WeasyPrint, PDF/UA-1), validated with veraPDF: sample and real-audit PDFs pass; an untagged control fails.
- [x] JSON, CSV and formatted Excel (.xlsx) exports from the same model (`app/report/`). The CSV and XLSX end with a "Limitations" row.
- [x] CLI (`python -m app.report generate --fixture sample|--audit <id>`) and API (`GET /audits/{id}/report`, `/report/summary`)
- [x] Export panel in the Angular UI (format choice, included vs. excluded counts, download), checked with axe-core in its spec
- [x] Tests: each exporter against the fixture, unapproved and rejected excluded by default, the unreviewed flag adds only labeled pending findings, no secrets in output
- [ ] Stretch: ACR (VPAT-style) export with editable roll-up thresholds. **Deferred**, not started.
- [x] Run the report on one real audit and check the agent's output has every field the report needs (findings below)
- [ ] Run the evals on the auditor prompt change (source/confidence) and log it in `evals/results.md`; not yet run because it costs API tokens

Week 7 notes:

- Unreviewed findings are a demo switch: `REPORT_INCLUDE_UNREVIEWED=1` on the server, `--include-unreviewed` on the CLI. The API refuses to include them unless the server flag is on. The UI does not offer it.
- Weak fields in real agent output: confidence was "high" on 23 of 23 findings, so it carries no signal yet; each finding stores one selector, so a rule hit on many nodes of a page records only the first; the root-cause ticket grouping is per page, so one issue can have several tickets; the explanation is per finding and the PDF shows the first one for the issue.
- veraPDF and WeasyPrint's native libraries (Pango via MSYS2 on Windows) must be installed to validate and render; the Docker image in week 8 needs Pango.

**Week 8 — Deploy and finish**

- [ ] Dockerize and deploy to a public demo URL
- [ ] Optional: export tickets to GitHub Issues
- [ ] README with problem, approach, architecture, eval numbers, sample report, and limitations
- [ ] One real user runs it on their site

## Eval plan

### Dataset

- W3C Before-After Demonstration (BAD) "before" pages, with known accessibility failures.
- 10–15 seeded test pages, each with specific labeled issues.
- A few clean pages, to measure false positives.

### Metrics

| Metric                   | Definition                                                   |
| ------------------------ | ------------------------------------------------------------ |
| Precision per issue type | Findings that match a labeled issue ÷ all findings           |
| Recall per issue type    | Labeled issues found ÷ all labeled issues                    |
| WCAG mapping accuracy    | Correct success criterion ÷ matched findings                 |
| Explanation quality      | LLM-as-judge rubric, plus a manual spot check of 20 findings |
| Cost and latency         | Tokens and seconds per page                                  |

### Process

1. Set a baseline in week 5.
2. Run the full eval on every prompt, tool, or model change.
3. Log each run's results and what changed in `evals/results.md`.
4. Never edit eval labels to make a result look better.
