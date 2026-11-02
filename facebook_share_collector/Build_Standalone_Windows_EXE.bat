@echo off
setlocal EnableDelayedExpansion
title Build Standalone Single-Folder EXE - Facebook Contest Validator
cd /d "%~dp0"

set "CPU_ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "CPU_ARCH=%PROCESSOR_ARCHITEW6432%"

echo ============================================================================
echo   Building Standalone Bundled Windows .EXE for Processor: %CPU_ARCH%
echo ============================================================================

if not exist ".venv\Scripts\python.exe" (
    call Setup_And_Launch_Windows.bat --no-launch
)

echo [1/2] Installing PyInstaller into .venv...
".venv\Scripts\python.exe" -m pip install pyinstaller

echo [2/2] Compiling standalone dist\FacebookContestValidator\FacebookContestValidator.exe...
".venv\Scripts\pyinstaller.exe" --noconfirm --clean FacebookContestValidator.spec

echo ============================================================================
echo [SUCCESS] Standalone Windows App compiled at:
echo   dist\FacebookContestValidator\FacebookContestValidator.exe
echo ============================================================================
pause
