@echo off
setlocal
set "APP_VENV=%USERPROFILE%\TLPVENV"
echo Removing virtual environment: %APP_VENV%
rmdir /s /q "%APP_VENV%"
echo Done. Run install_requirements.bat again.
pause
