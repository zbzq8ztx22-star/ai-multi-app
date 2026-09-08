# AI Multi-App Installation Script for Windows
# This script installs all dependencies and sets up the application

Write-Host "=== AI Multi-App Installation ===" -ForegroundColor Cyan
Write-Host ""

# Check Python installation
Write-Host "Checking Python installation..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "Python found: $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "ERROR: Python not found. Please install Python 3.11+ from https://www.python.org/" -ForegroundColor Red
    exit 1
}

# Install uv package manager
Write-Host ""
Write-Host "Installing uv package manager..." -ForegroundColor Yellow
python -m pip install uv --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "uv installed successfully" -ForegroundColor Green
} else {
    Write-Host "ERROR: Failed to install uv" -ForegroundColor Red
    exit 1
}

# Install AI Multi-App dependencies
Write-Host ""
Write-Host "Installing AI Multi-App dependencies..." -ForegroundColor Yellow
cd server
python -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "AI Multi-App dependencies installed" -ForegroundColor Green
} else {
    Write-Host "ERROR: Failed to install AI Multi-App dependencies" -ForegroundColor Red
    exit 1
}
cd ..

# Setup OpenExecutive
Write-Host ""
Write-Host "Setting up OpenExecutive..." -ForegroundColor Yellow
cd OpenExecutive\packages\core

# Install dependencies with uv
python -m uv sync
if ($LASTEXITCODE -eq 0) {
    Write-Host "OpenExecutive dependencies installed" -ForegroundColor Green
} else {
    Write-Host "ERROR: Failed to install OpenExecutive dependencies" -ForegroundColor Red
    exit 1
}

# Install additional timezone libraries
.venv\Scripts\python.exe -m pip install pytz tzdata --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "Timezone libraries installed" -ForegroundColor Green
} else {
    Write-Host "WARNING: Failed to install timezone libraries" -ForegroundColor Yellow
}

cd ..\..\..

# Create OpenExecutive .env file
Write-Host ""
Write-Host "Creating OpenExecutive configuration..." -ForegroundColor Yellow
$envContent = @"
ANTHROPIC_API_KEY=sk-ant-placeholder
EXEC_EMAIL_ADDRESS=exec@example.com
"@
[System.IO.File]::WriteAllLines("OpenExecutive\.env", $envContent)
Write-Host "OpenExecutive .env file created" -ForegroundColor Green

# Create AI Multi-App .env file
Write-Host ""
Write-Host "Creating AI Multi-App configuration..." -ForegroundColor Yellow
$aiEnvContent = @"
OPENEXECUTIVE_API_URL=http://localhost:8000
OPENEXECUTIVE_API_KEY=
"@
[System.IO.File]::WriteAllLines("server\.env", $aiEnvContent)
Write-Host "AI Multi-App .env file created" -ForegroundColor Green

Write-Host ""
Write-Host "=== Installation Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "To start the applications:" -ForegroundColor Cyan
Write-Host "1. Start OpenExecutive: cd OpenExecutive\packages\core; .venv\Scripts\python.exe -m uvicorn openexecutive.api.main:app --reload --port 8000" -ForegroundColor White
Write-Host "2. Start AI Multi-App: cd server; python app.py" -ForegroundColor White
Write-Host ""
Write-Host "Then open http://localhost:5000 in your browser" -ForegroundColor Cyan
Write-Host ""
Write-Host "IMPORTANT: To enable real AI responses, edit OpenExecutive\.env and add your Anthropic API key" -ForegroundColor Yellow
