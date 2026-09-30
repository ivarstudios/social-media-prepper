@echo off
rem IVAR SMP installer: asks where the programs (Python, ExifTool, Ollama), the models and SMP's data go, then sets
rem them up. Safe to run again: it repairs, updates, and moves a folder you change.
rem Options: -Yes (no questions)  -ClaudeOnly (no local model, use the Claude API)
rem          -ToolsDir D:\x  -ModelsDir D:\x  -DataDir D:\x (the folders, without asking)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
if errorlevel 1 (
  echo.
  echo Install failed. See install.log in this folder.
  pause
  exit /b 1
)
rem no pause when start.bat ran it: the app starts next
if "%~1"=="" if not defined SMP_FROM_START pause
