#!/usr/bin/env python3
"""
Builds the Universal Multi-Processor Windows `.EXE` Distribution Package for
Facebook Contest Validator & Live Lottery Prep:
  - Generates native Windows GUI executables (`.exe` with SUBSYSTEM_WINDOWS_GUI
    and custom 32-bit ARGB `AppIcon` embedded directly in the PE `.rsrc` table):
      1. `Facebook Contest Validator.exe` (Universal x86/x64/ARM64 Windows GUI EXE)
      2. `Facebook Contest Validator (64-bit Intel-AMD).exe` (Native x86_64 PE32+ GUI EXE)
      3. `Facebook Contest Validator (ARM64).exe` (Native ARM64 PE32+ GUI EXE)
  - Supports Intel (Core i3/i5/i7/i9/Xeon x64 & x86), AMD (Ryzen/Athlon x64),
    and Windows on ARM (Snapdragon ARM64) on Windows 10 & Windows 11.
  - Packages everything into `/Users/MacBookPro/Downloads/ShareExtractor-main 2/Facebook_Contest_Validator_Windows_All_Processors.zip`.
"""
import io
import os
import shutil
import struct
import zipfile

WORKSPACE_ROOT = "/Users/MacBookPro/Downloads/ShareExtractor-main 2"
PROJECT_ROOT = os.path.join(WORKSPACE_ROOT, "facebook_share_collector")
ZIP_OUTPUT_PATH = os.path.join(
    WORKSPACE_ROOT, "Facebook_Contest_Validator_Windows_All_Processors.zip"
)
DISTLIB_DIR = os.path.join(
    PROJECT_ROOT,
    ".venv",
    "lib",
    "python3.14",
    "site-packages",
    "pip",
    "_vendor",
    "distlib",
)


