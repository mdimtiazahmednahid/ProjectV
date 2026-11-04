import logging
import os
import re
import socket
import struct
import subprocess
import time
from typing import Dict, List, Optional, Tuple
from app.utils.platform_binaries import (
    download_official_adb_if_missing,
    get_os_arch_info,
    resolve_adb_binary,
    subprocess_windowless_kwargs,
)

logger = logging.getLogger(__name__)


class DeviceManager:
    _last_adb_diagnostic: str = ""

    @classmethod
    def get_last_diagnostic(cls) -> str:
        return cls._last_adb_diagnostic

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
            if "e00002be" in combined.lower() or "unable to create an interface plug-in" in combined.lower():
                DeviceManager._last_adb_diagnostic = (
                    "macOS USB interface is locked by another app (e00002be) or USB cable needs re-plugging. "
                    "Tip: Close Android File Transfer / Chrome / scrcpy, or click '📶 Wi-Fi Phone' to connect by scanning a QR code."
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
                env = os.environ.copy()
                env.setdefault("ADB_MDNS_OPENSCREEN", "1")
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
                start_combined = f"{start_res.stdout or ''}\n{start_res.stderr or ''}"
                if "e00002be" in start_combined.lower():
                    DeviceManager._last_adb_diagnostic = (
                        "macOS USB interface is locked (e00002be). Retrying with IOKit/libusb toggle or use '📶 Wi-Fi Phone' QR scan."
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
                        **subprocess_windowless_kwargs(),
                    )
                    # Also try auto-connecting any already-paired wireless _adb-tls-connect._tcp services on Wi-Fi
                    if auto_reconnect and not devices:
                        DeviceManager.auto_connect_discovered_wireless_devices(timeout=1.2)
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
        starts a clean ADB server (with macOS libusb/IOKit fallback if e00002be occurs),
        auto-connects any paired Wi-Fi debugging phones, and scans for connected phones.
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

            env = os.environ.copy()
            env["ADB_MDNS_OPENSCREEN"] = "1"
            start_res = subprocess.run(
                [adb_bin, "start-server"],
                capture_output=True,
                text=True,
                timeout=8,
                env=env,
                **subprocess_windowless_kwargs(),
            )
            combined_log = f"{start_res.stdout or ''}\n{start_res.stderr or ''}".strip()

            devices = DeviceManager.get_connected_devices(auto_reconnect=True)

            # If macOS USB interface error (e00002be) occurred and no devices were found, retry with ADB_LIBUSB=0 then 1
            if not devices and ("e00002be" in combined_log.lower() or not get_os_arch_info()["is_windows"]):
                for libusb_val in ("0", "1"):
                    subprocess.run(
                        [adb_bin, "kill-server"],
                        capture_output=True,
                        text=True,
                        timeout=4,
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
                    if devices:
                        break

            # Also check for already-paired wireless debugging phones on the same Wi-Fi
            if not devices:
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
        Example line:
          studio-fcv12345	_adb-tls-pairing._tcp.	192.168.1.25:41823
          adb-R58M42-xyz	_adb-tls-connect._tcp.	192.168.1.25:38192
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
    def _build_mdns_query_packet(service_names: List[str]) -> bytes:
        header = struct.pack("!HHHHHH", 0, 0, len(service_names), 0, 0, 0)
        questions = bytearray()
        for fqdn in service_names:
            for label in fqdn.strip(".").split("."):
                enc = label.encode("utf-8")
                questions.append(len(enc))
                questions.extend(enc)
            questions.append(0)
            # QTYPE = PTR (12), QCLASS = IN (1) with unicast-response bit (0x8001) + multicast fallback
            questions.extend(struct.pack("!HH", 12, 0x8001))
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
    def _parse_mdns_response_packet(packet: bytes, sender_ip: str) -> Dict[str, List[Dict[str, str]]]:
        """
        Parses raw mDNS UDP response packets for `_adb-tls-pairing._tcp` and `_adb-tls-connect._tcp`
        SRV (type 33) and A (type 1) records.
        """
        found: Dict[str, List[Dict[str, str]]] = {"pairing": [], "connect": []}
        if len(packet) < 12:
            return found

        try:
            _, _, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", packet[:12])
            offset = 12
            for _ in range(qdcount):
                _, offset = DeviceManager._read_dns_name(packet, offset)
                offset += 4
                if offset > len(packet):
                    return found

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

                if rtype == 33 and rdlength >= 6:  # SRV record
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
        return found

    @staticmethod
    def _discover_via_udp_mdns(timeout: float = 1.0) -> Dict[str, List[Dict[str, str]]]:
        """
        Pure-Python UDP multicast mDNS scanner for `_adb-tls-pairing._tcp.local` and `_adb-tls-connect._tcp.local`.
        Works on both Windows and macOS without external tools.
        """
        result: Dict[str, List[Dict[str, str]]] = {"pairing": [], "connect": []}
        mcast_grp = "224.0.0.251"
        mcast_port = 5353
        query_pkt = DeviceManager._build_mdns_query_packet(
            ["_adb-tls-pairing._tcp.local", "_adb-tls-connect._tcp.local"]
        )
        sockets: List[socket.socket] = []
        try:
            # 1. Ephemeral unicast/multicast query socket
            s_ephem = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s_ephem.setblocking(False)
            sockets.append(s_ephem)

            # 2. Shared 5353 multicast listener socket (to catch multicast-only responses)
            try:
                s_mcast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                s_mcast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    try:
                        s_mcast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except Exception:
                        pass
                s_mcast.bind(("", mcast_port))
                mreq = struct.pack("4sl", socket.inet_aton(mcast_grp), socket.INADDR_ANY)
                s_mcast.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                s_mcast.setblocking(False)
                sockets.append(s_mcast)
            except Exception:
                pass

            for sock in sockets:
                try:
                    sock.sendto(query_pkt, (mcast_grp, mcast_port))
                except Exception:
                    pass

            deadline = time.time() + max(timeout, 0.3)
            while time.time() < deadline:
                for sock in sockets:
                    try:
                        data, addr = sock.recvfrom(4096)
                        sender_ip = addr[0] if addr else ""
                        parsed = DeviceManager._parse_mdns_response_packet(data, sender_ip)
                        for key in ("pairing", "connect"):
                            for item in parsed[key]:
                                if not any(x["ip_port"] == item["ip_port"] for x in result[key]):
                                    result[key].append(item)
                    except BlockingIOError:
                        pass
                    except Exception:
                        pass
                if result["pairing"] and result["connect"]:
                    break
                time.sleep(0.05)
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
    def _discover_via_macos_dnssd(timeout: float = 0.9) -> Dict[str, List[Dict[str, str]]]:
        """
        Uses macOS built-in `/usr/bin/dns-sd -Z` to query Bonjour/mDNS daemon directly.
        """
        result: Dict[str, List[Dict[str, str]]] = {"pairing": [], "connect": []}
        if not os.path.isfile("/usr/bin/dns-sd"):
            return result

        for key, svc_type in (("pairing", "_adb-tls-pairing._tcp"), ("connect", "_adb-tls-connect._tcp")):
            proc = None
            try:
                proc = subprocess.Popen(
                    ["/usr/bin/dns-sd", "-Z", svc_type, "local."],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                time.sleep(max(timeout * 0.5, 0.35))
                proc.terminate()
                stdout_text, _ = proc.communicate(timeout=1.0)
            except Exception:
                if proc:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                stdout_text = ""

            # Parse SRV lines like:
            # studio-fcv123._adb-tls-pairing._tcp.local. 4500 IN SRV 0 0 41823 Android.local.
            srv_re = re.compile(
                r"^(\S+?)\." + re.escape(svc_type) + r"\.local\.\s+\d+\s+IN\s+SRV\s+\d+\s+\d+\s+(\d+)\s+(\S+)",
                re.MULTILINE,
            )
            for match in srv_re.finditer(stdout_text or ""):
                instance = match.group(1).replace("\\032", " ")
                port = match.group(2)
                host = match.group(3).rstrip(".")
                ip = ""
                try:
                    ip = socket.gethostbyname(host)
                except Exception:
                    try:
                        ip = socket.gethostbyname(f"{host}.local")
                    except Exception:
                        pass
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
    def discover_mdns_adb_services(timeout: float = 1.5) -> Dict[str, List[Dict[str, str]]]:
        """
        Discovers Android 11+ Wireless Debugging mDNS services (`_adb-tls-pairing._tcp` and `_adb-tls-connect._tcp`)
        across the local Wi-Fi network using a 3-tier cascade:
          1. `adb mdns services`
          2. Pure-Python UDP Multicast mDNS query (`224.0.0.251:5353`)
          3. macOS `/usr/bin/dns-sd -Z` Bonjour lookup
        """
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
                res = subprocess.run(
                    [adb_bin, "mdns", "services"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=3,
                    **subprocess_windowless_kwargs(),
                )
                _merge(DeviceManager._parse_adb_mdns_output(res.stdout))
            except Exception:
                pass

        # Tier 2: Pure-Python UDP Multicast mDNS
        _merge(DeviceManager._discover_via_udp_mdns(timeout=min(timeout, 0.9)))

        # Tier 3: macOS Bonjour dns-sd fallback if pairing service not yet seen
        if not combined["pairing"] and os.path.isfile("/usr/bin/dns-sd"):
            _merge(DeviceManager._discover_via_macos_dnssd(timeout=min(timeout, 0.8)))

        return combined

    @staticmethod
    def auto_connect_discovered_wireless_devices(timeout: float = 1.2) -> List[str]:
        """
        Discovers any active `_adb-tls-connect._tcp` wireless debugging endpoints on Wi-Fi
        and runs `adb connect <ip:port>` on them automatically.
        """
        connected_endpoints: List[str] = []
        adb_bin = resolve_adb_binary(auto_download=False)
        if not os.path.isfile(adb_bin):
            return connected_endpoints

        services = DeviceManager.discover_mdns_adb_services(timeout=timeout)
        for item in services.get("connect", []):
            ip_port = item.get("ip_port", "")
            if not ip_port:
                continue
            try:
                res = subprocess.run(
                    [adb_bin, "connect", ip_port],
                    capture_output=True,
                    text=True,
                    timeout=5,
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
          1. Runs `adb pair <ip:pair_port> <password>`
          2. Discovers `<ip:connect_port>` from `_adb-tls-connect._tcp` (retrying briefly if needed)
          3. Runs `adb connect <ip:connect_port>`
          4. Returns `(ok, status_log, connected_devices, discovered_services)`
        """
        adb_bin = resolve_adb_binary(auto_download=True)
        services = DeviceManager.discover_mdns_adb_services(timeout=1.1)
        logs: List[str] = []

        pairing_list = services.get("pairing", [])
        # Prioritize exact service_name match from QR code, then any active pairing endpoint
        ordered_pairing = sorted(
            pairing_list,
            key=lambda x: 0 if expected_service_name.lower() in x.get("instance", "").lower() else 1,
        )

        paired_ip = None
        for p_item in ordered_pairing:
            pair_ip_port = p_item["ip_port"]
            try:
                pair_res = subprocess.run(
                    [adb_bin, "pair", pair_ip_port, password],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
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

        # If we just paired (or previously paired in this session), connect to _adb-tls-connect._tcp
        target_ips = set()
        if paired_ip:
            target_ips.add(paired_ip)
        if paired_ips:
            target_ips.update(paired_ips)

        if paired_ip and not services.get("connect"):
            time.sleep(0.5)
            services = DeviceManager.discover_mdns_adb_services(timeout=1.2)

        for c_item in services.get("connect", []):
            c_ip_port = c_item["ip_port"]
            if target_ips and c_item["ip"] not in target_ips and len(services["connect"]) > 1:
                continue
            try:
                conn_res = subprocess.run(
                    [adb_bin, "connect", c_ip_port],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    **subprocess_windowless_kwargs(),
                )
                conn_out = f"{conn_res.stdout or ''}\n{conn_res.stderr or ''}".strip()
                logs.append(f"Connect ({c_ip_port}): {conn_out}")
            except Exception as e:
                logs.append(f"Connect error ({c_ip_port}): {e}")

        if paired_ip or logs:
            devices = DeviceManager.get_connected_devices(auto_reconnect=False)
            ready = [d for d in devices if d.get("state") == "device"]
            if ready:
                return True, "\n".join(logs), devices, services

        return False, "\n".join(logs), [], services

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

            conn_target = connect_ip_port.strip()
            # If user paired with code but left connect port empty, auto-discover _adb-tls-connect._tcp on that IP!
            if not conn_target and pair_ip_port.strip():
                pair_ip = pair_ip_port.strip().split(":")[0]
                services = DeviceManager.discover_mdns_adb_services(timeout=1.2)
                for c_item in services.get("connect", []):
                    if c_item.get("ip") == pair_ip:
                        conn_target = c_item["ip_port"]
                        break

            if conn_target:
                conn_res = subprocess.run(
                    [adb_bin, "connect", conn_target],
                    capture_output=True,
                    text=True,
                    timeout=10,
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
