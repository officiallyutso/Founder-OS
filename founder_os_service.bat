@echo off
REM ============================================================
REM  Founder OS - unattended 24/7 service (Windows)
REM  Auto-restarts on crash. Launched by Task Scheduler at logon
REM  (via start_hidden.vbs, so no console window appears).
REM  Do NOT also run founder_os.bat at the same time, or two
REM  bots will poll the same token and Telegram will error (409).
REM ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py) || (set PY=python)

if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

if not exist ".env" (
    echo [error] No .env file found. Copy .env.example to .env and fill it in.
    exit /b 1
)

:loop
echo [%date% %time%] starting Founder OS...
".venv\Scripts\python.exe" main.py
echo [%date% %time%] exited (code %errorlevel%). Restarting in 10s...
timeout /t 10 /nobreak >nul
goto loop
