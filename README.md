# AI Multi-App

AI Multi-App provides real chat, vision, code generation, and document analysis through a Flask bridge to OpenExecutive, plus a business suite (payroll, personal tax estimates, and double-entry accounting) backed by SQLite. The frontend is built with Vite and React.

## Status

The chat, vision, code, and document flows have been stabilized for real OpenExecutive-backed responses:

- **Chat** sends conversational requests to OpenExecutive.
- **Vision** submits uploaded images for model analysis.
- **Code** generates code from a language and natural-language request.
- **Documents** extracts supported uploads and requests analysis or summaries.

The business suite is implemented and works independently of OpenExecutive:

- **Payroll** — employees, pay periods, payslip calculation with YTD and W-4 adjustments, reports, CSV export, and an OpenExecutive-backed assistant.
- **Personal tax** — taxpayer records and personal tax-return estimates using versioned 2025 federal rules.
- **Accounting** — business-scoped double-entry accounting with chart of accounts, journal entries, contacts, invoices, payments, expenses, trial balance, general ledger, Profit & Loss, Balance Sheet, and a corporate tax estimate.

All business data is business-scoped and protected by session authentication.

## Repository layout

The repositories must be sibling directories under the same `GitHub` directory:

```text
GitHub\
├── ai-multi-app\
└── OpenExecutive\
    └── packages\
        └── core\
```

From the AI Multi-App root, OpenExecutive core is therefore `..\OpenExecutive\packages\core`.

## Prerequisites

- Python 3.11+
- Node.js and npm
- PowerShell
- The OpenExecutive repository in the sibling layout above
- Provider credentials required by OpenExecutive

Keep all real credentials and shared secrets in local `.env` files. Do not commit them.

## Windows installation

From any PowerShell working directory, invoke the installer by its path. From the AI Multi-App root:

```powershell
.\install.ps1
```

The installer resolves paths from its own `$PSScriptRoot`, not from the shell's current directory. It:

- creates an isolated `.venv` and installs the Flask development requirements;
- runs `uv sync` in `..\OpenExecutive\packages\core`;
- installs locked frontend dependencies with `npm.cmd ci`;
- copies `server\.env.example` to `server\.env` only when `server\.env` is absent; and
- never creates or overwrites an OpenExecutive `.env` or writes a placeholder credential.

Existing `.env` files are left unchanged.

## Manual setup

Run these commands from the `ai-multi-app` root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install uv
.\.venv\Scripts\python.exe -m pip install -r .\server\requirements-dev.txt

Push-Location ..\OpenExecutive\packages\core
..\..\..\ai-multi-app\.venv\Scripts\python.exe -m uv sync
Pop-Location

npm.cmd ci

if (-not (Test-Path .\server\.env)) {
    Copy-Item .\server\.env.example .\server\.env
}
```

Configure OpenExecutive according to its own documentation and provider requirements. Do not use example text as a real credential.

### Shared-secret configuration

The Flask bridge sends `OPENEXECUTIVE_API_KEY` to OpenExecutive. OpenExecutive validates that value against its `BACKEND_SHARED_SECRET`; these two variables are different names for the same shared secret on opposite sides of the connection:

```text
OpenExecutive:  BACKEND_SHARED_SECRET=<one private generated value>
ai-multi-app:   OPENEXECUTIVE_API_KEY=<the exact same value>
```

Set `BACKEND_SHARED_SECRET` in the environment file used by OpenExecutive core. Set the matching value in `ai-multi-app\server\.env`. Generate a strong private value locally, never paste it into documentation, and never commit either `.env` file.

The backend configuration also includes:

```text
OPENEXECUTIVE_API_URL=http://localhost:8000
OPENEXECUTIVE_API_KEY=
SECRET_KEY=change-me-in-production
DEFAULT_ADMIN_PASSWORD=
SESSION_COOKIE_SAMESITE=Lax
SESSION_COOKIE_SECURE=1
```

`SESSION_COOKIE_SAMESITE` controls the SameSite attribute on the session cookie (`Lax` by default). `SESSION_COOKIE_SECURE` marks the cookie Secure so it is only sent over HTTPS; set it to `0` only for local development over plain HTTP.

A blank key is only an unconfigured example; it is not a real secret.
`SECRET_KEY` is required; it signs Flask session cookies. Set `DEFAULT_ADMIN_PASSWORD` to create an `admin` user on startup.

## Run in development

Development uses three separate long-running processes. Open three PowerShell terminals.

### 1. OpenExecutive — port 8000

From `ai-multi-app`:

```powershell
Set-Location ..\OpenExecutive\packages\core
.\.venv\Scripts\python.exe -m uvicorn openexecutive.api.main:app --reload --port 8000
```

### 2. Flask API — port 5000

From `ai-multi-app`:

```powershell
Set-Location .\server
& ..\.venv\Scripts\python.exe app.py
```

### 3. Vite frontend — port 3000

From `ai-multi-app`:

```powershell
npm.cmd run dev
```

Open `http://localhost:3000`. Vite serves the frontend, Flask serves the application API on `http://localhost:5000`, and Flask calls OpenExecutive on `http://localhost:8000`.

