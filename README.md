# AI Multi-App

AI Multi-App provides real chat, vision, code generation, and document analysis through a Flask bridge to OpenExecutive, with a Vite frontend.

## Status

The chat, vision, code, and document flows have been stabilized for real OpenExecutive-backed responses:

- **Chat** sends conversational requests to OpenExecutive.
- **Vision** submits uploaded images for model analysis.
- **Code** generates code from a language and natural-language request.
- **Documents** extracts supported uploads and requests analysis or summaries.

Payroll is the next planned feature. It is **not implemented yet**.

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

## API endpoints

- `POST /api/chat` — chat requests
- `POST /api/vision` — image analysis
- `POST /api/code` — code generation
- `POST /api/docs` — document analysis
- `GET /api/health` — backend and OpenExecutive connection status

## Troubleshooting

### OpenExecutive is unavailable

- Confirm the sibling core path is `..\OpenExecutive\packages\core`.
- Confirm OpenExecutive is listening on port 8000.
- Confirm its provider credentials are configured locally.
- Confirm `BACKEND_SHARED_SECRET` exactly matches `OPENEXECUTIVE_API_KEY` in `server\.env`.

### Flask cannot connect

- Start OpenExecutive before making AI requests.
- Confirm `OPENEXECUTIVE_API_URL=http://localhost:8000` in `server\.env`.
- Confirm Flask is running on port 5000.

### The browser cannot load the app

- Confirm Vite is running on port 3000.
- Open `http://localhost:3000`, not the Flask port.

## License

MIT
