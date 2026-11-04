@echo off
setlocal EnableDelayedExpansion
title Facebook Contest Validator
cd /d "%~dp0"

set "CPU_ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "CPU_ARCH=%PROCESSOR_ARCHITEW6432%"

if exist ".venv\Scripts\pythonw.exe" (
    if not exist "Facebook Contest Validator.exe" (
        ".venv\Scripts\python.exe" "scripts\windows_setup_helper.py" >nul 2>nul
    )
    if /I "%~1"=="--no-launch" exit /b 0
    start "" ".venv\Scripts\pythonw.exe" "main.py"
    exit /b 0
)

echo ============================================================================
echo   Facebook Contest Validator ^& Live Lottery Prep (Windows Desktop Edition)
echo   Processor Architecture: %CPU_ARCH%
echo ============================================================================

echo [1/4] Checking Python 3 installation...
set "PY_CMD="
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 --version >nul 2>nul
    if !ERRORLEVEL! EQU 0 set "PY_CMD=py -3"
)

if "%PY_CMD%"=="" (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        python --version >nul 2>nul
        if !ERRORLEVEL! EQU 0 set "PY_CMD=python"
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] Python 3.10+ is required on this Windows PC.
    echo         Download Python from: https://www.python.org/downloads/windows/
    echo         Make sure to check "Add python.exe to PATH" during installation,
    echo         then double-click Start_Facebook_Contest_Validator.cmd again.
    pause
    exit /b 1
)

echo [2/4] Creating native %CPU_ARCH% virtual environment (.venv)...
%PY_CMD% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [3/4] Installing official PySide6 GUI ^& Contest Validator packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo [4/4] Generating local native "Facebook Contest Validator.exe" launcher...
".venv\Scripts\python.exe" "scripts\windows_setup_helper.py"

if /I "%~1"=="--no-launch" exit /b 0
echo [DONE] Launching Facebook Contest Validator...
start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0
