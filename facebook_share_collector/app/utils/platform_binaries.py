import os
import sys
import shutil
import platform
import subprocess
from typing import Dict, Any


def get_os_arch_info() -> Dict[str, str]:
    """
    Returns normalized OS and CPU architecture info for macOS (Intel & Apple Silicon),
    Windows (10/11 x64 & x86), and Linux.
    """
    sys_name = platform.system().lower()
    machine = platform.machine().lower()

    if sys_name == "darwin":
        os_name = "macos"
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    elif sys_name == "windows":
        os_name = "windows"
        arch = "x64" if "64" in machine else "x86"
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
    # Default to facebook_share_collector directory
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def resolve_adb_binary() -> str:
    """
    Finds the best available ADB binary:
    1. Bundled platform-specific binary inside bin/<os>-<arch>/ or bin/<os>/
    2. System PATH ('adb' or 'adb.exe')
    3. Standard Android SDK locations on macOS / Windows / Linux
    """
    info = get_os_arch_info()
    exe_name = "adb.exe" if info["is_windows"] else "adb"
    base_dir = get_base_resource_dir()

    candidate_paths = [
        os.path.join(base_dir, "bin", info["platform_tag"], exe_name),
        os.path.join(base_dir, "bin", info["os"], exe_name),
        os.path.join(base_dir, "bin", "platform-tools", exe_name),
        os.path.join(base_dir, "bin", exe_name),
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
    if which_adb:
        return which_adb

    # Standard OS SDK locations
    home = os.path.expanduser("~")
    if info["is_macos"]:
        sdk_candidates = [
            os.path.join(home, "Library", "Android", "sdk", "platform-tools", "adb"),
            "/opt/homebrew/bin/adb",
            "/usr/local/bin/adb",
        ]
    elif info["is_windows"]:
        local_app_data = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        sdk_candidates = [
            os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe"),
            r"C:\Android\platform-tools\adb.exe",
        ]
    else:
        sdk_candidates = [
            os.path.join(home, "Android", "Sdk", "platform-tools", "adb"),
            "/usr/bin/adb",
        ]

    for path in sdk_candidates:
        if os.path.isfile(path):
            return path

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

