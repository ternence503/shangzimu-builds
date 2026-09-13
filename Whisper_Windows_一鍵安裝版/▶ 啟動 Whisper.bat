@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%_internal\setup_and_run.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

if NOT "%EXIT_CODE%"=="0" (
  echo.
  echo Setup did not finish. Check connection, disk space and permissions, then run this launcher again.
  echo Detailed Chinese instructions and log location are shown above.
  pause
  exit /b %EXIT_CODE%
)

echo.
exit /b 0
