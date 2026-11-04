import datetime
import json
import logging
import os
import re
import select
import socket
import struct
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Tuple
from app.utils.platform_binaries import (
    download_official_adb_if_missing,
    get_os_arch_info,
    resolve_adb_binary,
    subprocess_windowless_kwargs,
)

logger = logging.getLogger(__name__)

# Known Android OEM USB Vendor IDs (decimal and hex) — including Tecno / Transsion (Infinix / Itel), Samsung, Xiaomi, etc.
ANDROID_USB_VENDOR_IDS = {
    0x04E8: "Samsung",
    0x18D1: "Google / Tecno / Android",
    0x2717: "Xiaomi / Redmi / POCO",
    0x22D9: "Oppo / Realme / OnePlus",
    0x2A70: "OnePlus",
    0x2D95: "Vivo / iQOO",
    0x12D1: "Huawei / Honor",
    0x22B8: "Motorola",
    0x0B05: "Asus",
    0x0FCE: "Sony",
    0x1004: "LG",
    0x0BB4: "HTC",
    0x2916: "Android",
    0x0E8D: "Tecno / Infinix / MediaTek",
    0x1782: "Tecno / Infinix / Unisoc",
    0x2E04: "Tecno / Infinix / Itel (Transsion)",
    0x2C7C: "Tecno / Transsion",
    0x2FB8: "Tecno / Transsion",
    0x271D: "Tecno / Gionee / Transsion",
    0x05C6: "Qualcomm / Android",
    0x19D2: "ZTE / Nubia / Android",
    0x2A45: "Meizu",
    0x1D4D: "Pegatron",
    0x0489: "Foxconn / Nokia / Android",
    0x1BBB: "Alcatel / TCL",
    0x2A47: "Nothing / Android",
    0x2006: "Android / Transsion",
}

# Exact Tecno / Transsion internal model code -> marketing name map
TECNO_MODEL_CODE_MAP = {
    "ck6": "TECNO Camon 20",
    "ck6n": "TECNO Camon 20",
    "tecno-ck6": "TECNO Camon 20",
    "tecno_ck6": "TECNO Camon 20",
    "tecno-ck6n": "TECNO Camon 20",
    "tecno_ck6n": "TECNO Camon 20",
    "ck7n": "TECNO Camon 20 Pro",
    "tecno-ck7n": "TECNO Camon 20 Pro",
    "tecno_ck7n": "TECNO Camon 20 Pro",
    "ck8n": "TECNO Camon 20 Pro 5G",
    "tecno-ck8n": "TECNO Camon 20 Pro 5G",
    "tecno_ck8n": "TECNO Camon 20 Pro 5G",
    "ck9n": "TECNO Camon 20 Premier 5G",
    "tecno-ck9n": "TECNO Camon 20 Premier 5G",
    "tecno_ck9n": "TECNO Camon 20 Premier 5G",
    "cl6": "TECNO Camon 30",
    "cl6k": "TECNO Camon 30",
    "tecno-cl6": "TECNO Camon 30",
    "tecno_cl6": "TECNO Camon 30",
    "cl7": "TECNO Camon 30 5G",
    "cl7k": "TECNO Camon 30 5G",
    "cl8": "TECNO Camon 30 Pro 5G",
    "cl9": "TECNO Camon 30 Premier 5G",
    "cg8": "TECNO Camon 18P",
    "cg8h": "TECNO Camon 18P",
    "ch6": "TECNO Camon 19",
    "ch6n": "TECNO Camon 19",
    "ch7": "TECNO Camon 19 Pro",
    "ch7n": "TECNO Camon 19 Pro",
    "ch9": "TECNO Camon 19 Pro 5G",
    "ch9n": "TECNO Camon 19 Pro 5G",
    "kj5": "TECNO Spark 20",
    "kj5n": "TECNO Spark 20",
    "kj6": "TECNO Spark 20C",
    "kj7": "TECNO Spark 20 Pro",
    "kl7": "TECNO Spark 20 Pro+",
    "ki5k": "TECNO Spark 10",
    "ki5q": "TECNO Spark 10",
    "ki7": "TECNO Spark 10 Pro",
    "lh7n": "TECNO Pova 4",
    "lh8n": "TECNO Pova 5",
    "li6": "TECNO Pova 6 Neo",
    "li7": "TECNO Pova 6",
    "li9": "TECNO Pova 6 Pro 5G",
    "ad8": "TECNO Phantom X2",
    "ad9": "TECNO Phantom X2 Pro",
    "ad10": "TECNO Phantom V Fold",
    "ae10": "TECNO Phantom V Flip",
}

# Product/Model string signatures for Tecno (Camon 20 Pro, Spark, Pova, Phantom, Pop) & Transsion family
TECNO_MODEL_KEYWORDS = (
    "tecno",
    "techno",
    "camon",
    "spark",
    "pova",
    "phantom",
    "transsion",
    "infinix",
    "itel",
    "hios",
    "tecno-",
    "tecno_",
    "ck6",
    "ck7",
    "ck8",
    "ck9",
    "cl6",
    "cl7",
    "cl8",
    "cl9",
    "cg8",
    "ch6",
    "ch7",
    "ch9",
    "kj5",
    "kj6",
    "kj7",
    "kl7",
    "ki5",
    "ki7",
    "li6",
    "li7",
    "li9",
    "lh7",
    "lh8",
    "lg7",
    "bf7",
)

# Transsion / Tecno factory USB serial number pattern (e.g. 102622534S009003, 098765432A001234)
TRANSSION_SERIAL_RE = re.compile(r"^\d{6,10}[A-HJ-NP-Z]\d{5,8}$")


