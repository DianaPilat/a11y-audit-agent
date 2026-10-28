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
