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

## Audit a page

One-time browser install, then run an audit; results are saved as JSON under `backend/data/results/`.

```
playwright install chromium
python -m app.browser https://example.com
```

## Run the agent

The agent connects to the `a11y-browser` MCP server, writes a plain-language report for one page, and saves each issue with the `save_finding` tool (uses the Claude API, a few cents per run).

Run it from the `backend` folder with the venv active:

```
cd backend
.venv\Scripts\activate
python -m app.agent https://example.com
```

The run prints the report, then `saved N findings (audit <id>)`. Findings are stored in `backend/data/findings.db` (SQLite).

### View saved findings

```
.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect('data/findings.db'); [print(r) for r in c.execute('select id, rule_id, wcag_criterion, severity, element from findings')]"
```

Or open `backend/data/findings.db` with the VS Code "SQLite Viewer" extension to browse the `findings` table.

Run the tests with `pytest`. The live agent test is skipped unless `RUN_LIVE=1` is set.
