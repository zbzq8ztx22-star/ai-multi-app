---
name: testing-payroll-local
description: Run local Windows login and payroll end-to-end checks with isolated SQLite data.
---

# Local payroll testing

## Devin Secrets Needed
- No external credentials are needed for isolated payroll tests. Generate a local SECRET_KEY and temporary test passwords; never commit them.
- Testing successful AI responses additionally requires a reachable OpenExecutive service and its OPENEXECUTIVE_API_KEY.

## Environment
- Install frontend dependencies with `npm ci` at the repository root.
- Use `C:\devin\python\python.exe -m pip install -r server/requirements.txt` for backend dependencies.
- Copy `server/.env.example` to `server/.env` only if absent. Supply a random SECRET_KEY, set SESSION_COOKIE_SECURE=0 for HTTP, and use a dedicated PAYROLL_DATABASE path outside the checkout.
- Launch the backend from `server`, normally with `python app.py`. If the embedded Python distribution excludes the working directory from imports, insert `.` in sys.path before importing app.
- Launch `npm run dev` at the root. Vite serves localhost:3000 and proxies `/api` to Flask localhost:5000; inspect vite.config.js if ports change.
- Use a fresh SQLite database. If DEFAULT_ADMIN_PASSWORD does not bootstrap the intended database, register the first admin through `/api/auth/register` before other users; create the viewer while authenticated as that admin.

## UI and API evidence
- Navigate Login -> Payroll -> Employees, Periods, Payslips, Reports. Open a payslip detail modal and download CSV to compare deduction and net-pay totals.
- For endpoints without UI controls, use same-origin fetch from the authenticated browser rather than extracting cookies into shell HTTP clients.
- Inspect employee_ytd in the isolated SQLite database for tax-year assertions not exposed by the UI.
- Test actual cross-origin PUT/DELETE preflights, not only Access-Control-Allow-Methods headers.
- Inspect actual Set-Cookie attributes without retaining cookie values.
- When OpenExecutive is intentionally unavailable, health/AI upstream 502/503 responses are expected; distinguish them from authentication 401 or authorization 403.
- Do not share the test database or raw browser session cookies as evidence.
