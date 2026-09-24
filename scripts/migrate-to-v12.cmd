@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0migrate_to_v12.ps1" -InstallDirectory "%~dp0"
