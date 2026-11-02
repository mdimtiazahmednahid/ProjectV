"""
Standalone Desktop App Builder for Facebook Contest Validator & Live Lottery Prep.
Supports:
  - macOS Apple Silicon (arm64)
  - macOS Intel (x86_64)
  - Windows 10 & Windows 11 (x64 / x86)

Automatically downloads & bundles Google's official standalone ADB platform-tools
into bin/ so end users need ZERO external setup (no Python, no Node.js, no Appium, no SDK).
"""

import os
import sys
import shutil
import zipfile
import urllib.request
import subprocess
from app.utils.platform_binaries import get_os_arch_info

PLATFORM_TOOLS_URLS = {
    "macos": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}


def download_and_bundle_adb(base_dir: str) -> str:
    info = get_os_arch_info()
    os_name = info["os"]
    url = PLATFORM_TOOLS_URLS.get(os_name)
    if not url:
        raise RuntimeError(f"Unsupported OS for ADB auto-bundle: {os_name}")

    target_bin_dir = os.path.join(base_dir, "bin", info["platform_tag"])
    os.makedirs(target_bin_dir, exist_ok=True)

    exe_name = "adb.exe" if info["is_windows"] else "adb"
    target_adb = os.path.join(target_bin_dir, exe_name)
    if os.path.isfile(target_adb):
        print(f"[✓] Bundled ADB already present at: {target_adb}")
        return target_bin_dir

    zip_path = os.path.join(base_dir, "bin", f"platform-tools-{os_name}.zip")
    print(f"[*] Downloading official Android platform-tools for {info['platform_tag']}...")
    urllib.request.urlretrieve(url, zip_path)

    extract_tmp = os.path.join(base_dir, "bin", "_tmp_pt")
    if os.path.exists(extract_tmp):
        shutil.rmtree(extract_tmp)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_tmp)

    pt_root = os.path.join(extract_tmp, "platform-tools")
    needed_files = ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"] if info["is_windows"] else ["adb"]

    for fname in needed_files:
        src = os.path.join(pt_root, fname)
        dst = os.path.join(target_bin_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            if not info["is_windows"]:
                os.chmod(dst, 0o755)

    shutil.rmtree(extract_tmp, ignore_errors=True)
    if os.path.exists(zip_path):
        os.remove(zip_path)

    print(f"[✓] Bundled standalone ADB into: {target_bin_dir}")
    return target_bin_dir


def build_executable():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    info = get_os_arch_info()
    app_name = f"FacebookContestValidator-{info['platform_tag']}"

    download_and_bundle_adb(base_dir)

    sep = ";" if info["is_windows"] else ":"
    add_data_bin = f"{os.path.join(base_dir, 'bin')}{sep}bin"
    add_data_cfg = f"{os.path.join(base_dir, 'config.yaml')}{sep}."

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        app_name,
        "--add-data",
        add_data_bin,
        "--add-data",
        add_data_cfg,
        os.path.join(base_dir, "run.py"),
    ]

    print(f"[*] Building standalone desktop application: {app_name}")
    subprocess.run(cmd, check=True, cwd=base_dir)
    print(f"[✓] Build complete! Check the 'dist/{app_name}' folder.")


if __name__ == "__main__":
    build_executable()

