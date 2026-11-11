# Accessibility Audit Agent

An AI agent that audits a website against Section 508 and WCAG 2.1 AA and drafts remediation tickets. See [PLAN.md](PLAN.md) for scope, architecture, and milestones.

## Run the backend

```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/health.

## Run the review UI

The Angular app starts audits, shows progress, and lets you approve or reject each finding. It needs the backend running on port 8000 (the dev server proxies `/api` to it) and Node 22.12 or newer.

```
cd frontend
npm install
npm start
```

Then open http://localhost:4200. `npm test` runs the component tests (set `CHROME_BIN` if Chrome isn't found).

## Audit a page

One-time browser install, then run an audit; results are saved as JSON under `backend/data/results/`.

```
playwright install chromium
python -m app.browser https://example.com
```

## Run the agent

An orchestrator delegates to a crawler subagent (finds up to `max_pages` pages) and an auditor subagent (audits one page at a time through the `a11y-browser` MCP server and saves each issue with `save_finding`). Uses the Claude API, a few cents per run.

Run it from the `backend` folder with the venv active:

```
cd backend
.venv\Scripts\activate
python -m app.agent https://example.com 5
```

The last argument is the page limit (default 20). The run prints the report, then `saved N findings (audit <id>)`. Findings are stored in `backend/data/findings.db` (SQLite).

### View saved findings

```
.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect('data/findings.db'); [print(r) for r in c.execute('select id, rule_id, wcag_criterion, severity, element from findings')]"
```

Or open `backend/data/findings.db` with the VS Code "SQLite Viewer" extension to browse the `findings` table.

### WCAG lookup

The auditor maps each issue to a WCAG 2.1 A/AA success criterion with the `lookup_wcag` tool (`app/wcag.py`). It embeds the 50 criteria locally with sentence-transformers (`all-MiniLM-L6-v2`, downloaded on first use, no API cost) and returns the closest few for a one-sentence issue description. `save_finding` rejects any criterion number that isn't one of the 50.

- `app/data/wcag21.json` is generated from the W3C quickref data: `python scripts/build_wcag_data.py`.
- `app/data/wcag21_failures.json` is hand-written: typical failures per criterion, embedded with the official wording so plain issue descriptions match.

Run the tests with `pytest`. The live agent test is skipped unless `RUN_LIVE=1` is set.
