@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"
if errorlevel 1 (
  echo.
  echo Shortcut creation failed. Check config.json and try again.
  pause
)
