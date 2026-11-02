@echo off
setlocal EnableDelayedExpansion
title Facebook Contest Validator - Windows Multi-Processor Setup ^& Launcher
cd /d "%~dp0"

REM ============================================================================
REM Detect Windows CPU Architecture (Intel/AMD x64, Qualcomm/Surface ARM64, x86)
REM ============================================================================
set "CPU_ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "CPU_ARCH=%PROCESSOR_ARCHITEW6432%"

echo ============================================================================
echo   Facebook Contest Validator ^& Live Lottery Prep (Windows Desktop Edition)
echo   Detected Processor Architecture: %CPU_ARCH%
echo ============================================================================

REM Fast path: if virtual environment already exists, launch windowlessly!
if exist ".venv\Scripts\pythonw.exe" (
    if /I "%~1"=="--no-launch" exit /b 0
    echo [OK] Launching Facebook Contest Validator...
    start "" ".venv\Scripts\pythonw.exe" "main.py"
    exit /b 0
)

echo [1/4] Checking Python installation for %CPU_ARCH%...
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
    echo [INFO] Python 3 not found. Attempting automatic installation via Windows Winget...
    where winget >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
        set "PY_CMD=python"
    ) else (
        echo [ERROR] Please install Python 3.10+ from https://www.python.org/downloads/windows/
        echo         Check "Add Python to PATH" during installation, then double-click
        echo         "Facebook Contest Validator.exe" again.
        pause
        exit /b 1
    )
)

echo [2/4] Creating native %CPU_ARCH% virtual environment (.venv)...
%PY_CMD% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [3/4] Installing native %CPU_ARCH% GUI ^& Contest dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo [4/4] Creating Desktop Shortcut ("Facebook Contest Validator")...
set "APP_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$appDir = $env:APP_DIR; " ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Facebook Contest Validator.lnk'); " ^
  "$s.TargetPath = Join-Path $appDir 'Facebook Contest Validator.exe'; " ^
  "$s.WorkingDirectory = $appDir; " ^
  "$s.IconLocation = (Join-Path $appDir 'Facebook Contest Validator.exe') + ',0'; " ^
  "$s.Description = 'Facebook 3-Action Contest Validator & Live Lottery Draw'; " ^
  "$s.Save()" >nul 2>nul

if /I "%~1"=="--no-launch" exit /b 0
echo [DONE] Launching Facebook Contest Validator...
start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0
