@echo off
rem IVAR SMP: get the latest version (when this folder is a git clone) and repair the install.
cd /d "%~dp0"
if exist ".git" (
  git pull --ff-only || echo Could not update from git; repairing the current version instead.
) else (
  echo This folder isn't a git clone: download the latest ZIP to update. Repairing the current install.
)
call "%~dp0install.bat" -Yes
pause
