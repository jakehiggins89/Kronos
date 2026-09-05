@echo off
cd /d "%~dp0..\.."
REM Potter v3 research scan: prints today's triggers under a research banner.
REM Not a trade signal. Does not touch the retired scanner or its schedule.
REM Run after 16:00 ET so the reading candle is complete.
if not exist "venv\Scripts\python.exe" (
  echo venv\Scripts\python.exe not found; run install_deps.bat first
  exit /b 1
)
if not exist "scanner\logs" mkdir "scanner\logs"
set "LAST=%TEMP%\potter_v3_scan_last.txt"
"venv\Scripts\python.exe" -m scanner.potter_v3 --mode scan > "%LAST%" 2>&1
set EXITCODE=%ERRORLEVEL%
type "%LAST%"
echo ===== %DATE% %TIME% exit=%EXITCODE% >> "scanner\logs\potter_v3_scan.log"
type "%LAST%" >> "scanner\logs\potter_v3_scan.log"
exit /b %EXITCODE%
