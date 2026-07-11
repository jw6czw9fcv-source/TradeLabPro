@echo off
setlocal
cd /d %~dp0
set "APP_VENV=%USERPROFILE%\TLPVENV"

if not exist "%APP_VENV%\Scripts\python.exe" (
    call install_requirements.bat
)

REM launch_tradelab.py itself now verifies/auto-installs missing packages
REM (see ensure_dependencies()), so this console launcher stays a thin
REM wrapper rather than duplicating that logic a third time.
"%APP_VENV%\Scripts\python.exe" launch_tradelab.py
pause
