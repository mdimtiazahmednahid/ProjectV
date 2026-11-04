#!/usr/bin/env python3
"""
Windows Post-Setup Helper (runs locally on the user's Windows PC inside `.venv`).
Because this script creates `Facebook Contest Validator.exe` locally on the Windows PC
using Python's official unmodified `distlib` launcher stub pointing directly to
`.venv\\Scripts\\pythonw.exe`:
  1. The generated `.exe` has NO internet Mark-of-the-Web (`Zone.Identifier` stream).
  2. The PE binary is 100% unmodified from Python's official `pip._vendor.distlib` (valid PE checksum).
  3. It invokes the Authenticode-signed `.venv\\Scripts\\pythonw.exe` directly (no `wscript`, no `.vbs`, no `powershell`).
"""
import io
import os
import platform
import zipfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _clear_zone_identifiers(root_dir: str) -> None:
    """Removes NTFS Zone.Identifier (Mark-of-the-Web) streams from extracted files on Windows."""
    if os.name != "nt":
        return
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for fname in filenames:
            zone_stream = os.path.join(dirpath, fname) + ":Zone.Identifier"
            try:
                if os.path.exists(zone_stream):
                    os.remove(zone_stream)
            except OSError:
                pass


def create_local_windows_exe() -> None:
    _clear_zone_identifiers(PROJECT_ROOT)

    try:
        from pip._vendor.distlib import scripts as distlib_scripts
    except ImportError:
        return

    distlib_dir = os.path.dirname(distlib_scripts.__file__)
    machine = (
        os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
        or platform.machine()
        or ""
    ).lower()

    if "arm" in machine or "aarch64" in machine:
        stub_name = "w64-arm.exe"
    elif "64" in machine:
        stub_name = "w64.exe"
    else:
        stub_name = "w32.exe"

    stub_path = os.path.join(distlib_dir, stub_name)
    if not os.path.isfile(stub_path):
        stub_path = os.path.join(distlib_dir, "w32.exe")
    if not os.path.isfile(stub_path):
        return

    # Use 100% unmodified official distlib PE bytes (preserves exact PE header checksum!)
    with open(stub_path, "rb") as f:
        pe_bytes = f.read()

    # Standard Python relative launcher shebang -> points directly to PSF-signed pythonw.exe
    shebang = b'#!"<launcher_dir>\\.venv\\Scripts\\pythonw.exe"\r\n'

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

    out_exe = os.path.join(PROJECT_ROOT, "Facebook Contest Validator.exe")
    with open(out_exe, "wb") as f:
        f.write(pe_bytes)
        f.write(shebang)
        f.write(zip_buf.getvalue())

    print(f"[OK] Created local native launcher: {out_exe} ({stub_name})")


if __name__ == "__main__":
    create_local_windows_exe()

