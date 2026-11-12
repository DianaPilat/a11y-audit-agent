# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

An AI agent that audits a site against WCAG 2.1 AA / Section 508 and drafts remediation tickets. [PLAN.md](PLAN.md) is the source of truth for scope, architecture and milestones (update it before building anything it lists as out of scope). [README.md](README.md) and [evals/README.md](evals/README.md) cover running things.

## Commands

Backend (run from `backend/`, venv active: `.venv\Scripts\activate`; Windows):

```
uvicorn app.main:app --reload                     # API on :8000
playwright install chromium                       # one-time
python -m app.browser <url>                       # plain axe audit -> backend/data/results/
python -m app.agent <url> [max_pages]             # full agent run (costs API tokens, needs ANTHROPIC_API_KEY)
python -m app.mcp_server                          # a11y-browser MCP server over stdio
pytest                                            # all tests
pytest tests/test_findings.py::test_name          # single test
RUN_LIVE=1 pytest -m live                         # live Claude API tests (skipped otherwise)
python -m app.evals run --set seeded|bad|all [--only 09]   # costs API tokens; saves to evals/runs/
python -m app.evals score ../evals/runs/<file>.json         # re-score a saved run, free
python scripts/build_wcag_data.py                 # regenerate app/data/wcag21.json
python -m app.report generate --fixture sample --format all --validate   # or --audit <id>; reports go to ../reports/ (needs Pango and veraPDF, see PLAN.md)
```

Frontend (run from `frontend/`, Node >= 22.12): `npm start` (:4200, proxies `/api` -> `localhost:8000`), `npm test` (set `CHROME_BIN` if Chrome isn't found), `npm run build`.

## Architecture

- **Orchestration is plain Python, not an LLM** ([backend/app/agent.py](backend/app/agent.py), `audit_site`): crawler run -> one auditor run per page (sequential, since the browser server holds a single page) -> one ticket-writer run that groups findings by root cause. An LLM orchestrator was dropped because it stopped after one page. Each step is its own Claude Agent SDK run with a scoped tool list; SDK built-in tools (Bash, file writes) are disabled. The crawler always uses the smallest model (Haiku); default model is Haiku during development.
- **Browser access only via our MCP server** ([mcp_server.py](backend/app/mcp_server.py), wrapping Playwright + axe in [browser.py](backend/app/browser.py)): `navigate`, `list_links`, `run_axe`, `get_dom_snippet`, `get_page_content`. It has no LLM logic, must return compact results (token cost), and has retries/timeouts. It is registered for Claude Code in [.mcp.json](.mcp.json) with absolute paths to this machine's venv.
- **In-process SDK tools**, each built as a small MCP server bound to an `audit_id`: `lookup_wcag` ([wcag.py](backend/app/wcag.py), local sentence-transformers embeddings over the 50 A/AA criteria in `app/data/`), `save_finding` and `create_ticket` ([findings.py](backend/app/findings.py), [tickets.py](backend/app/tickets.py)). `save_finding` rejects criteria not in the 50-criterion list.
- **Storage**: `FindingStore` (SQLite, `backend/data/findings.db`, gitignored) holds audits, findings and tickets. It uses a single connection, so FastAPI handlers in [main.py](backend/app/main.py) are deliberately `async` to share the event loop thread with the background audit task. Don't make them sync `def`.
- **API -> UI**: `POST /audits` starts a background audit; the Angular app ([frontend/src/app/audit/](frontend/src/app/audit/)) polls `/audits/{id}` for progress and `PATCH`es findings to approve/reject. Only approved findings go to ticket export (Markdown/JSON).
- **Observability** ([observability.py](backend/app/observability.py)): `UsageTracker` logs each tool call with tokens and cost per subagent.

## Evals

- [evals/](evals/) holds 15 seeded pages (12 with issues, 3 clean) with `labels.json`, plus W3C BAD page labels in `bad_labels.json`. Labels are ground truth: never edit them to improve a result. `tests/test_eval_labels.py` verifies seeded labels against real axe output.
- Every prompt, tool or model change should be run through the harness and logged in [evals/results.md](evals/results.md) with what changed and its effect.
