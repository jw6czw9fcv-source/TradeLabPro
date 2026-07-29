@echo off
setlocal
cd /d %~dp0

REM TradeLab Pro installer with SHORT virtual-environment path.
REM PySide6 can fail on Windows when the project is extracted in a long path
REM like Downloads\TradeLabPro_Phase1_Qt_baseline_fixed_installer\...

set "APP_VENV=%USERPROFILE%\TLPVENV"

 echo ========================================
 echo TradeLab Pro - Dependency Installer
 echo ========================================
 echo.
 echo Project folder: %CD%
 echo Virtual environment: %APP_VENV%
 echo.

 echo Checking Python...
 py -3 --version >nul 2>&1
 if errorlevel 1 (
     python --version >nul 2>&1
     if errorlevel 1 (
         echo ERROR: Python is not installed or not in PATH.
         echo Install Python 3.11 or 3.12 from python.org and check "Add Python to PATH".
         pause
         exit /b 1
     )
     set "PYTHON_CMD=python"
 ) else (
     set "PYTHON_CMD=py -3"
 )

 echo.
 echo Creating short-path virtual environment...
 if exist "%APP_VENV%\Scripts\python.exe" (
     echo Existing virtual environment found.
 ) else (
     %PYTHON_CMD% -m venv "%APP_VENV%"
     if errorlevel 1 (
         echo ERROR: Could not create virtual environment at %APP_VENV%.
         pause
         exit /b 1
     )
 )

 echo.
 echo Upgrading pip...
 "%APP_VENV%\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
 if errorlevel 1 (
     echo ERROR: pip upgrade failed.
     pause
     exit /b 1
 )

 echo.
 echo Installing packages. This can take several minutes...
 "%APP_VENV%\Scripts\python.exe" -m pip install --no-cache-dir -r requirements.txt
 if errorlevel 1 (
     echo.
     echo ERROR: Package installation failed.
     echo.
     echo Most likely fix:
     echo 1. Move this folder to C:\TradeLabPro
     echo 2. Run install_requirements.bat again
     echo.
     echo If PySide6 still fails, enable Windows long paths:
     echo https://pip.pypa.io/warnings/enable-long-paths
     pause
     exit /b 1
 )

 echo.
 echo Checking installation...
 "%APP_VENV%\Scripts\python.exe" check_install.py
 if errorlevel 1 (
     echo ERROR: Dependency check failed.
     pause
     exit /b 1
 )

 echo.
 echo Installation complete.
 echo You can now run run_tradelab.bat
 pause
