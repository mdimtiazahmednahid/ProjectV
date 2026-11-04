import logging
import re
import subprocess
import time
from typing import Optional, Dict
from app.utils.platform_binaries import resolve_adb_binary, subprocess_windowless_kwargs

logger = logging.getLogger(__name__)


class ADBDriver:
    """
    Zero-Appium Direct ADB Driver that implements the same essential interface
    as the Appium WebDriver (page_source, current_package, get_window_size, etc.)
    plus fast in-memory screenshot capture and direct swipe/tap controls.
    """

    is_direct_adb = True

    def __init__(self, device_serial: str):
        self.device_serial = device_serial
        self.adb_bin = resolve_adb_binary(auto_download=True)
        self._window_size: Optional[Dict[str, int]] = None

    def _run_adb(self, args: list, timeout: float = 10.0, binary: bool = False):
        cmd = [self.adb_bin, "-s", self.device_serial] + args
        kwargs = subprocess_windowless_kwargs()
        if binary:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=False,
                timeout=timeout,
                **kwargs,
            )
        # Critical on Windows: force UTF-8 decoding with replacement so Bangla/emoji/bullet
        # characters in Android uiautomator XML dumps never trigger cp1252 UnicodeDecodeError!
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **kwargs,
        )

    def is_device_ready(self) -> bool:
        """
        Verifies via `adb -s <serial> get-state` that the device is genuinely online (`device` state),
        and attempts a fast `adb reconnect offline` if needed.
        """
        try:
            res = self._run_adb(["get-state"], timeout=3.5)
            state = (res.stdout or "").strip().lower()
            if state == "device":
                return True
            # Try one fast reconnect if offline or transient
            subprocess.run(
                [self.adb_bin, "reconnect", "offline"],
                capture_output=True,
                text=True,
                timeout=3.0,
                **subprocess_windowless_kwargs(),
            )
            res2 = self._run_adb(["get-state"], timeout=3.5)
            return (res2.stdout or "").strip().lower() == "device"
        except Exception:
            return False

    def get_window_size(self) -> Dict[str, int]:
        if self._window_size:
            return self._window_size
        try:
            res = self._run_adb(["shell", "wm", "size"], timeout=5.0)
            match = re.search(r"(\d+)x(\d+)", res.stdout or "")
            if match:
                self._window_size = {
                    "width": int(match.group(1)),
                    "height": int(match.group(2)),
                }
                return self._window_size
        except Exception as e:
            logger.warning(f"Failed to query wm size via ADB, using default 1080x2400: {e}")

        self._window_size = {"width": 1080, "height": 2400}
        return self._window_size

    @property
    def current_package(self) -> str:
        try:
            res = self._run_adb(["shell", "dumpsys", "window"], timeout=5.0)
            out = res.stdout or ""
            for pattern in (
                r"mCurrentFocus=Window\{[^\}]*\s+([a-zA-Z0-9_.]+)/",
                r"mFocusedApp=ActivityRecord\{[^\}]*\s+([a-zA-Z0-9_.]+)/",
                r"mObscuringWindow=Window\{[^\}]*\s+([a-zA-Z0-9_.]+)/",
            ):
                m = re.search(pattern, out)
                if m:
                    return m.group(1)

            # Fallback to dumpsys activity activities
            res2 = self._run_adb(["shell", "dumpsys", "activity", "activities"], timeout=5.0)
            out2 = res2.stdout or ""
            for pat2 in (
                r"topResumedActivity=ActivityRecord\{[^\}]*\s+([a-zA-Z0-9_.]+)/",
                r"ResumedActivity:\s+ActivityRecord\{[^\}]*\s+([a-zA-Z0-9_.]+)/",
                r"mResumedActivity:\s+ActivityRecord\{[^\}]*\s+([a-zA-Z0-9_.]+)/",
            ):
                m2 = re.search(pat2, out2)
                if m2:
                    return m2.group(1)
        except Exception as e:
            logger.error(f"ADB current_package check failed: {e}")
        return ""

    @property
    def current_activity(self) -> str:
        try:
            res = self._run_adb(["shell", "dumpsys", "window"], timeout=5.0)
            m = re.search(r"mCurrentFocus=Window\{[^\}]*\s+[a-zA-Z0-9_.]+/([a-zA-Z0-9_.$]+)", res.stdout or "")
            if m:
                return m.group(1)
        except Exception:
            pass
        return ""

    @property
    def page_source(self) -> str:
        """
        Dumps UI XML hierarchy directly via ADB without needing Appium Server.
        Uses isolated try/except blocks per strategy so a timeout or /dev/tty restriction
        on Windows adb.exe always falls back cleanly to /sdcard/window_dump.xml.
        """
        # Strategy 1: Fast compressed stdout streaming via /dev/tty
        try:
            res = self._run_adb(["exec-out", "uiautomator", "dump", "--compressed", "/dev/tty"], timeout=6.0)
            xml = self._extract_xml(res.stdout or "")
            if xml:
                return xml
        except Exception as e:
            logger.debug(f"Strategy 1 (compressed /dev/tty) skipped: {e}")

        # Strategy 2: Uncompressed stdout streaming via /dev/tty
        try:
            res = self._run_adb(["exec-out", "uiautomator", "dump", "/dev/tty"], timeout=6.0)
            xml = self._extract_xml(res.stdout or "")
            if xml:
                return xml
        except Exception as e:
            logger.debug(f"Strategy 2 (/dev/tty) skipped: {e}")

        # Strategy 3: Compressed dump to /sdcard/window_dump.xml + cat
        try:
            self._run_adb(["shell", "uiautomator", "dump", "--compressed", "/sdcard/window_dump.xml"], timeout=8.0)
            res2 = self._run_adb(["exec-out", "cat", "/sdcard/window_dump.xml"], timeout=6.0)
            xml2 = self._extract_xml(res2.stdout or "")
            if xml2:
                return xml2
        except Exception as e:
            logger.debug(f"Strategy 3 (compressed /sdcard/window_dump.xml) skipped: {e}")

        # Strategy 4: Standard dump to /sdcard/window_dump.xml + shell cat
        try:
            self._run_adb(["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"], timeout=8.0)
            res3 = self._run_adb(["shell", "cat", "/sdcard/window_dump.xml"], timeout=6.0)
            xml3 = self._extract_xml(res3.stdout or "")
            if xml3:
                return xml3
        except Exception as e:
            logger.error(f"Direct ADB page_source dump failed across all strategies: {e}")

        return ""

    @staticmethod
    def _extract_xml(raw_output: str) -> str:
        if not raw_output:
            return ""
        start = raw_output.find("<?xml")
        if start == -1:
            start = raw_output.find("<hierarchy")
        end = raw_output.rfind("</hierarchy>")
        if start != -1 and end != -1:
            return raw_output[start : end + len("</hierarchy>")]
        return ""

    def capture_screenshot_bytes(self) -> bytes:
        """
        Captures raw PNG screenshot bytes in memory for fast avatar cropping & pHash.
        """
        try:
            res = self._run_adb(["exec-out", "screencap", "-p"], timeout=6.0, binary=True)
            data = res.stdout or b""
            if data.startswith(b"\x89PNG\r\r\n"):
                data = data.replace(b"\r\n", b"\n")
            if res.returncode == 0 and data.startswith(b"\x89PNG"):
                return data
        except Exception as e:
            logger.debug(f"ADB screencap failed: {e}")
        return b""

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 550) -> bool:
        try:
            res = self._run_adb(
                ["shell", "input", "swipe", str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)],
                timeout=5.0
            )
            return res.returncode == 0
        except Exception as e:
            logger.error(f"ADB swipe failed: {e}")
            return False

    def tap(self, x: int, y: int) -> bool:
        try:
            res = self._run_adb(["shell", "input", "tap", str(x), str(y)], timeout=4.0)
            return res.returncode == 0
        except Exception as e:
            logger.error(f"ADB tap failed: {e}")
            return False

    def press_back(self) -> bool:
        try:
            res = self._run_adb(["shell", "input", "keyevent", "4"], timeout=4.0)
            return res.returncode == 0
        except Exception as e:
            logger.error(f"ADB press_back failed: {e}")
            return False

    def quit(self):
        pass


class ADBManager:
    """
    Connection manager for Direct ADB Mode (drop-in alternative to AppiumManager).
    """

    def __init__(self):
        self.driver: Optional[ADBDriver] = None

    def connect(self, device_serial: str) -> bool:
        if not device_serial:
            return False
        try:
            candidate = ADBDriver(device_serial)
            if not candidate.is_device_ready():
                logger.warning(f"Device {device_serial} is not in 'device' state yet.")
                self.driver = None
                return False
            size = candidate.get_window_size()
            if size and size.get("width"):
                self.driver = candidate
                logger.info(
                    f"Connected to {device_serial} via Direct ADB Mode (Screen: {size['width']}x{size['height']})."
                )
                return True
        except Exception as e:
            logger.error(f"Failed to connect via Direct ADB: {e}")
        self.driver = None
        return False

    def get_driver(self) -> Optional[ADBDriver]:
        return self.driver

    def disconnect(self):
        self.driver = None

    def is_connected(self) -> bool:
        return self.driver is not None
