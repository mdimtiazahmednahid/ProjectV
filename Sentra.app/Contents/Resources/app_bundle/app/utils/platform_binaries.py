import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from typing import Any, Dict

logger = logging.getLogger(__name__)

PLATFORM_TOOLS_URLS = {
    "windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "macos": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}

_adb_download_lock = threading.Lock()
_adb_download_attempted = False


def get_os_arch_info() -> Dict[str, Any]:
    """
    Returns normalized OS and CPU architecture info for macOS (Intel & Apple Silicon),
    Windows (10/11 x64, ARM64, & x86), and Linux.
    """
    sys_name = platform.system().lower()
    machine = (
        os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
        or platform.machine()
        or ""
    ).lower()

    if sys_name == "darwin":
        os_name = "macos"
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    elif sys_name == "windows":
        os_name = "windows"
        if "arm" in machine or "aarch64" in machine:
            arch = "arm64"
        elif "64" in machine:
            arch = "x64"
        else:
            arch = "x86"
    else:
        os_name = "linux"
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"

    return {
        "os": os_name,
        "arch": arch,
        "platform_tag": f"{os_name}-{arch}",
        "is_windows": os_name == "windows",
        "is_macos": os_name == "macos",
    }


def get_base_resource_dir() -> str:
    """
    Returns the root directory for bundled assets (supports PyInstaller _MEIPASS and normal execution).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return getattr(sys, "_MEIPASS")
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def get_writable_bin_dir() -> str:
    """
    Returns a guaranteed-writable directory for storing downloaded platform-tools (adb / adb.exe).
    """
    info = get_os_arch_info()
    base_dir = get_base_resource_dir()
    candidate = os.path.join(base_dir, "bin", info["os"])
    try:
        os.makedirs(candidate, exist_ok=True)
        if os.access(candidate, os.W_OK):
            return candidate
    except OSError:
        pass

    if info["is_windows"]:
        appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        fallback = os.path.join(appdata, "FacebookContestValidator", "bin", "windows")
    else:
        fallback = os.path.expanduser("~/Library/Application Support/FacebookContestValidator/bin/macos")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def download_official_adb_if_missing(force: bool = False) -> str:
    """
    Automatically downloads and extracts Google's official signed Android Platform-Tools
    (`adb.exe`, `AdbWinApi.dll`, `AdbWinUsbApi.dll` on Windows; `adb` on macOS/Linux)
    if no ADB binary is present on the user's computer.
    """
    global _adb_download_attempted
    with _adb_download_lock:
        if _adb_download_attempted and not force:
            return ""
        _adb_download_attempted = True

        info = get_os_arch_info()
        os_name = info["os"]
        url = PLATFORM_TOOLS_URLS.get(os_name)
        if not url:
            return ""

        target_dir = get_writable_bin_dir()
        exe_name = "adb.exe" if info["is_windows"] else "adb"
        target_adb = os.path.join(target_dir, exe_name)
        if os.path.isfile(target_adb) and not force:
            return target_adb

        zip_path = os.path.join(target_dir, f"platform-tools-{os_name}.zip")
        extract_tmp = os.path.join(target_dir, "_tmp_pt")
        try:
            logger.info(f"Downloading official Google Android Platform-Tools ({os_name}) from {url}...")
            urllib.request.urlretrieve(url, zip_path)

            if os.path.exists(extract_tmp):
                shutil.rmtree(extract_tmp, ignore_errors=True)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_tmp)

            pt_root = os.path.join(extract_tmp, "platform-tools")
            needed = (
                ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"]
                if info["is_windows"]
                else ["adb"]
            )
            for fname in needed:
                src = os.path.join(pt_root, fname)
                dst = os.path.join(target_dir, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    if not info["is_windows"]:
                        try:
                            os.chmod(dst, 0o755)
                        except OSError:
                            pass

            if os.path.isfile(target_adb):
                logger.info(f"Successfully installed official ADB at: {target_adb}")
                return target_adb
        except Exception as e:
            logger.error(f"Failed to auto-download Android Platform-Tools: {e}")
        finally:
            shutil.rmtree(extract_tmp, ignore_errors=True)
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except OSError:
                pass

        return ""


def resolve_adb_binary(auto_download: bool = True) -> str:
    """
    Finds the best available ADB binary:
    1. Bundled or writable platform-specific binary inside bin/<os>-<arch>/ or bin/<os>/
    2. System PATH ('adb' or 'adb.exe')
    3. Standard Android SDK locations on macOS / Windows / Linux
    4. Auto-downloads Google's official signed Android Platform-Tools if missing!
    """
    info = get_os_arch_info()
    exe_name = "adb.exe" if info["is_windows"] else "adb"
    base_dir = get_base_resource_dir()
    home = os.path.expanduser("~")
    local_app_data = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))

    candidate_paths = [
        os.path.join(base_dir, "bin", info["platform_tag"], exe_name),
        os.path.join(base_dir, "bin", info["os"], exe_name),
        os.path.join(base_dir, "bin", "platform-tools", exe_name),
        os.path.join(base_dir, "bin", exe_name),
        os.path.join(get_writable_bin_dir(), exe_name),
    ]

    for path in candidate_paths:
        if os.path.isfile(path):
            if not info["is_windows"] and not os.access(path, os.X_OK):
                try:
                    os.chmod(path, 0o755)
                except OSError:
                    pass
            return path

    # Check system PATH
    which_adb = shutil.which(exe_name) or shutil.which("adb")
    if which_adb and os.path.isfile(which_adb):
        return which_adb

    # Standard OS SDK locations
    if info["is_macos"]:
        sdk_candidates = [
            os.path.join(home, "Library", "Android", "sdk", "platform-tools", "adb"),
            "/opt/homebrew/bin/adb",
            "/usr/local/bin/adb",
        ]
    elif info["is_windows"]:
        sdk_candidates = [
            os.path.join(local_app_data, "FacebookContestValidator", "bin", "windows", "adb.exe"),
            os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe"),
            r"C:\Android\platform-tools\adb.exe",
            r"C:\platform-tools\adb.exe",
            r"C:\Program Files (x86)\Android\android-sdk\platform-tools\adb.exe",
            r"C:\Program Files\Android\android-sdk\platform-tools\adb.exe",
        ]
    else:
        sdk_candidates = [
            os.path.join(home, "Android", "Sdk", "platform-tools", "adb"),
            "/usr/bin/adb",
        ]

    for path in sdk_candidates:
        if os.path.isfile(path):
            return path

    if auto_download:
        downloaded = download_official_adb_if_missing(force=False)
        if downloaded and os.path.isfile(downloaded):
            return downloaded

    return exe_name


def subprocess_windowless_kwargs() -> Dict[str, Any]:
    """
    Returns extra kwargs for subprocess.run / Popen so Windows 10/11 does not flash
    black console windows when running background ADB commands.
    """
    kwargs: Dict[str, Any] = {}
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs
