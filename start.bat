@echo off
rem IVAR SMP: double-click to start (the first start installs everything). Drag a folder onto it to open that folder.
cd /d "%~dp0"
title IVAR SMP
if not exist ".venv\Scripts\python.exe" (
  echo IVAR SMP isn't installed yet: running the installer first.
  set "SMP_FROM_START=1"
  call "%~dp0install.bat" || exit /b 1
)
".venv\Scripts\python.exe" -m smp %*
if errorlevel 1 pause
