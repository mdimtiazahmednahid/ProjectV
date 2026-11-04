import logging
import os
import subprocess
from typing import Dict, List, Tuple
from app.utils.platform_binaries import (
    download_official_adb_if_missing,
    get_os_arch_info,
    resolve_adb_binary,
    subprocess_windowless_kwargs,
)

logger = logging.getLogger(__name__)


class DeviceManager:
    @staticmethod
    def is_adb_binary_present() -> bool:
        adb_bin = resolve_adb_binary(auto_download=False)
        return os.path.isfile(adb_bin)

    @staticmethod
    def _force_kill_hung_adb() -> None:
        info = get_os_arch_info()
        try:
            if info["is_windows"]:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "adb.exe", "/T"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    **subprocess_windowless_kwargs(),
                )
            else:
                subprocess.run(
                    ["killall", "-9", "adb"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
        except Exception:
            pass

    @staticmethod
    def get_connected_devices(auto_reconnect: bool = False) -> List[Dict[str, str]]:
        devices: List[Dict[str, str]] = []
        adb_bin = resolve_adb_binary(auto_download=auto_reconnect)
        try:
            result = subprocess.run(
                [adb_bin, "devices", "-l"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=6,
                **subprocess_windowless_kwargs(),
            )

            combined = f"{result.stdout or ''}\n{result.stderr or ''}"
            if result.returncode != 0 or "cannot connect to daemon" in combined or "Address already in use" in combined:
                if auto_reconnect:
                    DeviceManager._force_kill_hung_adb()
                    subprocess.run(
                        [adb_bin, "start-server"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=8,
                        **subprocess_windowless_kwargs(),
                    )
                    result = subprocess.run(
                        [adb_bin, "devices", "-l"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=6,
                        **subprocess_windowless_kwargs(),
                    )

            devices = DeviceManager._parse_devices_output(result.stdout)

            # If any device is offline or no devices found when auto_reconnect is requested, try adb reconnect
            if auto_reconnect and (not devices or any(d["state"] != "device" for d in devices)):
                try:
                    subprocess.run(
                        [adb_bin, "reconnect", "offline"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=4,
                        **subprocess_windowless_kwargs(),
                    )
                    result2 = subprocess.run(
                        [adb_bin, "devices", "-l"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=6,
                        **subprocess_windowless_kwargs(),
                    )
                    devices = DeviceManager._parse_devices_output(result2.stdout)
                except Exception:
                    pass

        except FileNotFoundError:
            if auto_reconnect:
                downloaded = download_official_adb_if_missing(force=True)
                if downloaded and os.path.isfile(downloaded):
                    return DeviceManager.get_connected_devices(auto_reconnect=False)
            logger.error("ADB is not installed or not in PATH.")
        except subprocess.TimeoutExpired:
            logger.error("ADB command timed out.")
        except Exception as e:
            logger.error(f"Error getting adb devices: {e}")

        return devices

    @staticmethod
    def _parse_devices_output(stdout_text: str) -> List[Dict[str, str]]:
        devices: List[Dict[str, str]] = []
        if not stdout_text:
            return devices
        lines = stdout_text.strip().split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("List of devices") or stripped.startswith("*"):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                serial = parts[0]
                state = parts[1]

                extras = " ".join(parts[2:])
                model = "Android Device"
                if "model:" in extras:
                    model = extras.split("model:")[1].split()[0]

                devices.append(
                    {
                        "serial": serial,
                        "state": state,
                        "model": model,
                        "raw": stripped,
                    }
                )
        return devices

    @staticmethod
    def restart_adb_server() -> Tuple[bool, str, List[Dict[str, str]]]:
        """
        Ensures ADB is installed (auto-downloading Google's official signed platform-tools
        if missing on Windows/macOS), force-kills any hung ADB daemon holding port 5037,
        starts a clean ADB server, and scans for connected phones.
        """
        adb_bin = resolve_adb_binary(auto_download=True)
        if not os.path.isfile(adb_bin):
            downloaded = download_official_adb_if_missing(force=True)
            if downloaded:
                adb_bin = downloaded

        try:
            subprocess.run(
                [adb_bin, "kill-server"],
                capture_output=True,
                text=True,
                timeout=5,
                **subprocess_windowless_kwargs(),
            )
            DeviceManager._force_kill_hung_adb()
            start_res = subprocess.run(
                [adb_bin, "start-server"],
                capture_output=True,
                text=True,
                timeout=8,
                **subprocess_windowless_kwargs(),
            )
            devices = DeviceManager.get_connected_devices(auto_reconnect=True)
            combined_log = f"{start_res.stdout or ''}\n{start_res.stderr or ''}".strip()
            return True, combined_log, devices
        except Exception as e:
            logger.error(f"Error restarting ADB server: {e}")
            return False, str(e), []

    @staticmethod
    def connect_wireless_adb(
        connect_ip_port: str,
        pair_ip_port: str = "",
        pair_code: str = "",
    ) -> Tuple[bool, str, List[Dict[str, str]]]:
        """
        Pairs (optional, for Android 11+ Wireless Debugging) and connects to a phone
        over Wi-Fi (`adb pair <ip:port> <code>` + `adb connect <ip:port>`).
        Bypasses USB cable and Windows OEM USB driver issues completely!
        """
        adb_bin = resolve_adb_binary(auto_download=True)
        logs = []
        try:
            if pair_ip_port.strip() and pair_code.strip():
                pair_res = subprocess.run(
                    [adb_bin, "pair", pair_ip_port.strip(), pair_code.strip()],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    **subprocess_windowless_kwargs(),
                )
                pair_out = f"{pair_res.stdout or ''}\n{pair_res.stderr or ''}".strip()
                logs.append(f"Pair: {pair_out}")

            conn_res = subprocess.run(
                [adb_bin, "connect", connect_ip_port.strip()],
                capture_output=True,
                text=True,
                timeout=10,
                **subprocess_windowless_kwargs(),
            )
            conn_out = f"{conn_res.stdout or ''}\n{conn_res.stderr or ''}".strip()
            logs.append(f"Connect: {conn_out}")

            devices = DeviceManager.get_connected_devices(auto_reconnect=False)
            ok = "connected to" in conn_out.lower() or any(
                d.get("state") == "device" for d in devices
            )
            return ok, "\n".join(logs), devices
        except Exception as e:
            return False, str(e), []

    @staticmethod
    def open_url(serial: str, url: str) -> bool:
        adb_bin = resolve_adb_binary(auto_download=False)
        try:
            result = subprocess.run(
                [
                    adb_bin,
                    "-s",
                    serial,
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=5,
                **subprocess_windowless_kwargs(),
            )
            if result.returncode == 0:
                logger.info(f"Successfully opened URL on device {serial}")
                return True
            else:
                logger.error(f"Failed to open URL. ADB stderr: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error opening URL via ADB: {e}")
            return False
