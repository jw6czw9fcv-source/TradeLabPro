@echo off
setlocal
cd /d %~dp0

set "APP_VENV=%USERPROFILE%\TLPVENV"

if not exist "%APP_VENV%\Scripts\python.exe" (
    call install_requirements.bat
)

if not exist "%APP_VENV%\Scripts\python.exe" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName PresentationFramework;[System.Windows.MessageBox]::Show('Virtual environment was not found. Run install_requirements.bat first.','TradeLab Pro Error')"
    exit /b 1
)

REM launch_tradelab.py itself verifies/auto-installs any missing packages
REM (ensure_dependencies()) before importing the app, so every launcher
REM that runs it - this one, run_tradelab_console.bat, or the VBS shortcut -
REM is protected the same way, in one place, instead of each .bat needing
REM to remember to check_install.py separately.
if exist "%APP_VENV%\Scripts\pythonw.exe" (
    start "" "%APP_VENV%\Scripts\pythonw.exe" "%~dp0launch_tradelab.py"
) else (
    start "" "%APP_VENV%\Scripts\python.exe" "%~dp0launch_tradelab.py"
)
exit /b 0