## Usage

### Chat

Enter a message and send it to receive a real OpenExecutive-backed response.

### Vision

Upload an image and request analysis. Supported image data is forwarded through the backend to the model flow.

### Code generation

Choose a language, describe the desired result, and generate code through OpenExecutive.

### Document analysis

Upload a supported document and request analysis or a summary. Uploads are limited to 16 MB and are handled by the Flask backend.

### Payroll

Manage employees (hourly or salary, W-4 allowances, dependents), create pay periods, calculate payslips with YTD and W-4 adjustments, view payslip details, print payslips, run payroll reports, and export CSV. An OpenExecutive-backed assistant answers payroll questions. Payroll routes require login; management routes require an admin role.

### Personal tax

Create taxpayers and personal tax returns. The calculator applies 2025 federal rules: total income, AGI, standard vs. itemized deduction, taxable income, progressive federal tax, federal refund/balance, and state refund/balance. Estimates only — not legal or tax advice.

### Accounting

Create businesses, a chart of accounts (asset, liability, equity, revenue, expense), and journal entries (draft or posted). Posted entries drive the trial balance, general ledger, Profit & Loss, Balance Sheet, and the corporate tax estimate. Contacts (customers/vendors), invoices, payments, and expenses generate balanced journal entries automatically. Reports support date-range filters and are business-scoped.

## API endpoints

Core AI flows:

- `POST /api/chat` — chat requests
- `POST /api/vision` — image analysis
- `POST /api/code` — code generation
- `POST /api/docs` — document analysis
- `GET /api/health` — backend and OpenExecutive connection status

Auth:

- `POST /api/auth/register` — register a user (admin bootstrap)
- `POST /api/auth/login` — start a session
- `POST /api/auth/logout` — end a session
- `GET /api/auth/me` — current session user

Entities:

- `GET /api/entities/taxpayers` / `POST /api/entities/taxpayers`
- `GET /api/entities/businesses` / `POST /api/entities/businesses`

Payroll:

- `GET/POST /api/payroll/employees`
- `GET/POST /api/payroll/pay-periods`
- `POST /api/payroll/payslips/calculate`
- `GET /api/payroll/payslips`
- `GET /api/payroll/reports/summary`
- `GET /api/payroll/reports/export.csv`
- `POST /api/payroll/assistant`

Personal tax:

- `GET/POST /api/tax/returns`
- `PUT /api/tax/returns/:id`

Accounting:

- `GET/POST /api/accounting/accounts`
- `GET/POST /api/accounting/entries`
- `GET /api/accounting/trial-balance`
- `GET /api/accounting/ledger`
- `GET/POST /api/accounting/contacts`
- `GET/POST /api/accounting/invoices`
- `POST /api/accounting/payments`
- `GET/POST /api/accounting/expenses`
- `GET /api/accounting/reports/profit-loss`
- `GET /api/accounting/reports/balance-sheet`
- `GET /api/accounting/reports/corporate-tax`

## Troubleshooting

### OpenExecutive is unavailable

- Confirm the sibling core path is `..\OpenExecutive\packages\core`.
- Confirm OpenExecutive is listening on port 8000.
- Confirm its provider credentials are configured locally.
- Confirm `BACKEND_SHARED_SECRET` exactly matches `OPENEXECUTIVE_API_KEY` in `server\.env`.
- The payroll, tax, and accounting modules work without OpenExecutive; only the chat, vision, code, document, and payroll-assistant flows depend on it.

### Flask cannot connect

- Start OpenExecutive before making AI requests.
- Confirm `OPENEXECUTIVE_API_URL=http://localhost:8000` in `server\.env`.
- Confirm Flask is running on port 5000.

### The browser cannot load the app

- Confirm Vite is running on port 3000.
- Open `http://localhost:3000`, not the Flask port.

## License

MIT