class DeviceManager:
    _last_adb_diagnostic: str = ""
    _mdns_server_ensured: bool = False
    _usb_ini_ensured: bool = False
    _model_props_cache: Dict[str, Tuple[str, str]] = {}
    _tcpip_bridged_serials: set = set()

    @classmethod
    def get_last_diagnostic(cls) -> str:
        return cls._last_adb_diagnostic

    @staticmethod
    def _known_devices_file_path() -> str:
        from app.database.repository import ensure_writable_data_dir

        data_dir = ensure_writable_data_dir("data")
        return os.path.join(data_dir, "known_devices.json")

    @classmethod
    def get_saved_devices(cls) -> List[Dict[str, str]]:
        """
        Loads previously connected phones (USB or Wi-Fi) from `data/known_devices.json`.
        Each entry contains:
          `{"serial": str, "model": str, "vendor": str, "connection_type": "usb"|"wifi", "ip_port": str, "last_seen": str}`
        """
        path = cls._known_devices_file_path()
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and d.get("serial")]
        except Exception:
            pass
        return []

    @classmethod
    def save_known_device(
        cls,
        serial: str,
        model: str = "",
        vendor: str = "",
        connection_type: str = "",
        ip_port: str = "",
    ) -> None:
        """
        Persists a connected device into `data/known_devices.json` so Sentra remembers
        every previously connected phone across app restarts and can 1-click reconnect.
        """
        serial = (serial or "").strip()
        if not serial or serial.startswith("usb_hw:") or serial.startswith("saved:"):
            return
        is_wifi = (
            connection_type == "wifi"
            or ":" in serial
            or "._adb-tls-" in serial
            or serial.startswith("adb-")
        )
        conn_type = connection_type or ("wifi" if is_wifi else "usb")
        if not ip_port and ":" in serial and re.match(r"^\d{1,3}(?:\.\d{1,3}){3}:\d+$", serial):
            ip_port = serial

        # Enrich model/brand via getprop if not already cached
        if serial not in cls._model_props_cache:
            cls._query_device_brand_and_model(serial)
        cached_vendor, cached_model = cls._model_props_cache.get(serial, ("", ""))

        final_vendor, final_model = cls.resolve_friendly_model_and_vendor(
            serial=serial,
            raw_model=model or cached_model,
            raw_vendor=vendor or cached_vendor,
            include_saved=False,
        )

        # If connected over USB, also discover phone's Wi-Fi IP so we can reconnect wirelessly later
        if not ip_port and conn_type == "usb":
            wlan_ip = cls._query_device_wlan_ip(serial)
            if wlan_ip:
                ip_port = f"{wlan_ip}:5555"

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing = cls.get_saved_devices()
        updated = False
        for item in existing:
            if item.get("serial") == serial or (
                ip_port and item.get("ip_port") and item.get("ip_port").split(":")[0] == ip_port.split(":")[0] and item.get("model") == final_model
            ):
                item["serial"] = serial
                if final_model and final_model not in ("Android Phone", "Android Device"):
                    item["model"] = final_model
                if final_vendor:
                    item["vendor"] = final_vendor
                item["connection_type"] = conn_type
                if ip_port:
                    item["ip_port"] = ip_port
                item["last_seen"] = now_str
                updated = True
                break

        if not updated:
            existing.insert(
                0,
                {
                    "serial": serial,
                    "model": final_model,
                    "vendor": final_vendor,
                    "connection_type": conn_type,
                    "ip_port": ip_port,
                    "last_seen": now_str,
                },
            )

        # Keep most recent 25 devices sorted by last_seen descending
        existing.sort(key=lambda x: x.get("last_seen", ""), reverse=True)
        existing = existing[:25]
        try:
            path = cls._known_devices_file_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @classmethod
    def resolve_friendly_model_and_vendor(
        cls,
        serial: str,
        raw_model: str = "",
        raw_vendor: str = "",
        include_saved: bool = True,
    ) -> Tuple[str, str]:
        """
        Resolves the best friendly `(vendor, model)` for any Android phone (especially Tecno Camon 20 Pro
        `CK7n` / `CK8n` / serial `102622534S009003`), even when `adb devices -l` omits `model:` (e.g.
        in `unauthorized` or `offline` states) or reports an internal code like `TECNO_CK7n`.
        """
        serial_clean = (serial or "").strip()
        model_clean = (raw_model or "").strip().replace("_", " ")
        vendor_clean = (raw_vendor or "").strip()

        if serial_clean in cls._model_props_cache:
            c_v, c_m = cls._model_props_cache[serial_clean]
            if c_m and model_clean in ("", "Android Device", "Android", "Android Phone"):
                model_clean = c_m
            if c_v and not vendor_clean:
                vendor_clean = c_v

        # Check exact Tecno model code dictionary (e.g. CK7n -> TECNO Camon 20 Pro)
        lookup_keys = [
            (raw_model or "").strip().lower(),
            model_clean.lower(),
            model_clean.lower().replace(" ", "-"),
            model_clean.lower().replace(" ", "_"),
        ]
        for lk in lookup_keys:
            if lk in TECNO_MODEL_CODE_MAP:
                model_clean = TECNO_MODEL_CODE_MAP[lk]
                vendor_clean = "Tecno"
                break

        # Cross-reference saved devices if model is still generic
        if include_saved and (not model_clean or model_clean in ("Android Device", "Android", "Android Phone")):
            for sdev in cls.get_saved_devices():
                s_ser = sdev.get("serial", "")
                s_ipp = sdev.get("ip_port", "")
                if s_ser == serial_clean or (
                    ":" in serial_clean and s_ipp and s_ipp.split(":")[0] == serial_clean.split(":")[0]
                ):
                    if sdev.get("model") and sdev["model"] not in ("Android Device", "Android"):
                        model_clean = sdev["model"]
                    if sdev.get("vendor") and not vendor_clean:
                        vendor_clean = sdev["vendor"]
                    break

        combined_lower = f"{vendor_clean} {model_clean} {raw_model}".lower()
        is_tecno = any(kw in combined_lower for kw in TECNO_MODEL_KEYWORDS) or bool(
            TRANSSION_SERIAL_RE.match(serial_clean)
        )
        if is_tecno:
            vendor_clean = "Tecno"
            if not model_clean or model_clean in ("Android Device", "Android", "Android Phone", "Tecno Phone"):
                model_clean = "TECNO Phone"
            elif "tecno" not in model_clean.lower() and not any(
                b in model_clean.lower() for b in ("infinix", "itel")
            ):
                model_clean = f"TECNO {model_clean}".strip()

        if not vendor_clean:
            vendor_clean = "Android"
        if not model_clean or model_clean in ("Android Device", "Android"):
            model_clean = "Android Phone"
        return vendor_clean, model_clean

    @classmethod
    def ensure_adb_usb_ini(cls) -> None:
        """
        Ensures `~/.android/adb_usb.ini` contains all Tecno / Transsion / MediaTek / Unisoc / OEM
        USB Vendor IDs so `adb` always scans Tecno USB interfaces on both macOS and Windows.
        """
        if cls._usb_ini_ensured:
            return
        cls._usb_ini_ensured = True
        try:
            android_dir = os.path.expanduser("~/.android")
            os.makedirs(android_dir, exist_ok=True)
            ini_path = os.path.join(android_dir, "adb_usb.ini")
            existing_vids = set()
            if os.path.isfile(ini_path):
                try:
                    with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            s = line.strip().lower()
                            if s.startswith("0x"):
                                existing_vids.add(s)
                except Exception:
                    pass
            required_vids = [f"0x{vid:04x}" for vid in sorted(ANDROID_USB_VENDOR_IDS.keys())]
            missing = [v for v in required_vids if v.lower() not in existing_vids]
            if missing or not os.path.isfile(ini_path):
                all_vids = sorted(existing_vids.union(v.lower() for v in required_vids))
                content = (
                    "# ANDROID 3RD PARTY USB VENDOR ID LIST -- MANAGED BY SENTRA\n"
                    + "\n".join(all_vids)
                    + "\n"
                )
                with open(ini_path, "w", encoding="utf-8") as f:
                    f.write(content)
        except Exception:
            pass

    @classmethod
    def remove_saved_device(cls, serial: str) -> None:
        existing = [d for d in cls.get_saved_devices() if d.get("serial") != serial]
        try:
            path = cls._known_devices_file_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @classmethod
    def _query_device_wlan_ip(cls, serial: str) -> str:
        """
        Queries a connected USB phone's `wlan0` IPv4 address and optionally enables TCP/IP port 5555
        once per session so Sentra can seamlessly reconnect to the phone over Wi-Fi if the USB cable
        is later unplugged or switches to charge-only mode.
        """
        if not serial or ":" in serial or "._adb-tls-" in serial:
            return ""
        adb_bin = resolve_adb_binary(auto_download=False)
        if not os.path.isfile(adb_bin):
            return ""
        wlan_ip = ""
        try:
            res = subprocess.run(
                [adb_bin, "-s", serial, "shell", "ip -f inet addr show wlan0"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2.0,
                **subprocess_windowless_kwargs(),
            )
            m = re.search(r"inet\s+(\d{1,3}(?:\.\d{1,3}){3})/", res.stdout or "")
            if m and not m.group(1).startswith("127."):
                wlan_ip = m.group(1)
        except Exception:
            pass
        return wlan_ip

    @classmethod
    def _query_device_brand_and_model(cls, serial: str) -> Tuple[str, str]:
        """
        Queries `ro.product.brand`, `ro.product.manufacturer`, `ro.product.marketname`,
        and `ro.product.model` over ADB so Tecno (e.g. TECNO Camon 20 Pro `CK7n` / `CK8n`),
        Samsung, Xiaomi, etc. show their friendly marketing name.
        """
        if serial in cls._model_props_cache:
            return cls._model_props_cache[serial]
        adb_bin = resolve_adb_binary(auto_download=False)
        if not os.path.isfile(adb_bin):
            return ("", "")
        try:
            res = subprocess.run(
                [
                    adb_bin,
                    "-s",
                    serial,
                    "shell",
                    "getprop ro.product.brand; getprop ro.product.marketname; getprop ro.product.model; getprop ro.tran.device.name",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2.5,
                **subprocess_windowless_kwargs(),
            )
            lines = [ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()]
            brand = lines[0] if len(lines) >= 1 else ""
            market = lines[1] if len(lines) >= 2 else ""
            model = lines[2] if len(lines) >= 3 else ""
            tran_name = lines[3] if len(lines) >= 4 else ""
            raw_best = market or tran_name or model
            vendor, friendly = cls.resolve_friendly_model_and_vendor(
                serial=serial,
                raw_model=raw_best,
                raw_vendor=brand,
                include_saved=False,
            )
            if friendly and friendly not in ("Android Phone", "Android Device"):
                cls._model_props_cache[serial] = (vendor, friendly)
                return (vendor, friendly)
        except Exception:
            pass
        return ("", "")

    @staticmethod
    def is_adb_binary_present() -> bool:
        adb_bin = resolve_adb_binary(auto_download=False)
        return os.path.isfile(adb_bin)

    @staticmethod
    def _check_macos_adb_log_for_e00002be() -> bool:
        """
        Checks the tail of macOS `/var/folders/.../T/adb.<uid>.log` for `usb_osx.cpp:168 ... (e00002be)`.
        When `adb` 35–37 runs with its legacy `usb_osx.cpp` backend on macOS Sequoia/Sonoma, it can spam
        `Unable to create an interface plug-in (e00002be)` until restarted with `ADB_LIBUSB=1`.
        """
        try:
            uid = os.getuid() if hasattr(os, "getuid") else 501
            log_path = os.path.join(tempfile.gettempdir(), f"adb.{uid}.log")
            if not os.path.isfile(log_path):
                return False
            with open(log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 4096), os.SEEK_SET)
                tail = f.read().decode("utf-8", errors="ignore").lower()
            return "e00002be" in tail or "unable to create an interface plug-in" in tail
        except Exception:
            return False

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
                # Also release macOS ptpcamerad if it holds exclusive lock on Tecno/Samsung/Android MTP interface
                subprocess.run(
                    ["killall", "-9", "ptpcamerad"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                subprocess.run(
                    ["killall", "-9", "adb"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
        except Exception:
            pass

    @staticmethod
    def parse_macos_ioreg_usb_devices(text: str) -> List[Dict[str, str]]:
        """
        Parses `ioreg` output (`IOUSBHostDevice` / `AppleUSBDevice` / `IOUSBDevice`) into a list of
        detected physical Android USB devices.
        Handles USB product names containing spaces (e.g. `+-o TECNO Camon 20 Pro@14300000`,
        `+-o TECNO CK7n@14300000`, `+-o MT65xx Android Phone@14300000`) and nested hub indentation (`| +-o`).
        """
        found: List[Dict[str, str]] = []
        if not text:
            return found

        # Split on any USB device header line regardless of indentation or spaces in the node name
        blocks = re.split(
            r"(?=^[|\s]*\+-o\s+[^\n]+?<class\s+(?:IOUSBHostDevice|AppleUSBDevice|IOUSBDevice)\b)",
            text,
            flags=re.MULTILINE,
        )
        for blk in blocks:
            if not re.search(r"<class\s+(?:IOUSBHostDevice|AppleUSBDevice|IOUSBDevice)\b", blk):
                continue
            vid_m = re.search(r'"idVendor"\s*=\s*(\d+)', blk)
            if not vid_m:
                continue
            vid = int(vid_m.group(1))
            # Skip Apple internal devices (0x05AC == 1452)
            if vid == 0x05AC:
                continue

            header_m = re.search(
                r"^[|\s]*\+-o\s+([^@\n]+?)(?:@[0-9a-fA-F]+)?\s+<class\s+(?:IOUSBHostDevice|AppleUSBDevice|IOUSBDevice)\b",
                blk,
                flags=re.MULTILINE,
            )
            node_title = header_m.group(1).strip() if header_m else ""

            prod_m = re.search(r'"(?:USB Product Name|kUSBProductString)"\s*=\s*"([^"]+)"', blk)
            prod_name = (prod_m.group(1).strip() if prod_m else "") or node_title
            vend_m = re.search(r'"(?:USB Vendor Name|kUSBVendorString)"\s*=\s*"([^"]+)"', blk)
            vend_str = vend_m.group(1).strip() if vend_m else ""
            ser_m = re.search(r'"(?:USB Serial Number|kUSBSerialNumberString)"\s*=\s*"([^"]+)"', blk)
            serial = ser_m.group(1).strip() if ser_m else ""

            combined_usb_str = f"{prod_name} {vend_str} {node_title} {serial}".lower()
            is_tecno_family = any(kw in combined_usb_str for kw in TECNO_MODEL_KEYWORDS) or bool(
                TRANSSION_SERIAL_RE.match(serial)
            )
            if (
                vid not in ANDROID_USB_VENDOR_IDS
                and "android" not in combined_usb_str
                and not is_tecno_family
            ):
                continue

            if not serial:
                serial = f"usb-{vid:04x}"

            raw_vendor = "Tecno" if is_tecno_family else ANDROID_USB_VENDOR_IDS.get(vid, "Android")
            vendor_name, model_name = DeviceManager.resolve_friendly_model_and_vendor(
                serial=serial,
                raw_model=prod_name,
                raw_vendor=raw_vendor,
            )

            # Check if ADB USB Interface (Class 255, SubClass 66, Protocol 1) is active in descriptor
            has_adb = bool(
                re.search(
                    r'"bInterfaceClass"\s*=\s*255[\s\S]{0,400}?"bInterfaceSubClass"\s*=\s*66',
                    blk,
                )
                or "ADB Interface" in blk
            )
            if not any(d["serial"] == serial for d in found):
                found.append(
                    {
                        "serial": serial,
                        "model": model_name,
                        "vendor": vendor_name,
                        "has_adb_interface": "true" if has_adb else "false",
                    }
                )
        return found

    @staticmethod
    def detect_physical_usb_android_devices() -> List[Dict[str, str]]:
        """
        Detects physical Android phones plugged into USB at the OS hardware level
        (`ioreg` on macOS, `pnputil` on Windows) even when 'USB Debugging' is currently
        switched OFF on the phone (e.g. Tecno HiOS Charge/MTP mode or Samsung MTP-only mode).
        Returns a list of dicts:
          `{"serial": str, "model": str, "vendor": str, "has_adb_interface": "true"|"false"}`
        """
        found: List[Dict[str, str]] = []
        info = get_os_arch_info()
        if info["is_macos"] and os.path.isfile("/usr/sbin/ioreg"):
            for ioreg_cmd in (
                ["/usr/sbin/ioreg", "-r", "-c", "IOUSBHostDevice", "-l", "-w", "0"],
                ["/usr/sbin/ioreg", "-p", "IOUSB", "-l", "-w", "0"],
            ):
                try:
                    res = subprocess.run(
                        ioreg_cmd,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=4,
                    )
                    parsed = DeviceManager.parse_macos_ioreg_usb_devices(res.stdout or "")
                    for item in parsed:
                        if not any(d["serial"] == item["serial"] for d in found):
                            found.append(item)
                    if found:
                        break
                except Exception:
                    pass
        elif info["is_windows"]:
            try:
                res = subprocess.run(
                    ["pnputil", "/enum-devices", "/connected"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    **subprocess_windowless_kwargs(),
                )
                blocks = re.split(r"(?=Instance ID:)", res.stdout or "")
                for blk in blocks:
                    blk_lower = blk.lower()
                    matched_vendor = None
                    matched_ser = ""
                    matched_model = ""
                    desc_m = re.search(r"Device Description:\s*(.+)", blk)
                    if desc_m:
                        matched_model = desc_m.group(1).strip()
                    inst_m = re.search(r"Instance ID:\s*(.+)", blk)
                    inst_line = inst_m.group(1).strip() if inst_m else ""
                    for vid, vname in ANDROID_USB_VENDOR_IDS.items():
                        tag = f"VID_{vid:04X}"
                        if tag in inst_line.upper():
                            matched_vendor = vname
                            parts = inst_line.split("\\")
                            matched_ser = parts[-1].strip() if len(parts) >= 3 else tag
                            break
                    if not matched_vendor and any(kw in blk_lower for kw in TECNO_MODEL_KEYWORDS):
                        matched_vendor = "Tecno"
                        parts = inst_line.split("\\")
                        matched_ser = parts[-1].strip() if len(parts) >= 3 else "TECNO-USB"
                    if matched_vendor and matched_ser:
                        v_resolved, m_resolved = DeviceManager.resolve_friendly_model_and_vendor(
                            serial=matched_ser,
                            raw_model=matched_model,
                            raw_vendor=matched_vendor,
                        )
                        if not any(d["serial"] == matched_ser for d in found):
                            found.append(
                                {
                                    "serial": matched_ser,
                                    "model": m_resolved,
                                    "vendor": v_resolved,
                                    "has_adb_interface": "false",
                                }
                            )
            except Exception:
                pass
        return found

    @staticmethod
    def ensure_adb_mdns_server() -> None:
        """
        Ensures the running ADB daemon has `ADB_MDNS_OPENSCREEN=1` (and `ADB_LIBUSB=1` on macOS if
        `usb_osx.cpp` hit `e00002be`) enabled so USB and wireless QR code pairing work reliably.
        """
        DeviceManager.ensure_adb_usb_ini()
        if DeviceManager._mdns_server_ensured:
            return
        adb_bin = resolve_adb_binary(auto_download=True)
        if not os.path.isfile(adb_bin):
            return
        try:
            env = os.environ.copy()
            env["ADB_MDNS_OPENSCREEN"] = "1"
            if get_os_arch_info()["is_macos"]:
                env["ADB_LIBUSB"] = "1"
            chk = subprocess.run(
                [adb_bin, "mdns", "check"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                env=env,
                **subprocess_windowless_kwargs(),
            )
            chk_out = f"{chk.stdout or ''}\n{chk.stderr or ''}".lower()
            need_restart = (
                "openscreen" not in chk_out
                and ("error" in chk_out or "unknown" in chk_out or chk.returncode != 0)
            ) or (get_os_arch_info()["is_macos"] and DeviceManager._check_macos_adb_log_for_e00002be())
            if need_restart:
                subprocess.run(
                    [adb_bin, "kill-server"],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )
                subprocess.run(
                    [adb_bin, "start-server"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )
            DeviceManager._mdns_server_ensured = True
        except Exception:
            pass

    @staticmethod
    def get_connected_devices(auto_reconnect: bool = False) -> List[Dict[str, str]]:
        DeviceManager.ensure_adb_usb_ini()
        devices: List[Dict[str, str]] = []
        adb_bin = resolve_adb_binary(auto_download=auto_reconnect)
        env = os.environ.copy()
        env["ADB_MDNS_OPENSCREEN"] = "1"
        if get_os_arch_info()["is_macos"]:
            env["ADB_LIBUSB"] = "1"
        try:
            result = subprocess.run(
                [adb_bin, "devices", "-l"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=6,
                env=env,
                **subprocess_windowless_kwargs(),
            )

            combined = f"{result.stdout or ''}\n{result.stderr or ''}"
            if "e00002be" in combined.lower() or "unable to create an interface plug-in" in combined.lower():
                DeviceManager._last_adb_diagnostic = (
                    "macOS USB interface is locked by ptpcamerad/Chrome (e00002be) or USB Debugging is OFF on phone."
                )

            daemon_down = (
                result.returncode != 0
                or "cannot connect to daemon" in combined.lower()
                or "daemon not running" in combined.lower()
                or "address already in use" in combined.lower()
            )
            if daemon_down:
                if auto_reconnect:
                    DeviceManager._force_kill_hung_adb()
                start_res = subprocess.run(
                    [adb_bin, "start-server"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )
                DeviceManager._mdns_server_ensured = True
                start_combined = f"{start_res.stdout or ''}\n{start_res.stderr or ''}"
                if "e00002be" in start_combined.lower():
                    DeviceManager._last_adb_diagnostic = (
                        "macOS USB interface is locked (e00002be). Enable USB Debugging on phone or use Wi-Fi QR."
                    )
                result = subprocess.run(
                    [adb_bin, "devices", "-l"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=6,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )

            devices = DeviceManager._parse_devices_output(result.stdout)
            if any(d.get("state") == "device" for d in devices):
                DeviceManager._last_adb_diagnostic = ""
                for d in devices:
                    if d.get("state") == "device":
                        v, friendly = DeviceManager._query_device_brand_and_model(d["serial"])
                        if friendly:
                            d["model"] = friendly
                        if v:
                            d["vendor"] = v
                        DeviceManager.save_known_device(
                            serial=d["serial"],
                            model=d.get("model", ""),
                            vendor=d.get("vendor", ""),
                        )

            # If any device is offline or no ready device found when auto_reconnect is requested, try adb reconnect
            has_offline = any(d["state"] == "offline" for d in devices)
            if has_offline or (auto_reconnect and (not devices or any(d["state"] != "device" for d in devices))):
                try:
                    subprocess.run(
                        [adb_bin, "reconnect", "offline"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=4,
                        env=env,
                        **subprocess_windowless_kwargs(),
                    )
                    if auto_reconnect and not devices:
                        DeviceManager.auto_connect_discovered_wireless_devices(timeout=1.2)
                    result2 = subprocess.run(
                        [adb_bin, "devices", "-l"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=6,
                        env=env,
                        **subprocess_windowless_kwargs(),
                    )
                    devices = DeviceManager._parse_devices_output(result2.stdout)
                    for d in devices:
                        if d.get("state") == "device":
                            v, friendly = DeviceManager._query_device_brand_and_model(d["serial"])
                            if friendly:
                                d["model"] = friendly
                            if v:
                                d["vendor"] = v
                            DeviceManager.save_known_device(
                                serial=d["serial"],
                                model=d.get("model", ""),
                                vendor=d.get("vendor", ""),
                            )
                except Exception:
                    pass

            # If ADB sees 0 devices, check if a physical Android phone (e.g. Tecno Camon 20 Pro / Samsung) is plugged into USB
            if not devices:
                usb_hw = DeviceManager.detect_physical_usb_android_devices()
                for hw in usb_hw:
                    hw_state = "usb_adb_locked" if hw.get("has_adb_interface") == "true" else "usb_debugging_off"
                    devices.append(
                        {
                            "serial": hw["serial"],
                            "state": hw_state,
                            "model": hw["model"],
                            "vendor": hw.get("vendor", "Android"),
                            "raw": f"{hw['serial']} {hw_state} model:{hw['model']}",
                        }
                    )

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
                raw_model = ""
                if "model:" in extras:
                    raw_model = extras.split("model:")[1].split()[0]
                elif "device:" in extras:
                    raw_model = extras.split("device:")[1].split()[0]

                vendor, friendly_model = DeviceManager.resolve_friendly_model_and_vendor(
                    serial=serial,
                    raw_model=raw_model,
                )

                devices.append(
                    {
                        "serial": serial,
                        "state": state,
                        "model": friendly_model,
                        "vendor": vendor,
                        "raw": stripped,
                    }
                )
        return devices

    @staticmethod
    def restart_adb_server() -> Tuple[bool, str, List[Dict[str, str]]]:
        """
        Ensures ADB is installed, updates `~/.android/adb_usb.ini` with Tecno/Transsion Vendor IDs,
        releases macOS ptpcamerad USB locks, restarts ADB with `ADB_MDNS_OPENSCREEN=1` and `ADB_LIBUSB=1`
        (bypassing macOS Sequoia/Sonoma `usb_osx.cpp:168 e00002be` interface lock), and auto-connects
        any paired wireless debugging phones.
        """
        DeviceManager.ensure_adb_usb_ini()
        adb_bin = resolve_adb_binary(auto_download=True)
        if not os.path.isfile(adb_bin):
            downloaded = download_official_adb_if_missing(force=True)
            if downloaded:
                adb_bin = downloaded

        info = get_os_arch_info()
        if info["is_macos"] and os.path.isfile(adb_bin) and os.path.isfile("/usr/bin/xattr"):
            try:
                subprocess.run(
                    ["/usr/bin/xattr", "-d", "com.apple.quarantine", adb_bin],
                    capture_output=True,
                    timeout=2,
                )
            except Exception:
                pass

        try:
            env = os.environ.copy()
            env["ADB_MDNS_OPENSCREEN"] = "1"
            if info["is_macos"]:
                # On macOS, ADB_LIBUSB=1 avoids usb_osx.cpp:168 (e00002be) exclusive plug-in failure
                env["ADB_LIBUSB"] = "1"

            subprocess.run(
                [adb_bin, "kill-server"],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
                **subprocess_windowless_kwargs(),
            )
            DeviceManager._force_kill_hung_adb()

            start_res = subprocess.run(
                [adb_bin, "start-server"],
                capture_output=True,
                text=True,
                timeout=8,
                env=env,
                **subprocess_windowless_kwargs(),
            )
            DeviceManager._mdns_server_ensured = True
            combined_log = f"{start_res.stdout or ''}\n{start_res.stderr or ''}".strip()

            devices = DeviceManager.get_connected_devices(auto_reconnect=True)
            real_adb_devices = [
                d for d in devices if not d.get("state", "").startswith("usb_")
            ]

            # If macOS still sees 0 USB ADB devices, also test ADB_LIBUSB=0 briefly and revert to ADB_LIBUSB=1 if 0 fails
            if not real_adb_devices and not info["is_windows"]:
                for libusb_val in ("0", "1"):
                    subprocess.run(
                        [adb_bin, "kill-server"],
                        capture_output=True,
                        text=True,
                        timeout=4,
                        env=env,
                        **subprocess_windowless_kwargs(),
                    )
                    DeviceManager._force_kill_hung_adb()
                    alt_env = env.copy()
                    alt_env["ADB_LIBUSB"] = libusb_val
                    alt_res = subprocess.run(
                        [adb_bin, "start-server"],
                        capture_output=True,
                        text=True,
                        timeout=8,
                        env=alt_env,
                        **subprocess_windowless_kwargs(),
                    )
                    alt_log = f"{alt_res.stdout or ''}\n{alt_res.stderr or ''}".strip()
                    if alt_log:
                        combined_log = f"{combined_log}\n[ADB_LIBUSB={libusb_val}] {alt_log}".strip()
                    devices = DeviceManager.get_connected_devices(auto_reconnect=False)
                    real_adb_devices = [
                        d for d in devices if not d.get("state", "").startswith("usb_")
                    ]
                    if real_adb_devices:
                        break

            if not real_adb_devices:
                wireless_connected = DeviceManager.auto_connect_discovered_wireless_devices(timeout=1.5)
                if wireless_connected:
                    devices = DeviceManager.get_connected_devices(auto_reconnect=False)

            return True, combined_log, devices
        except Exception as e:
            logger.error(f"Error restarting ADB server: {e}")
            return False, str(e), []

    @staticmethod
    def _parse_adb_mdns_output(stdout_text: str) -> Dict[str, List[Dict[str, str]]]:
        """
        Parses `adb mdns services` output into pairing and connect lists.
        """
        result: Dict[str, List[Dict[str, str]]] = {"pairing": [], "connect": []}
        if not stdout_text:
            return result

        ip_port_re = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})")
        for raw_line in stdout_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("List of discovered"):
                continue
            m = ip_port_re.search(line)
            if not m:
                continue
            ip, port = m.group(1), m.group(2)
            parts = line.split()
            instance_name = parts[0] if parts else ""
            entry = {
                "instance": instance_name,
                "ip": ip,
                "port": port,
                "ip_port": f"{ip}:{port}",
            }
            if "_adb-tls-pairing._tcp" in line:
                if not any(x["ip_port"] == entry["ip_port"] for x in result["pairing"]):
                    result["pairing"].append(entry)
            elif "_adb-tls-connect._tcp" in line:
                if not any(x["ip_port"] == entry["ip_port"] for x in result["connect"]):
                    result["connect"].append(entry)
        return result

    @staticmethod
    def _get_local_lan_ipv4_addresses() -> List[str]:
        """
        Returns all active private LAN IPv4 addresses on the machine (e.g. Wi-Fi `192.168.x.x`),
        ensuring UDP multicast mDNS packets are transmitted over the Wi-Fi interface rather than
        a USB modem interface.
        """
        ips: List[str] = []
        try:
            # Fast UDP connect probe to determine primary outbound Wi-Fi/LAN IP
            for probe_target in (("8.8.8.8", 80), ("192.168.1.1", 80), ("192.168.0.1", 80), ("10.0.0.1", 80)):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.settimeout(0.2)
                    s.connect(probe_target)
                    ip = s.getsockname()[0]
                    s.close()
                    if ip and not ip.startswith("127.") and ip not in ips:
                        ips.append(ip)
                except Exception:
                    pass
        except Exception:
            pass

        if os.path.isfile("/sbin/ifconfig"):
            try:
                res = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True, timeout=2)
                for m in re.finditer(r"inet\s+(\d{1,3}(?:\.\d{1,3}){3})", res.stdout or ""):
                    ip = m.group(1)
                    if not ip.startswith("127.") and not ip.startswith("169.254.") and ip not in ips:
                        ips.append(ip)
            except Exception:
                pass
        return ips

    @staticmethod
    def _build_mdns_query_packet(queries: List[Tuple[str, int]]) -> bytes:
        """
        Builds a multi-question DNS query packet where each item in `queries` is `(fqdn, qtype)`.
        Supports PTR (12), SRV (33), A (1), and ANY (255).
        """
        header = struct.pack("!HHHHHH", 0, 0, len(queries) * 2, 0, 0, 0)
        questions = bytearray()
        for fqdn, qtype in queries:
            encoded_name = bytearray()
            for label in fqdn.strip(".").split("."):
                enc = label.encode("utf-8")
                encoded_name.append(len(enc))
                encoded_name.extend(enc)
            encoded_name.append(0)
            # Ask for both unicast response (0x8001) and standard multicast response (0x0001)
            questions.extend(encoded_name)
            questions.extend(struct.pack("!HH", qtype, 0x8001))
            questions.extend(encoded_name)
            questions.extend(struct.pack("!HH", qtype, 0x0001))
        return header + bytes(questions)

    @staticmethod
    def _read_dns_name(packet: bytes, offset: int) -> Tuple[str, int]:
        labels: List[str] = []
        jumped = False
        orig_next_offset = offset
        visited = set()
        while offset < len(packet):
            if offset in visited:
                break
            visited.add(offset)
            length = packet[offset]
            if length == 0:
                offset += 1
                if not jumped:
                    orig_next_offset = offset
                break
            if (length & 0xC0) == 0xC0:
                if offset + 1 >= len(packet):
                    break
                ptr = ((length & 0x3F) << 8) | packet[offset + 1]
                if not jumped:
                    orig_next_offset = offset + 2
                    jumped = True
                offset = ptr
            else:
                offset += 1
                if offset + length > len(packet):
                    break
                labels.append(packet[offset : offset + length].decode("utf-8", errors="replace"))
                offset += length
                if not jumped:
                    orig_next_offset = offset
        return ".".join(labels), orig_next_offset

    @staticmethod
    def _parse_mdns_response_packet(
        packet: bytes, sender_ip: str
    ) -> Tuple[Dict[str, List[Dict[str, str]]], List[str]]:
        """
        Parses raw mDNS UDP response packets for `_adb-tls-pairing._tcp` and `_adb-tls-connect._tcp`
        PTR (type 12), SRV (type 33), and A (type 1) records.
        Returns `(found_endpoints, discovered_ptr_fqdns)`.
        """
        found: Dict[str, List[Dict[str, str]]] = {"pairing": [], "connect": []}
        ptr_fqdns: List[str] = []
        if len(packet) < 12:
            return found, ptr_fqdns

        try:
            _, _, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", packet[:12])
            offset = 12
            for _ in range(qdcount):
                _, offset = DeviceManager._read_dns_name(packet, offset)
                offset += 4
                if offset > len(packet):
                    return found, ptr_fqdns

            total_rr = ancount + nscount + arcount
            srv_records: List[Tuple[str, int, str]] = []
            a_records: Dict[str, str] = {}

            for _ in range(total_rr):
                if offset >= len(packet):
                    break
                rr_name, offset = DeviceManager._read_dns_name(packet, offset)
                if offset + 10 > len(packet):
                    break
                rtype, _, _, rdlength = struct.unpack("!HHIH", packet[offset : offset + 10])
                offset += 10
                rdata_end = offset + rdlength
                if rdata_end > len(packet):
                    break

                if rtype == 12:  # PTR record -> target service instance FQDN
                    ptr_target, _ = DeviceManager._read_dns_name(packet, offset)
                    if "_adb-tls-" in ptr_target.lower() and ptr_target not in ptr_fqdns:
                        ptr_fqdns.append(ptr_target)
                elif rtype == 33 and rdlength >= 6:  # SRV record
                    _, _, port = struct.unpack("!HHH", packet[offset : offset + 6])
                    target_host, _ = DeviceManager._read_dns_name(packet, offset + 6)
                    srv_records.append((rr_name, port, target_host))
                elif rtype == 1 and rdlength == 4:  # IPv4 A record
                    ip_str = socket.inet_ntoa(packet[offset : offset + 4])
                    a_records[rr_name.lower()] = ip_str

                offset = rdata_end

            for rr_name, port, target_host in srv_records:
                lower_name = rr_name.lower()
                ip = a_records.get(target_host.lower(), "") or sender_ip
                if not ip or ip.startswith("127."):
                    continue
                instance = rr_name.split("._adb-tls-")[0]
                entry = {
                    "instance": instance,
                    "ip": ip,
                    "port": str(port),
                    "ip_port": f"{ip}:{port}",
                }
                if "_adb-tls-pairing._tcp" in lower_name:
                    if not any(x["ip_port"] == entry["ip_port"] for x in found["pairing"]):
                        found["pairing"].append(entry)
                elif "_adb-tls-connect._tcp" in lower_name:
                    if not any(x["ip_port"] == entry["ip_port"] for x in found["connect"]):
                        found["connect"].append(entry)
        except Exception:
            pass
        return found, ptr_fqdns

    @staticmethod
    def _get_arp_neighbor_ips() -> List[str]:
        """
        Returns IPv4 addresses from the system ARP table (`/usr/sbin/arp -an` on macOS, `arp -a` on Windows)
        so we can send direct unicast mDNS queries to `(neighbor_ip, 5353)`, bypassing Wi-Fi router multicast filtering.
        """
        neighbors: List[str] = []
        cmd = ["/usr/sbin/arp", "-an"] if os.path.isfile("/usr/sbin/arp") else ["arp", "-a"]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2,
                **subprocess_windowless_kwargs(),
            )
            for m in re.finditer(r"\(?(\d{1,3}(?:\.\d{1,3}){3})\)?", res.stdout or ""):
                ip = m.group(1)
                if (
                    not ip.startswith("127.")
                    and not ip.startswith("169.254.")
                    and not ip.startswith("224.")
                    and not ip.startswith("239.")
                    and not ip.endswith(".255")
                    and ip not in neighbors
                ):
                    neighbors.append(ip)
        except Exception:
            pass
        return neighbors

    @staticmethod
    def _discover_via_udp_mdns(
        timeout: float = 1.0, expected_service_name: str = "", full_subnet_sweep: bool = True
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Multi-interface Pure-Python UDP mDNS scanner for `_adb-tls-pairing._tcp.local`
        and `_adb-tls-connect._tcp.local`:
          1. Sends multicast mDNS queries to `224.0.0.251:5353` on every active LAN interface.
          2. Sends direct UNICAST mDNS queries (`QCLASS=0x8001`) to `(neighbor_ip, 5353)` for all ARP
             neighbors AND across the local `/24` Wi-Fi subnet (`192.168.x.1..254:5353`), completely
             bypassing router Wi-Fi multicast isolation and macOS port 5353 sharing restrictions!
        """
        result: Dict[str, List[Dict[str, str]]] = {"pairing": [], "connect": []}
        mcast_grp = "224.0.0.251"
        mcast_port = 5353

        queries: List[Tuple[str, int]] = [
            ("_adb-tls-pairing._tcp.local", 12),
            ("_adb-tls-pairing._tcp.local", 255),
            ("_adb-tls-connect._tcp.local", 12),
            ("_adb-tls-connect._tcp.local", 255),
        ]
        if expected_service_name:
            svc_fqdn = f"{expected_service_name}._adb-tls-pairing._tcp.local"
            queries.append((svc_fqdn, 33))
            queries.append((svc_fqdn, 255))

        query_pkt = DeviceManager._build_mdns_query_packet(queries)
        lan_ips = DeviceManager._get_local_lan_ipv4_addresses() or ["0.0.0.0"]
        arp_ips = DeviceManager._get_arp_neighbor_ips()
        sockets: List[socket.socket] = []

        try:
            for lan_ip in lan_ips:
                try:
                    s_ephem = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                    s_ephem.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
                    if lan_ip != "0.0.0.0":
                        s_ephem.setsockopt(
                            socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(lan_ip)
                        )
                        s_ephem.bind((lan_ip, 0))
                    s_ephem.setblocking(False)
                    sockets.append(s_ephem)
                except Exception:
                    pass

            # Shared 5353 multicast listener socket
            try:
                s_mcast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                s_mcast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    try:
                        s_mcast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except Exception:
                        pass
                s_mcast.bind(("", mcast_port))
                for lan_ip in lan_ips:
                    try:
                        iface_bytes = (
                            socket.inet_aton(lan_ip)
                            if lan_ip != "0.0.0.0"
                            else struct.pack("!I", socket.INADDR_ANY)
                        )
                        mreq = socket.inet_aton(mcast_grp) + iface_bytes
                        s_mcast.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    except Exception:
                        pass
                s_mcast.setblocking(False)
                sockets.append(s_mcast)
            except Exception:
                pass

            for sock in sockets:
                try:
                    sock.sendto(query_pkt, (mcast_grp, mcast_port))
                except Exception:
                    pass
                for nip in arp_ips:
                    try:
                        sock.sendto(query_pkt, (nip, mcast_port))
                    except Exception:
                        pass

            # Fast non-blocking unicast sweep across the local /24 subnet on port 5353
            if full_subnet_sweep and sockets:
                sweep_socks = [sockets[0]]
                if len(sockets) > 1 and sockets[-1] not in sweep_socks:
                    sweep_socks.append(sockets[-1])
                for lan_ip in lan_ips:
                    parts = lan_ip.split(".")
                    if len(parts) == 4 and parts[0] in ("192", "10", "172"):
                        prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
                        for host_id in range(1, 255):
                            target_ip = f"{prefix}.{host_id}"
                            if target_ip == lan_ip:
                                continue
                            for sw_sock in sweep_socks:
                                try:
                                    sw_sock.sendto(query_pkt, (target_ip, mcast_port))
                                except Exception:
                                    pass

            queried_ptrs = set()
            deadline = time.time() + max(timeout, 0.35)
            while time.time() < deadline:
                for sock in sockets:
                    try:
                        data, addr = sock.recvfrom(4096)
                        sender_ip = addr[0] if addr else ""
                        parsed, ptr_fqdns = DeviceManager._parse_mdns_response_packet(data, sender_ip)
                        for key in ("pairing", "connect"):
                            for item in parsed[key]:
                                if not any(x["ip_port"] == item["ip_port"] for x in result[key]):
                                    result[key].append(item)
                        new_ptrs = [p for p in ptr_fqdns if p not in queried_ptrs]
                        if new_ptrs:
                            queried_ptrs.update(new_ptrs)
                            followup_q = []
                            for pf in new_ptrs:
                                followup_q.append((pf, 33))
                                followup_q.append((pf, 255))
                            f_pkt = DeviceManager._build_mdns_query_packet(followup_q)
                            try:
                                sock.sendto(f_pkt, (mcast_grp, mcast_port))
                                if sender_ip:
                                    sock.sendto(f_pkt, (sender_ip, mcast_port))
                            except Exception:
                                pass
                    except BlockingIOError:
                        pass
                    except Exception:
                        pass
                if result["pairing"] and result["connect"]:
                    break
                time.sleep(0.04)
        except Exception:
            pass
        finally:
            for sock in sockets:
                try:
                    sock.close()
                except Exception:
                    pass
        return result

    @staticmethod
    def _run_dnssd_pty(args: List[str], duration: float = 0.55) -> str:
        """
        Runs macOS `/usr/bin/dns-sd` attached to a pseudo-terminal (`pty.openpty()`)
        so C stdio flushes every line immediately instead of block-buffering on a pipe!
        """
        if not os.path.isfile("/usr/bin/dns-sd"):
            return ""
        import pty

        master_fd = None
        proc = None
        output = bytearray()
        try:
            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen(
                ["/usr/bin/dns-sd"] + args,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)
            deadline = time.time() + max(duration, 0.25)
            while time.time() < deadline:
                rlist, _, _ = select.select([master_fd], [], [], 0.08)
                if rlist:
                    try:
                        chunk = os.read(master_fd, 4096)
                        if not chunk:
                            break
                        output.extend(chunk)
                    except OSError:
                        break
        except Exception:
            pass
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=0.5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except Exception:
                    pass
        return output.decode("utf-8", errors="replace")

    @staticmethod
    def _resolve_mdns_hostname_ipv4(host: str) -> str:
        clean_host = host.strip().rstrip(".")
        if not clean_host:
            return ""
        # 1. Try fast macOS dns-sd -G v4 via pty
        if os.path.isfile("/usr/bin/dns-sd"):
            out = DeviceManager._run_dnssd_pty(["-G", "v4", f"{clean_host}."], duration=0.4)
            for line in out.splitlines():
                if "Add" in line:
                    m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
                    if m and not m.group(1).startswith("127."):
                        return m.group(1)
        # 2. Standard socket IPv4 lookup
        for candidate in (clean_host, f"{clean_host}.local"):
            try:
                infos = socket.getaddrinfo(candidate, None, socket.AF_INET)
                for info in infos:
                    ip = info[4][0]
                    if ip and not ip.startswith("127."):
                        return ip
            except Exception:
                pass
        return ""

    @staticmethod
    def _discover_via_macos_dnssd(
        timeout: float = 0.9, expected_service_name: str = ""
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Uses macOS `/usr/bin/dns-sd` over an unbuffered `pty` to query Bonjour (`mDNSResponder`)
        for `_adb-tls-pairing._tcp` and `_adb-tls-connect._tcp`.
        """
        result: Dict[str, List[Dict[str, str]]] = {"pairing": [], "connect": []}
        if not os.path.isfile("/usr/bin/dns-sd"):
            return result

        # If we know the exact QR service name, also do a direct -L lookup for it!
        if expected_service_name:
            lookup_out = DeviceManager._run_dnssd_pty(
                ["-L", expected_service_name, "_adb-tls-pairing._tcp", "local."],
                duration=min(timeout * 0.5, 0.45),
            )
            # Example: studio-abc._adb-tls-pairing._tcp.local. can be reached at Android.local.:41823 (interface 14)
            reach_m = re.search(r"can be reached at\s+([^\s:]+):(\d{2,5})", lookup_out)
            if reach_m:
                host, port = reach_m.group(1).rstrip("."), reach_m.group(2)
                ip = DeviceManager._resolve_mdns_hostname_ipv4(host)
                if ip:
                    result["pairing"].append(
                        {
                            "instance": expected_service_name,
                            "ip": ip,
                            "port": port,
                            "ip_port": f"{ip}:{port}",
                        }
                    )

        for key, svc_type in (("pairing", "_adb-tls-pairing._tcp"), ("connect", "_adb-tls-connect._tcp")):
            stdout_text = DeviceManager._run_dnssd_pty(
                ["-Z", svc_type, "local."], duration=max(timeout * 0.5, 0.4)
            )
            # Also extract any inline A records from zone output
            inline_a: Dict[str, str] = {}
            for a_m in re.finditer(r"^(\S+?)\s+\d+\s+IN\s+A\s+(\d{1,3}(?:\.\d{1,3}){3})", stdout_text, re.MULTILINE):
                inline_a[a_m.group(1).rstrip(".").lower()] = a_m.group(2)

            srv_re = re.compile(
                r"^(\S+?)\." + re.escape(svc_type) + r"\.local\.\s+\d+\s+IN\s+SRV\s+\d+\s+\d+\s+(\d+)\s+(\S+)",
                re.MULTILINE,
            )
            for match in srv_re.finditer(stdout_text or ""):
                instance = match.group(1).replace("\\032", " ")
                port = match.group(2)
                host = match.group(3).rstrip(".")
                ip = inline_a.get(host.lower(), "") or DeviceManager._resolve_mdns_hostname_ipv4(host)
                if ip and not ip.startswith("127."):
                    entry = {
                        "instance": instance,
                        "ip": ip,
                        "port": port,
                        "ip_port": f"{ip}:{port}",
                    }
                    if not any(x["ip_port"] == entry["ip_port"] for x in result[key]):
                        result[key].append(entry)
        return result

    @staticmethod
    def discover_mdns_adb_services(
        timeout: float = 1.5, expected_service_name: str = ""
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Discovers Android 11+ Wireless Debugging mDNS services (`_adb-tls-pairing._tcp` and `_adb-tls-connect._tcp`)
        across the local Wi-Fi network using a 3-tier cascade:
          1. `adb mdns services` (with `ADB_MDNS_OPENSCREEN=1` ensured)
          2. Multi-interface Pure-Python UDP Multicast mDNS query (`224.0.0.251:5353`)
          3. Unbuffered `pty` macOS `/usr/bin/dns-sd` Bonjour lookup
        """
        DeviceManager.ensure_adb_mdns_server()
        combined: Dict[str, List[Dict[str, str]]] = {"pairing": [], "connect": []}

        def _merge(source: Dict[str, List[Dict[str, str]]]):
            for k in ("pairing", "connect"):
                for item in source.get(k, []):
                    if not any(x["ip_port"] == item["ip_port"] for x in combined[k]):
                        combined[k].append(item)

        # Tier 1: `adb mdns services`
        adb_bin = resolve_adb_binary(auto_download=False)
        if os.path.isfile(adb_bin):
            try:
                env = os.environ.copy()
                env["ADB_MDNS_OPENSCREEN"] = "1"
                res = subprocess.run(
                    [adb_bin, "mdns", "services"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=3,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )
                _merge(DeviceManager._parse_adb_mdns_output(res.stdout))
            except Exception:
                pass

        # Tier 2: Multi-interface Pure-Python UDP Multicast mDNS
        _merge(
            DeviceManager._discover_via_udp_mdns(
                timeout=min(timeout, 0.85), expected_service_name=expected_service_name
            )
        )

        # Tier 3: Unbuffered pty macOS Bonjour dns-sd
        if os.path.isfile("/usr/bin/dns-sd"):
            _merge(
                DeviceManager._discover_via_macos_dnssd(
                    timeout=min(timeout, 0.85), expected_service_name=expected_service_name
                )
            )

        return combined

    @staticmethod
    def _is_tcp_endpoint_reachable(ip_port: str, timeout: float = 0.55) -> bool:
        """
        Fast non-blocking TCP handshake check so stale Bonjour/mDNS cache entries
        (e.g. a phone's old DHCP IP) are skipped in <0.55s instead of hanging `adb pair`/`adb connect` for 10s.
        """
        if not ip_port or ":" not in ip_port:
            return False
        host, port_s = ip_port.rsplit(":", 1)
        try:
            port = int(port_s)
            with socket.create_connection((host.strip(), port), timeout=timeout):
                return True
        except Exception:
            return False

    @staticmethod
    def auto_connect_discovered_wireless_devices(timeout: float = 1.2) -> List[str]:
        """
        Discovers any active `_adb-tls-connect._tcp` wireless debugging endpoints on Wi-Fi
        (plus saved endpoints and ARP neighbor port 5555 endpoints) and runs `adb connect <ip:port>`
        on reachable endpoints automatically.
        """
        connected_endpoints: List[str] = []
        adb_bin = resolve_adb_binary(auto_download=False)
        if not os.path.isfile(adb_bin):
            return connected_endpoints

        services = DeviceManager.discover_mdns_adb_services(timeout=timeout)
        env = os.environ.copy()
        env["ADB_MDNS_OPENSCREEN"] = "1"
        if get_os_arch_info()["is_macos"]:
            env["ADB_LIBUSB"] = "1"

        candidates = [item.get("ip_port", "") for item in services.get("connect", []) if item.get("ip_port")]
        for saved in DeviceManager.get_saved_devices():
            saved_ipp = saved.get("ip_port", "") or (saved.get("serial", "") if ":" in saved.get("serial", "") else "")
            if saved_ipp and saved_ipp not in candidates:
                candidates.append(saved_ipp)

        # Also check ARP neighbor IPs for standard TCP ADB port 5555 (fast 0.15s probe)
        for nip in DeviceManager._get_arp_neighbor_ips()[:12]:
            cand_5555 = f"{nip}:5555"
            if cand_5555 not in candidates and DeviceManager._is_tcp_endpoint_reachable(cand_5555, timeout=0.15):
                candidates.append(cand_5555)

        for ip_port in candidates:
            if not ip_port:
                continue
            if not DeviceManager._is_tcp_endpoint_reachable(ip_port, timeout=0.45):
                continue
            try:
                res = subprocess.run(
                    [adb_bin, "connect", ip_port],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )
                out = f"{res.stdout or ''}\n{res.stderr or ''}".lower()
                if "connected to" in out or "already connected" in out:
                    connected_endpoints.append(ip_port)
            except Exception:
                pass
        return connected_endpoints

    @staticmethod
    def pair_and_connect_qr_service(
        expected_service_name: str,
        password: str,
        paired_ips: Optional[set] = None,
    ) -> Tuple[bool, str, List[Dict[str, str]], Dict[str, List[Dict[str, str]]]]:
        """
        Polls mDNS for a phone scanning our QR code (`WIFI:T:ADB;S:<expected_service_name>;P:<password>;;`).
        When `_adb-tls-pairing._tcp` appears on the Wi-Fi network:
          1. Runs `adb pair <ip:pair_port> <password>` (prioritizing reachable TCP endpoints)
          2. Polls for `<ip:connect_port>` from `_adb-tls-connect._tcp` and runs `adb connect <ip:connect_port>`
          3. Always checks `get_connected_devices()` so `adb` OpenScreen auto-connections are detected immediately.
        """
        adb_bin = resolve_adb_binary(auto_download=True)
        env = os.environ.copy()
        env["ADB_MDNS_OPENSCREEN"] = "1"
        if get_os_arch_info()["is_macos"]:
            env["ADB_LIBUSB"] = "1"

        services = DeviceManager.discover_mdns_adb_services(
            timeout=1.1, expected_service_name=expected_service_name
        )
        logs: List[str] = []

        pairing_list = services.get("pairing", [])
        ordered_pairing = sorted(
            pairing_list,
            key=lambda x: (
                0 if expected_service_name.lower() in x.get("instance", "").lower() else 1,
                0 if DeviceManager._is_tcp_endpoint_reachable(x.get("ip_port", ""), timeout=0.5) else 1,
            ),
        )

        paired_ip = None
        for idx_p, p_item in enumerate(ordered_pairing):
            pair_ip_port = p_item["ip_port"]
            # Skip unreachable stale Bonjour cache IPs if there are other candidates
            if len(ordered_pairing) > 1 and not DeviceManager._is_tcp_endpoint_reachable(pair_ip_port, timeout=0.55):
                logs.append(f"Skipped stale/unreachable pairing cache ({pair_ip_port})")
                continue
            try:
                pair_res = subprocess.run(
                    [adb_bin, "pair", pair_ip_port, password],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )
                pair_out = f"{pair_res.stdout or ''}\n{pair_res.stderr or ''}".strip()
                logs.append(f"Pair ({pair_ip_port}): {pair_out}")
                if "successfully paired" in pair_out.lower():
                    paired_ip = p_item["ip"]
                    if paired_ips is not None:
                        paired_ips.add(paired_ip)
                    break
            except Exception as e:
                logs.append(f"Pair error ({pair_ip_port}): {e}")

        target_ips = set()
        if paired_ip:
            target_ips.add(paired_ip)
        if paired_ips:
            target_ips.update(paired_ips)

        # If we just paired, poll up to 3 times (0.5s apart) for the phone's _adb-tls-connect._tcp port to come up
        if paired_ip and not services.get("connect"):
            for _ in range(3):
                time.sleep(0.5)
                services = DeviceManager.discover_mdns_adb_services(timeout=1.0)
                if services.get("connect"):
                    break

        connect_list = services.get("connect", [])
        for c_item in connect_list:
            c_ip_port = c_item["ip_port"]
            if target_ips and c_item["ip"] not in target_ips and len(connect_list) > 1:
                continue
            if len(connect_list) > 1 and not DeviceManager._is_tcp_endpoint_reachable(c_ip_port, timeout=0.55):
                continue
            try:
                conn_res = subprocess.run(
                    [adb_bin, "connect", c_ip_port],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=6,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )
                conn_out = f"{conn_res.stdout or ''}\n{conn_res.stderr or ''}".strip()
                logs.append(f"Connect ({c_ip_port}): {conn_out}")
            except Exception as e:
                logs.append(f"Connect error ({c_ip_port}): {e}")

        # Always check connected ADB devices on every pass (catches ADB_MDNS_OPENSCREEN auto-connections too!)
        devices = DeviceManager.get_connected_devices(auto_reconnect=False)
        ready = [d for d in devices if d.get("state") == "device"]
        if ready:
            return True, "\n".join(logs), devices, services

        return False, "\n".join(logs), devices, services

    @staticmethod
    def connect_wireless_adb(
        connect_ip_port: str,
        pair_ip_port: str = "",
        pair_code: str = "",
    ) -> Tuple[bool, str, List[Dict[str, str]]]:
        """
        Pairs (optional, for Android 11+ Wireless Debugging) and connects to a phone
        over Wi-Fi (`adb pair <ip:port> <code>` + `adb connect <ip:port>`).
        """
        adb_bin = resolve_adb_binary(auto_download=True)
        env = os.environ.copy()
        env["ADB_MDNS_OPENSCREEN"] = "1"
        logs = []
        try:
            if pair_ip_port.strip() and pair_code.strip():
                pair_res = subprocess.run(
                    [adb_bin, "pair", pair_ip_port.strip(), pair_code.strip()],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )
                pair_out = f"{pair_res.stdout or ''}\n{pair_res.stderr or ''}".strip()
                logs.append(f"Pair: {pair_out}")

            conn_target = connect_ip_port.strip()
            if not conn_target and pair_ip_port.strip():
                pair_ip = pair_ip_port.strip().split(":")[0]
                for _ in range(3):
                    services = DeviceManager.discover_mdns_adb_services(timeout=1.0)
                    for c_item in services.get("connect", []):
                        if c_item.get("ip") == pair_ip:
                            conn_target = c_item["ip_port"]
                            break
                    if conn_target:
                        break
                    time.sleep(0.4)

            if conn_target:
                conn_res = subprocess.run(
                    [adb_bin, "connect", conn_target],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                    **subprocess_windowless_kwargs(),
                )
                conn_out = f"{conn_res.stdout or ''}\n{conn_res.stderr or ''}".strip()
                logs.append(f"Connect: {conn_out}")
            else:
                conn_out = ""

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
