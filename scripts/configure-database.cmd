@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure_database.ps1"
if errorlevel 1 (
  echo.
  echo Configuration failed. Select the folder that directly contains both SQLite files and templates.
  pause
  exit /b 1
)
echo.
echo Configuration completed successfully.
pause
