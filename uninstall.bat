@echo off
rem IVAR SMP uninstaller: removes the programs, models and data (wherever the installer put them), the Python
rem environment and the shortcuts. A downloaded copy then deletes this folder too; a git clone keeps its code.
rem Options: -Yes (no questions)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\uninstall.ps1" %*
if errorlevel 2 goto removeapp
if errorlevel 1 (
  echo.
  echo Uninstall stopped.
  if "%~1"=="" pause
  exit /b 1
)
if "%~1"=="" pause
exit /b 0

:removeapp
rem last: leave this folder and delete it, this file too. (goto) ends the script; the rest of its line still runs.
set "APPDIR=%~dp0"
set "APPDIR=%APPDIR:~0,-1%"
cd /d "%TEMP%"
(goto) 2>nul & rmdir /s /q "%APPDIR%" & echo IVAR SMP is uninstalled. & if "%~1"=="" pause
