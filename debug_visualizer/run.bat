@echo off
REM Debug Visualizer Launcher for Windows
REM This script starts the Flask dashboard for real-time agent monitoring

setlocal enabledelayedexpansion

echo.
echo ================================================================
echo   Asset Agent Debug Visualizer Launcher
echo ================================================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ or add it to PATH
    exit /b 1
)

REM Check if venv exists
if not exist "venv\" (
    echo WARNING: Virtual environment not found
    echo Creating venv...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install Flask if needed
echo Installing/checking Flask...
pip install -q Flask==2.3.0 Werkzeug==2.3.0

REM Check if agent_state.db exists
if not exist "agent_state.db" (
    echo.
    echo WARNING: agent_state.db not found
    echo Run the agent first: python main.py --run-id test-001
    echo.
)

REM Start the server
echo.
echo ================================================================
echo   Starting Debug Visualizer...
echo ================================================================
echo.
echo ^[OK^] Open browser: http://localhost:5000
echo ^[OK^] Monitoring: agent_state.db
echo.
echo Press Ctrl+C to stop
echo.

python debug_visualizer\server.py

pause
