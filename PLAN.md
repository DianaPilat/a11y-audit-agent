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

The agent is built with the **Claude Agent SDK (Python)**, not raw API calls. An orchestrator delegates to three subagents. Browser and axe-core access comes only through our own MCP server.

Flow:

1. **Site URL** goes to the **orchestrator**.
2. The orchestrator delegates to:
   - **Crawler subagent** — finds up to 20 pages and returns the page list. Uses only the MCP server's navigation tools. Runs on the smallest model.
   - **Auditor subagent** — for each page, runs axe-core through the MCP server, makes judgment calls rules can't (alt text quality, link text meaning, heading structure, form label clarity), maps each issue with `lookup_wcag`, and saves it with `save_finding`.
   - **Ticket writer subagent** — drafts a ticket with a suggested code fix for each saved finding, using `create_ticket`.
3. **Findings store** holds every finding and ticket.
   - Feeds the **Review UI**, where a human approves or rejects each finding; approved ones go to **Ticket export** (Markdown, JSON).
   - Feeds the **Eval harness**, which scores findings against labeled test pages.

### Agent rules

- The orchestrator has no browser tools of its own; it only delegates.
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

### Stack

| Layer           | Choice                                                                     |
| --------------- | -------------------------------------------------------------------------- |
| Backend         | Python + FastAPI                                                           |
| Agent           | Claude Agent SDK (Python): orchestrator + 3 subagents                      |
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
- [ ] `save_finding` tool with a schema: WCAG criterion, severity, element, explanation

### Phase 2 — Core agent (weeks 3–4)

Gate: a 20-page site audited end to end.

**Week 3 — Subagents and retrieval**

- [ ] Orchestrator plus crawler and auditor subagents, each with scoped tools
- [ ] Crawler finds up to 20 pages; auditor audits each one
- [ ] `lookup_wcag` tool: embed the success criteria, retrieve the right one per finding
- [ ] Judgment checks for alt text, link text, headings, form labels

**Week 4 — Tickets and robustness**

- [ ] Ticket writer subagent with `create_ticket`: suggested code fix per finding; Markdown and JSON export
- [ ] Ticket writer groups findings by root cause before drafting tickets (for example, one missing `<main>` produces many 'region' nodes but should become one ticket)
- [ ] Severity and plain-language explanations
- [ ] Hooks that log each tool call with tokens and cost, per subagent
- [ ] Retries and timeouts in the MCP server

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
- [ ] Compare a single-agent run with the subagent design on cost and accuracy; record the result

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
