# AI Multi-App — Agent Rules

## Project overview
React + Vite frontend with Flask + SQLite backend. Business suite (payroll, tax, accounting, inventory) with optional OpenExecutive AI integration.

## Tech stack
- **Frontend:** React 18 + Vite 8 + Tailwind CSS + lucide-react
- **Backend:** Flask + SQLite + Python 3.11+
- **AI:** OpenExecutive (FastAPI, optional, port 8000)
- **Auth:** Flask sessions with signed cookies, roles `user` and `admin`
- **Tests:** pytest (461 tests)

## Build & test commands
- **Frontend build:** `npm run build` (from repo root)
- **Frontend dev:** `npm run dev` (serves localhost:3000, proxies /api to Flask :5000)
- **Backend:** `python app.py` (from `server/`)
- **Tests:** `pytest` (from `server/`)

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

## Dev credentials (development only)
- Username: `admin`
- Password: `admin123`
- Never commit real secrets. `server/.env` is gitignored.

## Communication
- Prefer Spanish for all communication with the user.
- Be concise and direct.

## Workflow
- Always run `npm run build` after frontend changes before considering done
- Run `pytest` from `server/` after backend changes
- Use Devin co-author trailer on commits
- Do not push unless explicitly asked
- Ask before destructive operations (force-push, branch deletion, history rewrite)
