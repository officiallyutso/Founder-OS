@echo off
REM ============================================================
REM  Founder OS - one-click launcher (Windows)
REM  First run: creates venv + installs deps.
REM  Every run after: just boots the whole system.
REM ============================================================
setlocal
cd /d "%~dp0"

REM --- pick a python launcher ---
where py >nul 2>nul && (set PY=py) || (set PY=python)

REM --- create venv only if it doesn't exist ---
if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    %PY% -m venv .venv
    echo [setup] Installing dependencies ^(first run only^)...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

REM --- sanity check: .env must exist ---
if not exist ".env" (
    echo [error] No .env file found. Copy .env.example to .env and fill it in.
    pause
    exit /b 1
)

echo [run] Starting Founder OS...
".venv\Scripts\python.exe" main.py

REM keep window open if it crashes so you can read the error
if errorlevel 1 pause
endlocal
