# AI Multi-App — Agent Rules

## Project overview
React + Vite frontend with Flask + SQLite backend. Business suite (payroll, tax, accounting, inventory) with optional OpenExecutive AI integration.

## Tech stack
- **Frontend:** React 18 + Vite 8 + Tailwind CSS + lucide-react
- **Backend:** Flask + SQLite + Python 3.11+
- **AI:** OpenExecutive (FastAPI, optional, port 8000)
- **Auth:** Flask sessions with signed cookies. User roles: `viewer` and `admin`. Business-access roles: `owner`, `editor`, `viewer`.
- **Tests:** pytest

## Build & test commands
- **Frontend build:** `npm run build` (from repo root)
- **Frontend lint:** `npm run lint` (from repo root)
- **Frontend dev:** `npm run dev` (serves localhost:3000, proxies /api to Flask :5000)
- **Backend:** `python app.py` (from `server/`)
- **Tests:** `pytest` (from `server/`)
- **Backend lint/security:** `ruff check .` and `bandit -r . -x ./tests` (from `server/`)

## Visual design rules
- Light professional theme: indigo accent, gray-100 backgrounds, gray-50 cards
- Avoid pure white surfaces except for print output (`print:bg-white`)
- Do NOT use Tailwind custom shadow names with `@apply` — use direct CSS `box-shadow` instead
- Inter font, soft shadows, pastel status colors

## Architecture constraints
- Code Generation tab must remain removed from navigation in `src/App.jsx`
- `CodeGen.jsx` and `/api/code` endpoint stay in repo but are not exposed in the sidebar
- Business modules (payroll, tax, accounting) must work without OpenExecutive
- AI modules (chat, vision, docs) require OpenExecutive on port 8000
- All business data is isolated by `business_id`
- `server/accounting/service.py` is a facade: domain logic lives in `accounting/ledger.py`, `invoices.py`, `credits.py`, `expenses.py`, `purchase_orders.py`, `assets.py`, `periods.py`, `reconciliation.py`, `projects.py`, `reports.py`. Shared helpers and core ledger code live in `ledger.py`; new domain code goes in the matching module, not in `service.py`.

## Local credentials
- Never commit real secrets or credentials. `server/.env` is gitignored.
- For local development and tests, create temporary users through the register endpoint or the admin user-management UI with random passwords. Do not hardcode or share fixed local credentials.

## Communication
- Prefer Spanish for all communication with the user.
- Be concise and direct.

## Workflow & quality gates
- Run `pytest` from `server/` after backend changes.
- Run `npm run build` (and `npm run lint` when lint-relevant files change) after frontend changes.
- Do not merge a branch until CI is green: backend tests, frontend build, linting, static/security checks, dependency review.
- Do not ignore or silently resolve review findings — address them or explain why they are invalid.
- Use Devin co-author trailer on commits.
- Do not push unless explicitly asked.
- Ask before destructive operations (force-push, branch deletion, history rewrite).
