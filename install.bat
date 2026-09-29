@echo off
rem IVAR SMP installer: sets up Python, ExifTool and Ollama in this folder. Safe to run again (repairs and updates).
rem Options: -Yes (no questions)  -ClaudeOnly (no local model, use the Claude API)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
if errorlevel 1 (
  echo.
  echo Install failed. See install.log in this folder.
  pause
  exit /b 1
)
if "%~1"=="" pause