def _create_base_qimage():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import (
        QColor,
        QFont,
        QGuiApplication,
        QImage,
        QLinearGradient,
        QPainter,
        QPen,
    )

    _app = QGuiApplication.instance() or QGuiApplication([])
    size = 512
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)

    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#1877F2"))
    grad.setColorAt(0.55, QColor("#1E40AF"))
    grad.setColorAt(1.0, QColor("#0F172A"))

    p.setPen(QPen(QColor("#60A5FA"), 10))
    p.setBrush(grad)
    margin = 24
    p.drawRoundedRect(
        margin, margin, size - 2 * margin, size - 2 * margin, 110, 110
    )

    wheel_grad = QLinearGradient(120, 120, 392, 392)
    wheel_grad.setColorAt(0.0, QColor("#10B981"))
    wheel_grad.setColorAt(1.0, QColor("#059669"))
    p.setPen(QPen(QColor("#FBBF24"), 12))
    p.setBrush(wheel_grad)
    p.drawEllipse(QPointF(size / 2, size / 2), 145, 145)

    p.setPen(QPen(QColor("#FFFFFF"), 24, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(195, 260, 240, 308)
    p.drawLine(240, 308, 330, 208)

    font = QFont("Arial", 28, QFont.Bold)
    p.setFont(font)
    p.setPen(QColor("#FDE68A"))
    p.drawText(0, 398, size, 60, Qt.AlignCenter, "3-ACTION")
    p.end()
    return img


def _qimage_to_win32_dib_icon(base_img, sz: int) -> bytes:
    """
    Converts a QImage into a Win32 RT_ICON 32-bit BGRA bottom-up DIB payload
    (BITMAPINFOHEADER + bottom-up BGRA XOR mask + 32-bit-aligned 1-bpp AND mask).
    Exact sizes:
      - 48x48 -> 9640 bytes
      - 32x32 -> 4264 bytes
      - 16x16 -> 1128 bytes
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    scaled = base_img.scaled(
        sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation
    ).convertToFormat(QImage.Format_ARGB32)

    xor_bytes = bytearray()
    and_row_stride = ((sz + 31) // 32) * 4
    and_bytes = bytearray()

    for y in range(sz - 1, -1, -1):
        and_row = bytearray(and_row_stride)
        for x in range(sz):
            pixel = scaled.pixel(x, y)
            b = pixel & 0xFF
            g = (pixel >> 8) & 0xFF
            r = (pixel >> 16) & 0xFF
            a = (pixel >> 24) & 0xFF
            xor_bytes.extend((b, g, r, a))
            if a < 16:
                byte_idx = x // 8
                bit_idx = 7 - (x % 8)
                and_row[byte_idx] |= 1 << bit_idx
        and_bytes.extend(and_row)

    bmi_header = struct.pack(
        "<IIIHHIIIIII",
        40,  # biSize
        sz,  # biWidth
        sz * 2,  # biHeight (XOR + AND combined height)
        1,  # biPlanes
        32,  # biBitCount
        0,  # biCompression (BI_RGB)
        len(xor_bytes) + len(and_bytes),  # biSizeImage
        0,
        0,
        0,
        0,
    )
    return bytes(bmi_header + xor_bytes + and_bytes)


def generate_windows_icons(resources_dir: str):
    """
    Writes `AppIcon.png`, `AppIcon.ico`, and returns the base QImage for PE `.rsrc` injection.
    """
    from PySide6.QtCore import QBuffer, QIODevice, Qt

    os.makedirs(resources_dir, exist_ok=True)
    img = _create_base_qimage()

    png_path = os.path.join(resources_dir, "AppIcon.png")
    img.save(png_path, "PNG")

    ico_sizes = [256, 128, 64, 48, 32, 16]
    png_payloads = []
    for sz in ico_sizes:
        scaled = img.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        scaled.save(buf, "PNG")
        png_payloads.append((sz, bytes(buf.data())))

    ico_path = os.path.join(resources_dir, "AppIcon.ico")
    with open(ico_path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(png_payloads)))
        offset = 6 + 16 * len(png_payloads)
        for sz, data in png_payloads:
            w_byte = 0 if sz >= 256 else sz
            h_byte = 0 if sz >= 256 else sz
            f.write(
                struct.pack(
                    "<BBBBHHII",
                    w_byte,
                    h_byte,
                    0,
                    0,
                    1,
                    32,
                    len(data),
                    offset,
                )
            )
            offset += len(data)
        for _sz, data in png_payloads:
            f.write(data)

    return img, ico_path


def build_native_windows_exe(stub_name: str, out_exe_path: str, base_img) -> None:
    """
    Builds a native Windows GUI `.exe` (`SUBSYSTEM_WINDOWS_GUI`) from the distlib PE stub
    (`w32.exe`, `w64.exe`, or `w64-arm.exe`), injects our custom 32-bit ARGB icons
    (48x48, 32x32, 16x16) directly into the PE `.rsrc` section, and appends the windowless
    launcher shebang + embedded `__main__.py` zip archive.
    """
    stub_path = os.path.join(DISTLIB_DIR, stub_name)
    pe_bytes = bytearray(open(stub_path, "rb").read())

    # Locate .rsrc section in PE header
    pe_off = struct.unpack_from("<I", pe_bytes, 0x3C)[0]
    _machine, num_sec = struct.unpack_from("<HH", pe_bytes, pe_off + 4)
    opt_size = struct.unpack_from("<H", pe_bytes, pe_off + 20)[0]
    sec_off = pe_off + 24 + opt_size

    rsrc_vaddr = None
    rsrc_rptr = None
    for i in range(num_sec):
        s = pe_bytes[sec_off + i * 40 : sec_off + (i + 1) * 40]
        sname = s[:8].rstrip(b"\x00").decode("ascii", errors="ignore")
        vsize, vaddr, rsize, rptr = struct.unpack_from("<IIII", s, 8)
        if sname == ".rsrc":
            rsrc_vaddr = vaddr
            rsrc_rptr = rptr
            break

    if rsrc_vaddr is not None and rsrc_rptr is not None:
        dib_48 = _qimage_to_win32_dib_icon(base_img, 48)
        dib_32 = _qimage_to_win32_dib_icon(base_img, 32)
        dib_16 = _qimage_to_win32_dib_icon(base_img, 16)
        assert len(dib_48) == 9640
        assert len(dib_32) == 4264
        assert len(dib_16) == 1128

        # Replace RT_ICON 5 (48x48), 6 (32x32), 7 (16x16) in-place
        for entry_off, dib_data in (
            (0x1F0, dib_48),
            (0x200, dib_32),
            (0x210, dib_16),
        ):
            drva, dsize = struct.unpack_from("<II", pe_bytes, rsrc_rptr + entry_off)
            assert dsize == len(dib_data)
            foff = rsrc_rptr + (drva - rsrc_vaddr)
            pe_bytes[foff : foff + dsize] = dib_data

        # Update RT_GROUP_ICON (entry 0x220) so all 7 slots reference our 32-bit icons (IDs 5, 6, 7)
        grp_rva, grp_size = struct.unpack_from("<II", pe_bytes, rsrc_rptr + 0x220)
        grp_foff = rsrc_rptr + (grp_rva - rsrc_vaddr)
        new_grp = bytearray(struct.pack("<HHH", 0, 1, 3))
        new_grp.extend(struct.pack("<BBBBHHIH", 48, 48, 0, 0, 1, 32, 9640, 5))
        new_grp.extend(struct.pack("<BBBBHHIH", 32, 32, 0, 0, 1, 32, 4264, 6))
        new_grp.extend(struct.pack("<BBBBHHIH", 16, 16, 0, 0, 1, 32, 1128, 7))
        new_grp.extend(b"\x00" * (grp_size - len(new_grp)))
        pe_bytes[grp_foff : grp_foff + grp_size] = new_grp

    # Windowless GUI shebang -> resolves built-in Win32 GUI wscript.exe via SearchPathW + PATHEXT (zero console flash!)
    shebang = b"#!/usr/bin/env wscript //B //E:vbscript Launch_Facebook_Contest_Validator.vbs\r\n"

    # Append valid zip archive containing __main__.py
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "__main__.py",
            "import os, runpy, sys\n"
            "app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))\n"
            "os.chdir(app_dir)\n"
            "if app_dir not in sys.path:\n"
            "    sys.path.insert(0, app_dir)\n"
            "runpy.run_path(os.path.join(app_dir, 'main.py'), run_name='__main__')\n",
        )

    with open(out_exe_path, "wb") as f:
        f.write(pe_bytes)
        f.write(shebang)
        f.write(zip_buf.getvalue())


VBS_LAUNCHER_CONTENT = r"""' ============================================================================
' Facebook Contest Validator & Live Lottery Prep - Windowless Windows Engine
' Invoked automatically by "Facebook Contest Validator.exe" (or directly).
' Compatible with ALL Windows Processors: Intel x64, AMD Ryzen x64, ARM64, x86
' ============================================================================
Option Explicit

Dim fso, shell, appDir, pythonwExe, mainPy, setupBat
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
If WScript.Arguments.Count > 0 Then
    Dim arg0
    arg0 = WScript.Arguments(0)
    If fso.FileExists(arg0) Then
        appDir = fso.GetParentFolderName(fso.GetAbsolutePathName(arg0))
    End If
End If

shell.CurrentDirectory = appDir

pythonwExe = appDir & "\.venv\Scripts\pythonw.exe"
mainPy = appDir & "\main.py"
setupBat = appDir & "\Setup_And_Launch_Windows.bat"

If fso.FileExists(pythonwExe) Then
    shell.Run Chr(34) & pythonwExe & Chr(34) & " " & Chr(34) & mainPy & Chr(34), 0, False
Else
    ' First-time run on this Windows PC: run processor-aware setup & launch
    shell.Run Chr(34) & setupBat & Chr(34), 1, False
End If
"""

SETUP_AND_LAUNCH_BAT = r"""@echo off
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
"""

BUILD_EXE_BAT = r"""@echo off
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
"""

PYINSTALLER_SPEC_CONTENT = r"""# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

added_files = [
    ('app/resources/AppIcon.ico', 'app/resources'),
    ('app/resources/AppIcon.png', 'app/resources'),
    ('config.yaml', '.'),
    ('browser_extension', 'browser_extension'),
]
if os.path.isdir('data'):
    added_files.append(('data', 'data'))
if os.path.isdir('bin'):
    added_files.append(('bin', 'bin'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'openpyxl',
        'sqlite3',
        'yaml',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.QtQuick',
        'PySide6.QtQml',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FacebookContestValidator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app/resources/AppIcon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FacebookContestValidator',
)
"""

WINDOWS_INSTALL_GUIDE = """================================================================================
FACEBOOK CONTEST VALIDATOR & LIVE LOTTERY PREP — WINDOWS .EXE EDITION
================================================================================

Included Native Windows Executables (.EXE):
  1. Facebook Contest Validator.exe
     -> Universal Windows GUI Executable (works on ALL Windows 10/11 processors:
        Intel Core/Xeon, AMD Ryzen/Athlon, 32-bit x86, and Snapdragon ARM64)
  2. Facebook Contest Validator (64-bit Intel-AMD).exe
     -> Native 64-bit x86_64 GUI Executable for Intel & AMD processors
  3. Facebook Contest Validator (ARM64).exe
     -> Native 64-bit ARM64 GUI Executable for Windows on ARM / Surface / Snapdragon

--------------------------------------------------------------------------------
HOW TO RUN ON ANY WINDOWS PC:
--------------------------------------------------------------------------------
1. Extract this ZIP folder anywhere on your Windows PC (e.g., Desktop).
2. Double-click:
      Facebook Contest Validator.exe
3. On your very first launch:
   - It automatically detects your Windows processor architecture (Intel/AMD x64,
     ARM64, or x86), sets up the native runtime in `.venv`, creates a
     "Facebook Contest Validator" shortcut on your Windows Desktop, and opens
     the app.
4. On every launch after that, double-clicking `Facebook Contest Validator.exe`
   (or the Desktop shortcut) opens the application immediately with zero console
   window.
================================================================================
"""


def write_text_crlf(path: str, content: str) -> None:
    normalized = content.replace("\r\n", "\n").replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(normalized)


def build_windows_distribution() -> None:
    resources_dir = os.path.join(PROJECT_ROOT, "app", "resources")
    base_img, ico_path = generate_windows_icons(resources_dir)
    print(f"[1/5] Generated Windows multi-resolution icon: {ico_path}")

    # Build the 3 native Windows .EXE binaries with embedded custom PE icons
    exe_targets = [
        ("w32.exe", "Facebook Contest Validator.exe"),
        ("w64.exe", "Facebook Contest Validator (64-bit Intel-AMD).exe"),
        ("w64-arm.exe", "Facebook Contest Validator (ARM64).exe"),
    ]
    for stub_name, exe_filename in exe_targets:
        out_exe = os.path.join(PROJECT_ROOT, exe_filename)
        build_native_windows_exe(stub_name, out_exe, base_img)
        # Also copy the universal .exe to the workspace root for easy visibility
        if exe_filename == "Facebook Contest Validator.exe":
            shutil.copy2(out_exe, os.path.join(WORKSPACE_ROOT, exe_filename))
        print(f"[2/5] Built native Windows GUI EXE: {out_exe}")

    vbs_path = os.path.join(PROJECT_ROOT, "Launch_Facebook_Contest_Validator.vbs")
    bat_path = os.path.join(PROJECT_ROOT, "Setup_And_Launch_Windows.bat")
    exe_bat_path = os.path.join(PROJECT_ROOT, "Build_Standalone_Windows_EXE.bat")
    spec_path = os.path.join(PROJECT_ROOT, "FacebookContestValidator.spec")
    guide_path = os.path.join(PROJECT_ROOT, "WINDOWS_INSTALL_GUIDE.txt")

    write_text_crlf(vbs_path, VBS_LAUNCHER_CONTENT)
    write_text_crlf(bat_path, SETUP_AND_LAUNCH_BAT)
    write_text_crlf(exe_bat_path, BUILD_EXE_BAT)
    write_text_crlf(spec_path, PYINSTALLER_SPEC_CONTENT)
    write_text_crlf(guide_path, WINDOWS_INSTALL_GUIDE)
    print("[3/5] Updated Windows engine scripts and guide.")

    for tag in ("windows-x64", "windows-arm64", "windows-x86"):
        bin_sub = os.path.join(PROJECT_ROOT, "bin", tag)
        os.makedirs(bin_sub, exist_ok=True)
        readme_bin = os.path.join(bin_sub, "README.txt")
        if not os.path.exists(readme_bin):
            write_text_crlf(
                readme_bin,
                f"Optional: Place Windows {tag} adb.exe, AdbWinApi.dll, and AdbWinUsbApi.dll here.\n"
                "If not placed here, the app automatically finds adb.exe from PATH or %LOCALAPPDATA%\\Android\\Sdk\\platform-tools.\n",
            )

    if os.path.exists(ZIP_OUTPUT_PATH):
        os.remove(ZIP_OUTPUT_PATH)

    root_folder_in_zip = "Facebook_Contest_Validator_Windows"
    exclude_dirs = {
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".git",
        "logs",
        "build",
        "dist",
        "browser_profile",
        "inspections",
    }
    exclude_exts = {".pyc", ".pyo", ".DS_Store"}

    print(f"[4/5] Packaging Windows .EXE distribution: {ZIP_OUTPUT_PATH}")
    with zipfile.ZipFile(ZIP_OUTPUT_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
            dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
            rel_dir = os.path.relpath(dirpath, PROJECT_ROOT)
            for fname in filenames:
                if fname in exclude_exts or os.path.splitext(fname)[1] in exclude_exts:
                    continue
                if fname.endswith("-wal") or fname.endswith("-shm"):
                    continue
                full_path = os.path.join(dirpath, fname)
                arcname = (
                    os.path.join(root_folder_in_zip, fname)
                    if rel_dir == "."
                    else os.path.join(root_folder_in_zip, rel_dir, fname)
                )
                zf.write(full_path, arcname)

    size_mb = os.path.getsize(ZIP_OUTPUT_PATH) / (1024 * 1024)
    print(f"[5/5] Done! Created {ZIP_OUTPUT_PATH} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    build_windows_distribution()
