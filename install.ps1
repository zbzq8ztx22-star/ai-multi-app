# AI Multi-App Installation Script for Windows
# Run this script from any directory; paths are resolved from the script location.

$ErrorActionPreference = "Stop"
$AppRoot = $PSScriptRoot
$ServerRoot = Join-Path $AppRoot "server"
$OpenExecutiveCore = Join-Path (Split-Path $AppRoot -Parent) "OpenExecutive\packages\core"
$ServerEnvExample = Join-Path $ServerRoot ".env.example"
$ServerEnv = Join-Path $ServerRoot ".env"
$AppVenv = Join-Path $AppRoot ".venv"
$AppPython = Join-Path $AppVenv "Scripts\python.exe"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host $Description -ForegroundColor Yellow
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

Write-Host "=== AI Multi-App Installation ===" -ForegroundColor Cyan
Write-Host "AI Multi-App: $AppRoot"
Write-Host "OpenExecutive core: $OpenExecutiveCore"
Write-Host ""

if (-not (Test-Path -LiteralPath $OpenExecutiveCore -PathType Container)) {
    throw "OpenExecutive core was not found at '$OpenExecutiveCore'. Place ai-multi-app and OpenExecutive beside each other under the same GitHub directory."
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.11 or newer and ensure it is on PATH."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm.cmd was not found. Install Node.js and ensure npm is on PATH."
}

Invoke-CheckedCommand "Checking Python installation..." { python --version }
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.11 or newer is required."
}

if (-not (Test-Path -LiteralPath $AppPython -PathType Leaf)) {
    Invoke-CheckedCommand "Creating application virtual environment..." { python -m venv $AppVenv }
}
Invoke-CheckedCommand "Installing uv in the application environment..." { & $AppPython -m pip install uv --quiet }

Push-Location $ServerRoot
try {
    Invoke-CheckedCommand "Installing Flask backend dependencies..." { & $AppPython -m pip install -r requirements-dev.txt --quiet }
} finally {
    Pop-Location
}

Push-Location $OpenExecutiveCore
try {
    Invoke-CheckedCommand "Installing OpenExecutive dependencies..." { & $AppPython -m uv sync }
} finally {
    Pop-Location
}

Push-Location $AppRoot
try {
    Invoke-CheckedCommand "Installing frontend dependencies..." { npm.cmd ci }
} finally {
    Pop-Location
}

if (Test-Path -LiteralPath $ServerEnv) {
    Write-Host "Keeping existing server\.env unchanged." -ForegroundColor Green
} else {
    if (-not (Test-Path -LiteralPath $ServerEnvExample -PathType Leaf)) {
        throw "Cannot create server\.env because '$ServerEnvExample' is missing."
    }
    Copy-Item -LiteralPath $ServerEnvExample -Destination $ServerEnv
    Write-Host "Created server\.env from server\.env.example." -ForegroundColor Green

    $envContent = Get-Content -LiteralPath $ServerEnv -Raw
    if ($envContent -match 'SECRET_KEY=change-me-in-production') {
        $chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_+-='.ToCharArray()
        $secret = -join ($chars | Get-Random -Count 32)
        $envContent = $envContent -replace 'SECRET_KEY=change-me-in-production', "SECRET_KEY=$secret"
        Set-Content -LiteralPath $ServerEnv -Value $envContent -NoNewline
        Write-Host "Generated a SECRET_KEY in server\.env." -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "=== Installation Complete ===" -ForegroundColor Green
Write-Host "No OpenExecutive .env file or secret was created or overwritten." -ForegroundColor Yellow
Write-Host "Set BACKEND_SHARED_SECRET in OpenExecutive and set OPENEXECUTIVE_API_KEY in server\.env to the same secret value." -ForegroundColor Yellow
Write-Host ""
Write-Host "Start these three development processes in separate PowerShell terminals:" -ForegroundColor Cyan
Write-Host "1. OpenExecutive (8000): Set-Location '$OpenExecutiveCore'; .\.venv\Scripts\python.exe -m uvicorn openexecutive.api.main:app --reload --port 8000"
Write-Host "2. Flask (5000): Set-Location '$ServerRoot'; & '$AppPython' app.py"
Write-Host "3. Vite (3000): Set-Location '$AppRoot'; npm.cmd run dev"
Write-Host "Then open http://localhost:3000 in your browser." -ForegroundColor Cyan
