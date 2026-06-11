@echo off
REM ============================================================
REM  Stop the Founder OS service: kills the restart loop first
REM  (so it won't relaunch) then the running bot process.
REM ============================================================
echo Stopping Founder OS...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object { $_.CommandLine -like '*founder_os_service.bat*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Done.
