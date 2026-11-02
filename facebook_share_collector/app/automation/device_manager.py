import subprocess
import logging
from typing import List, Dict, Tuple
from app.utils.platform_binaries import resolve_adb_binary, subprocess_windowless_kwargs

logger = logging.getLogger(__name__)


class DeviceManager:
    @staticmethod
    def get_connected_devices(auto_reconnect: bool = False) -> List[Dict[str, str]]:
        devices: List[Dict[str, str]] = []
        adb_bin = resolve_adb_binary()
        try:
            result = subprocess.run(
                [adb_bin, 'devices', '-l'],
                capture_output=True,
                text=True,
                timeout=6,
                **subprocess_windowless_kwargs()
            )

            devices = DeviceManager._parse_devices_output(result.stdout)

            # If any device is offline or no devices found when auto_reconnect is requested, try adb reconnect
            if auto_reconnect and (not devices or any(d["state"] != "device" for d in devices)):
                try:
                    subprocess.run(
                        [adb_bin, 'reconnect', 'offline'],
                        capture_output=True,
                        text=True,
                        timeout=4,
                        **subprocess_windowless_kwargs()
                    )
                    result2 = subprocess.run(
                        [adb_bin, 'devices', '-l'],
                        capture_output=True,
                        text=True,
                        timeout=6,
                        **subprocess_windowless_kwargs()
                    )
                    devices = DeviceManager._parse_devices_output(result2.stdout)
                except Exception:
                    pass

        except FileNotFoundError:
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
        lines = stdout_text.strip().split('\n')
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

                devices.append({
                    "serial": serial,
                    "state": state,
                    "model": model,
                    "raw": stripped
                })
        return devices

    @staticmethod
    def restart_adb_server() -> Tuple[bool, str, List[Dict[str, str]]]:
        """
        Restarts the ADB server (`adb kill-server` -> `adb start-server` -> `adb devices -l`)
        to recover from hung USB pipes, macOS exclusive-access locks, or offline states.
        """
        adb_bin = resolve_adb_binary()
        try:
            subprocess.run(
                [adb_bin, 'kill-server'],
                capture_output=True,
                text=True,
                timeout=5,
                **subprocess_windowless_kwargs()
            )
            start_res = subprocess.run(
                [adb_bin, 'start-server'],
                capture_output=True,
                text=True,
                timeout=8,
                **subprocess_windowless_kwargs()
            )
            devices = DeviceManager.get_connected_devices(auto_reconnect=True)
            combined_log = f"{start_res.stdout}\n{start_res.stderr}".strip()
            return True, combined_log, devices
        except Exception as e:
            logger.error(f"Error restarting ADB server: {e}")
            return False, str(e), []

    @staticmethod
    def open_url(serial: str, url: str) -> bool:
        adb_bin = resolve_adb_binary()
        try:
            result = subprocess.run(
                [adb_bin, '-s', serial, 'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', url],
                capture_output=True,
                text=True,
                timeout=5,
                **subprocess_windowless_kwargs()
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
