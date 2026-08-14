# PowerShell launcher for Debug Visualizer
# Run with: powershell -ExecutionPolicy Bypass -File debug_visualizer/run.ps1

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Asset Agent Debug Visualizer Launcher" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found. Please install Python 3.8+" -ForegroundColor Red
    exit 1
}

# Check venv
$venvPath = Join-Path $PSScriptRoot "..\venv"
if (-Not (Test-Path $venvPath)) {
    Write-Host "[WARN] Virtual environment not found, creating..." -ForegroundColor Yellow
    python -m venv $venvPath
}

# Activate venv
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
& $activateScript

# Install dependencies
Write-Host "[OK] Checking Flask..." -ForegroundColor Green
pip install -q Flask==2.3.0 Werkzeug==2.3.0

# Check database
$dbPath = Join-Path $PSScriptRoot "..\agent_state.db"
if (-Not (Test-Path $dbPath)) {
    Write-Host ""
    Write-Host "[WARN] agent_state.db not found" -ForegroundColor Yellow
    Write-Host "[WARN] Run the agent first: python main.py --run-id test-001" -ForegroundColor Yellow
    Write-Host ""
}

# Start server
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Starting Debug Visualizer..." -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[OK] Open browser: http://localhost:5000" -ForegroundColor Green
Write-Host "[OK] Monitoring: agent_state.db" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

python debug_visualizer\server.py
