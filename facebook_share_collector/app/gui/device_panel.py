import random
import string
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from app.automation.adb_controller import ADBManager
from app.automation.appium_manager import AppiumManager
from app.automation.device_manager import DeviceManager
from app.utils.platform_binaries import get_os_arch_info
from app.utils.qr_code import render_qr_pixmap


class QrPairingWorker(QThread):
    """
    Background worker that continuously listens for Android 11+ Wireless Debugging
    mDNS broadcasts (`_adb-tls-pairing._tcp` and `_adb-tls-connect._tcp`) when the user
    scans the QR code displayed in `WirelessAdbDialog`.
    """

    status_update = Signal(str)
    connect_endpoint_discovered = Signal(str)
    paired_and_connected = Signal(str, str)

    def __init__(self, service_name: str, password: str, parent=None):
        super().__init__(parent)
        self.service_name = service_name
        self.password = password
        self._running = True
        self._paired_ips = set()

    def stop(self):
        self._running = False

    def update_credentials(self, service_name: str, password: str):
        self.service_name = service_name
        self.password = password

    def run(self):
        while self._running:
            try:
                ok, logs, devices, services = DeviceManager.pair_and_connect_qr_service(
                    self.service_name,
                    self.password,
                    paired_ips=self._paired_ips,
                )
                if not self._running:
                    break

                # Auto-fill Connect IP:Port field if any _adb-tls-connect._tcp service is seen on Wi-Fi
                connect_list = services.get("connect", [])
                if connect_list:
                    first_ip_port = connect_list[0].get("ip_port", "")
                    if first_ip_port:
                        self.connect_endpoint_discovered.emit(first_ip_port)

                pairing_list = services.get("pairing", [])
                if pairing_list and not ok:
                    self.status_update.emit(
                        f"📲 Phone QR scan detected ({pairing_list[0].get('ip_port')}) — Pairing & connecting..."
                    )

                if ok and devices:
                    ready = [d for d in devices if d.get("state") == "device"]
                    if ready:
                        serial = ready[0].get("serial", "")
                        self.paired_and_connected.emit(serial, logs)
                        break
            except Exception:
                pass

            for _ in range(8):
                if not self._running:
                    break
                self.msleep(100)


class WirelessAdbDialog(QDialog):
    """
    1-Click Wireless ADB Connection Dialog with Android 11+ QR Code Scanner
    (`WIFI:T:ADB;S:<service_name>;P:<password>;;`) + Manual IP:Port / 6-Digit Code fallback.
    Works without any USB cable or OEM USB driver!
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📶 Connect Phone via Wi-Fi (Scan QR Code or Enter IP:Port)")
        self.setMinimumWidth(620)
        self.qr_paired_and_connected = False
        self.connected_serial = ""
        self.qr_service_name = ""
        self.qr_password = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Top QR Code Card ---
        qr_frame = QFrame(self)
        qr_frame.setStyleSheet(
            "QFrame { background-color: #0f172a; border: 1px solid #334155; border-radius: 10px; padding: 10px; }"
        )
        qr_hbox = QHBoxLayout(qr_frame)
        qr_hbox.setSpacing(16)

        # Left column: QR image + Refresh QR button
        qr_left = QVBoxLayout()
        qr_left.setAlignment(Qt.AlignCenter)
        self.qr_image_label = QLabel()
        self.qr_image_label.setAlignment(Qt.AlignCenter)
        self.qr_image_label.setStyleSheet(
            "background-color: #ffffff; border: 4px solid #ffffff; border-radius: 8px; padding: 4px;"
        )
        qr_left.addWidget(self.qr_image_label, 0, Qt.AlignCenter)

        self.btn_refresh_qr = QPushButton("🔄 New QR Code")
        self.btn_refresh_qr.setStyleSheet(
            "background-color: #1e293b; color: #38bdf8; font-weight: bold; padding: 5px 10px; border-radius: 6px;"
        )
        self.btn_refresh_qr.clicked.connect(self._regenerate_qr_code)
        qr_left.addWidget(self.btn_refresh_qr, 0, Qt.AlignCenter)
        qr_hbox.addLayout(qr_left)

        # Right column: Step-by-step QR instructions + live scanner status
        qr_right = QVBoxLayout()
        qr_title = QLabel("<b>📷 Option 1 (Fastest): Scan QR Code from Your Phone</b>")
        qr_title.setStyleSheet("color: #38bdf8; font-size: 14px; border: none;")
        qr_right.addWidget(qr_title)

        qr_steps = QLabel(
            "1. Connect your <b>phone</b> and <b>computer</b> to the <b>same Wi-Fi network</b>.<br>"
            "2. On your phone, open <b>Settings → Developer Options → Wireless debugging</b> and turn it <b>ON</b>.<br>"
            "3. Tap <b>Pair device with QR code</b> and scan this QR code!<br>"
            "4. Your phone will pair and connect automatically within 2–3 seconds."
        )
        qr_steps.setWordWrap(True)
        qr_steps.setStyleSheet("color: #e2e8f0; font-size: 12px; border: none;")
        qr_right.addWidget(qr_steps)

        self.qr_status_label = QLabel("📡 Waiting for phone to scan QR code on Wi-Fi...")
        self.qr_status_label.setWordWrap(True)
        self.qr_status_label.setStyleSheet(
            "color: #fbbf24; font-weight: bold; font-size: 12px; padding: 6px; "
            "background-color: #1e293b; border-radius: 6px; border: 1px solid #475569;"
        )
        qr_right.addWidget(self.qr_status_label)

        self.qr_creds_label = QLabel("")
        self.qr_creds_label.setStyleSheet("color: #94a3b8; font-size: 11px; border: none;")
        qr_right.addWidget(self.qr_creds_label)
        qr_right.addStretch()
        qr_hbox.addLayout(qr_right, 1)

        layout.addWidget(qr_frame)

        # --- Manual Fallback Form ---
        manual_group = QGroupBox("⌨️ Option 2: Or Connect Manually with IP:Port & 6-Digit Pairing Code")
        manual_layout = QVBoxLayout(manual_group)
        form = QFormLayout()
        self.input_connect_ip = QLineEdit()
        self.input_connect_ip.setPlaceholderText("e.g. 192.168.1.50:41235 (Auto-filled if discovered on Wi-Fi)")

        self.input_pair_ip = QLineEdit()
        self.input_pair_ip.setPlaceholderText("Optional (first time): e.g. 192.168.1.50:38199")

        self.input_pair_code = QLineEdit()
        self.input_pair_code.setPlaceholderText("Optional (first time): e.g. 482910")

        form.addRow("Phone IP & Port:", self.input_connect_ip)
        form.addRow("Pairing IP & Port (Optional):", self.input_pair_ip)
        form.addRow("6-Digit Pairing Code (Optional):", self.input_pair_code)
        manual_layout.addLayout(form)
        layout.addWidget(manual_group)

        btn_row = QHBoxLayout()
        self.btn_connect = QPushButton("📶 Pair & Connect Manually")
        self.btn_connect.setStyleSheet(
            "background-color: #16a34a; color: white; font-weight: bold; padding: 8px 16px;"
        )
        self.btn_cancel = QPushButton("Cancel")
        self.btn_connect.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_connect)
        layout.addLayout(btn_row)

        self.qr_worker = None
        self._regenerate_qr_code()

    def _regenerate_qr_code(self):
        rand_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        self.qr_service_name = f"adb-{rand_id}"
        self.qr_password = "".join(random.choices(string.digits, k=6))
        qr_payload = f"WIFI:T:ADB;S:{self.qr_service_name};P:{self.qr_password};;"

        pixmap = render_qr_pixmap(qr_payload, target_size_px=260, quiet_zone=4)
        self.qr_image_label.setPixmap(pixmap)
        self.qr_creds_label.setText(
            f"QR Service: {self.qr_service_name}  |  Passcode: {self.qr_password}"
        )
        self.qr_status_label.setText("📡 Listening for phone QR scan on Wi-Fi (mDNS + LAN Auto-Scan)...")
        self.qr_status_label.setStyleSheet(
            "color: #fbbf24; font-weight: bold; font-size: 12px; padding: 6px; "
            "background-color: #1e293b; border-radius: 6px; border: 1px solid #475569;"
        )

        if self.qr_worker is None:
            self.qr_worker = QrPairingWorker(self.qr_service_name, self.qr_password, self)
            self.qr_worker.status_update.connect(self._on_qr_status_update)
            self.qr_worker.connect_endpoint_discovered.connect(self._on_connect_endpoint_discovered)
            self.qr_worker.paired_and_connected.connect(self._on_qr_paired_and_connected)
            self.qr_worker.start()
        else:
            self.qr_worker.update_credentials(self.qr_service_name, self.qr_password)

    def _on_qr_status_update(self, msg: str):
        self.qr_status_label.setText(msg)
        self.qr_status_label.setStyleSheet(
            "color: #38bdf8; font-weight: bold; font-size: 12px; padding: 6px; "
            "background-color: #1e293b; border-radius: 6px; border: 1px solid #0284c7;"
        )

    def _on_connect_endpoint_discovered(self, ip_port: str):
        if not self.input_connect_ip.text().strip():
            self.input_connect_ip.setText(ip_port)
            self.qr_status_label.setText(
                f"📡 Discovered phone on Wi-Fi ({ip_port})! Scan QR code to pair, or click 'Pair & Connect Manually'."
            )

    def _on_qr_paired_and_connected(self, serial: str, _logs: str):
        self.qr_paired_and_connected = True
        self.connected_serial = serial
        self.qr_status_label.setText(f"✅ Paired & Connected to {serial}!")
        self.qr_status_label.setStyleSheet(
            "color: #4ade80; font-weight: bold; font-size: 12px; padding: 6px; "
            "background-color: #14532d; border-radius: 6px; border: 1px solid #22c55e;"
        )
        self._stop_worker()
        self.accept()

    def _stop_worker(self):
        if self.qr_worker is not None:
            self.qr_worker.stop()
            self.qr_worker.wait(1500)
            self.qr_worker = None

    def accept(self):
        self._stop_worker()
        super().accept()

    def reject(self):
        self._stop_worker()
        super().reject()

    def closeEvent(self, event):
        self._stop_worker()
        super().closeEvent(event)


class DevicePanel(QGroupBox):
    # Signal emitted when a device is connected successfully
    device_connected = Signal(str)

    def __init__(self, appium_manager: AppiumManager, adb_manager: ADBManager = None, parent=None):
        super().__init__("Device & Zero-Setup Connection (Optional if using Browser Extension)", parent)
        self.appium_manager = appium_manager
        self.adb_manager = adb_manager or ADBManager()
        self.active_manager = self.adb_manager
        self._is_connected = False
        self._connected_serial = None
        self._last_device_signature = None

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # ADB Devices + Engine Mode
        adb_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.refresh_btn = QPushButton("Refresh Devices")
        self.refresh_btn.clicked.connect(lambda: self.refresh_devices(manual=True))

        self.restart_adb_btn = QPushButton("🔄 Fix / Install ADB")
        self.restart_adb_btn.setToolTip(
            "Automatically downloads official ADB if missing, restarts the ADB USB daemon, "
            "and scans for your plugged-in or Wi-Fi phone."
        )
        self.restart_adb_btn.clicked.connect(self.restart_adb_and_refresh)

        self.wifi_adb_btn = QPushButton("📶 Wi-Fi Phone (QR Scan)")
        self.wifi_adb_btn.setStyleSheet("font-weight: bold; color: #38bdf8;")
        self.wifi_adb_btn.setToolTip(
            "Connect your phone over Wi-Fi by scanning a QR code (Wireless Debugging) — "
            "works without any USB cable or Windows USB driver!"
        )
        self.wifi_adb_btn.clicked.connect(self.open_wireless_adb_dialog)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(
            [
                "Direct ADB Mode (Zero-Setup — No Appium Needed)",
                "Appium Server Mode (127.0.0.1:4723)",
            ]
        )

        adb_layout.addWidget(QLabel("Device:"))
        adb_layout.addWidget(self.device_combo, 1)
        adb_layout.addWidget(QLabel("Engine:"))
        adb_layout.addWidget(self.mode_combo)
        adb_layout.addWidget(self.refresh_btn)
        adb_layout.addWidget(self.restart_adb_btn)
        adb_layout.addWidget(self.wifi_adb_btn)

        # Connect Button
        conn_layout = QHBoxLayout()
        self.connect_btn = QPushButton("Connect Device")
        self.connect_btn.clicked.connect(self.connect_appium)
        self.status_label = QLabel("Status: DISCONNECTED")
        self.status_label.setStyleSheet("color: #f87171; font-weight: bold;")

        self.hint_label = QLabel(
            "💡 Using Chrome/Edge? You don't need a phone connected — "
            "use the Browser Extension / Bookmarklet below and batches auto-import!"
        )
        self.hint_label.setStyleSheet("color: #93c5fd; font-size: 11px;")

        conn_layout.addWidget(self.connect_btn)
        conn_layout.addWidget(self.status_label)
        conn_layout.addSpacing(12)
        conn_layout.addWidget(self.hint_label, 1)

        # URL Launcher
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.facebook.com/share/...")
        self.open_url_btn = QPushButton("Open URL on Phone")
        self.open_url_btn.clicked.connect(self.open_url)

        url_layout.addWidget(QLabel("Launch URL:"))
        url_layout.addWidget(self.url_input, 1)
        url_layout.addWidget(self.open_url_btn)

        self.layout.addLayout(adb_layout)
        self.layout.addLayout(url_layout)
        self.layout.addLayout(conn_layout)

        self.refresh_devices(manual=False)

        # Auto-poll every 3 seconds continuously so plugging in, unlocking, or disconnecting a phone updates live
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self._auto_poll_devices)
        self._poll_timer.start()

    def _auto_poll_devices(self):
        self.refresh_devices(manual=False)

    def refresh_devices(self, manual: bool = False):
        if manual and not DeviceManager.is_adb_binary_present():
            self.status_label.setText("Status: DOWNLOADING OFFICIAL GOOGLE ADB...")
            self.status_label.setStyleSheet("color: #fbbf24; font-weight: bold;")

        devices = DeviceManager.get_connected_devices(auto_reconnect=manual)
        ready_serials = {d.get("serial") for d in devices if d.get("state") == "device"}

        # Detect if previously connected device was unplugged or went offline
        if self._is_connected and self._connected_serial and self._connected_serial not in ready_serials:
            self._is_connected = False
            self._connected_serial = None
            self.connect_btn.setText("Connect Device")
            self.connect_btn.setEnabled(True)
            self.mode_combo.setEnabled(True)

        sig = tuple((d.get("serial"), d.get("state"), d.get("model")) for d in devices)
        if not manual and sig == self._last_device_signature and self.device_combo.count() > 0:
            # Even if signature didn't change, if a ready device is sitting disconnected in Direct ADB mode, auto-connect it
            if not self._is_connected and ready_serials and self.mode_combo.currentIndex() == 0:
                self.connect_appium(silent=True)
            return
        self._last_device_signature = sig

        prev_selected = self.device_combo.currentData()
        self.device_combo.clear()
        ready_count = 0
        pending_states = []

        for dev in devices:
            serial = dev["serial"]
            state = dev["state"]
            model = dev["model"]
            if state == "device":
                self.device_combo.addItem(f"✅ {model} ({serial})", serial)
                ready_count += 1
            elif state == "unauthorized":
                self.device_combo.addItem(
                    f"⚠️ {serial} (UNAUTHORIZED — Tap 'Allow USB Debugging' on phone)",
                    serial,
                )
                pending_states.append("unauthorized")
            elif state == "offline":
                self.device_combo.addItem(
                    f"⚠️ {serial} (OFFLINE — Click '🔄 Fix / Install ADB' or re-plug USB)",
                    serial,
                )
                pending_states.append("offline")
            elif state in ("usb_debugging_off", "usb_adb_locked"):
                self.device_combo.addItem(
                    f"🔌 {model} ({serial}) — USB Plugged In (Turn ON 'USB Debugging' on Phone or use Wi-Fi QR)",
                    f"usb_hw:{serial}:{model}",
                )
                pending_states.append((state, serial, model))
            else:
                self.device_combo.addItem(f"⏳ {serial} ({state})", serial)
                pending_states.append(state)

        # Restore previous selection if still present
        if prev_selected:
            idx = self.device_combo.findData(prev_selected)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)

        if self.device_combo.count() == 0:
            if not DeviceManager.is_adb_binary_present():
                self.device_combo.addItem(
                    "ADB not installed yet — Click '🔄 Fix / Install ADB' to auto-install",
                    None,
                )
                if not self._is_connected:
                    self.status_label.setText("Status: CLICK '🔄 Fix / Install ADB' TO ENABLE PHONE CONNECTION")
                    self.status_label.setStyleSheet("color: #fbbf24; font-weight: bold;")
            else:
                diag = DeviceManager.get_last_diagnostic()
                if diag:
                    self.device_combo.addItem(f"⚠️ {diag}", None)
                else:
                    self.device_combo.addItem(
                        "No phone detected (Check USB Debugging / File Transfer, or click '📶 Wi-Fi Phone (QR Scan)')",
                        None,
                    )
                if not self._is_connected:
                    self.status_label.setText(
                        "Status: NO PHONE DETECTED (Try '🔄 Fix / Install ADB' or '📶 Wi-Fi Phone (QR Scan)')"
                    )
                    self.status_label.setStyleSheet("color: #f87171; font-weight: bold;")
        elif not self._is_connected:
            if ready_count > 0:
                self.status_label.setText("Status: PHONE DETECTED — Connecting...")
                self.status_label.setStyleSheet("color: #fbbf24; font-weight: bold;")
                if self.mode_combo.currentIndex() == 0:
                    self.connect_appium(silent=True)
            elif "unauthorized" in pending_states:
                self.status_label.setText("Status: TAP 'ALLOW USB DEBUGGING' ON PHONE SCREEN")
                self.status_label.setStyleSheet("color: #fb923c; font-weight: bold;")
            elif any(isinstance(p, tuple) for p in pending_states):
                hw_tuple = next(p for p in pending_states if isinstance(p, tuple))
                _hw_state, hw_serial, hw_model = hw_tuple
                self.status_label.setText(
                    f"Status: {hw_model} ({hw_serial}) PLUGGED IN — Turn ON 'USB Debugging' on Phone or click '📶 Wi-Fi Phone (QR Scan)'"
                )
                self.status_label.setStyleSheet("color: #fb923c; font-weight: bold;")
            else:
                self.status_label.setText(
                    f"Status: DEVICE {str(pending_states[0]).upper()} — Click '🔄 Fix / Install ADB'"
                )
                self.status_label.setStyleSheet("color: #fb923c; font-weight: bold;")

    def restart_adb_and_refresh(self):
        self.status_label.setText("Status: PREPARING & RESTARTING ADB DAEMON...")
        self.status_label.setStyleSheet("color: #fbbf24; font-weight: bold;")
        ok, log_msg, devices = DeviceManager.restart_adb_server()
        self._last_device_signature = None
        self.refresh_devices(manual=True)

        ready_devices = [d for d in devices if d.get("state") in ("device", "unauthorized")]
        hw_only_devices = [d for d in devices if d.get("state") in ("usb_debugging_off", "usb_adb_locked")]

        if hw_only_devices and not ready_devices:
            hw = hw_only_devices[0]
            self._show_usb_debugging_prompt(hw.get("serial", ""), hw.get("model", "Android Phone"))
            return

        if not devices:
            info = get_os_arch_info()
            os_label = "Windows" if info["is_windows"] else "macOS"
            extra_hint = ""
            if info["is_windows"]:
                extra_hint = (
                    "\n\n💡 Windows Tip (No USB Driver Needed!):\n"
                    "If Windows is missing your phone brand's USB ADB driver (Samsung/Xiaomi/Oppo/Vivo), "
                    "click the '📶 Wi-Fi Phone (QR Scan)' button to connect by scanning a QR code!"
                )
            elif "e00002be" in log_msg or "Unable to create an interface plug-in" in log_msg:
                extra_hint = (
                    "\n\n⚠️ macOS USB Exclusive Lock Detected (e00002be):\n"
                    "Another app (like Chrome 'chrome://inspect', Android File Transfer, or Photos) "
                    "is holding exclusive access to your phone's USB port.\n"
                    "• Close any 'chrome://inspect' tab or Android File Transfer app, OR\n"
                    "• Click '📶 Wi-Fi Phone (QR Scan)' to connect over Wi-Fi by scanning a QR code!"
                )
            QMessageBox.information(
                self,
                "ADB Ready — No Phone Detected Yet",
                f"ADB Server is active, but {os_label} currently sees 0 Android ADB devices.\n\n"
                "Quick Checklist for your phone:\n"
                "1. Unlock your phone screen.\n"
                "2. Swipe down the top notification bar → tap the 'USB Charging this device' notification "
                "→ switch USB mode to 'File Transfer / Android Auto' or 'PTP'.\n"
                "3. Go to Settings → Developer Options → turn 'USB Debugging' ON.\n"
                "4. Tap 'Allow' on the 'Allow USB debugging?' popup on your phone.\n"
                "5. Or click '📶 Wi-Fi Phone (QR Scan)' to connect wirelessly by scanning a QR code!"
                f"{extra_hint}",
            )

    def open_wireless_adb_dialog(self):
        dlg = WirelessAdbDialog(self)
        if dlg.exec():
            if dlg.qr_paired_and_connected:
                self._last_device_signature = None
                self.refresh_devices(manual=True)
                if dlg.connected_serial:
                    idx = self.device_combo.findData(dlg.connected_serial)
                    if idx >= 0:
                        self.device_combo.setCurrentIndex(idx)
                self.connect_appium(silent=False)
                return

            conn_ip = dlg.input_connect_ip.text().strip()
            pair_ip = dlg.input_pair_ip.text().strip()
            pair_code = dlg.input_pair_code.text().strip()
            if not conn_ip and not (pair_ip and pair_code):
                QMessageBox.warning(
                    self,
                    "Scan QR Code or Enter IP:Port",
                    "Please scan the QR code from your phone's Wireless Debugging screen, "
                    "or enter your phone's IP:Port below.",
                )
                return
            target_label = conn_ip or pair_ip
            self.status_label.setText(f"Status: CONNECTING WI-FI ADB ({target_label})...")
            self.status_label.setStyleSheet("color: #fbbf24; font-weight: bold;")
            ok, log_msg, _devices = DeviceManager.connect_wireless_adb(conn_ip, pair_ip, pair_code)
            self._last_device_signature = None
            self.refresh_devices(manual=True)
            if ok:
                self.connect_appium(silent=True)
                QMessageBox.information(
                    self,
                    "Wi-Fi Phone Connected!",
                    f"Successfully connected to phone over Wi-Fi ({target_label})!",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Wi-Fi ADB Connection Failed",
                    f"Could not connect to {target_label}.\n\nDetails:\n{log_msg}\n\n"
                    "Make sure:\n"
                    "• Phone and PC are on the same Wi-Fi network.\n"
                    "• Wireless Debugging is ON in Developer Options.\n"
                    "• Or simply use the QR Code scanner at the top of the Wi-Fi Phone window!",
                )

    def get_active_manager(self):
        return self.active_manager

    def connect_appium(self, silent: bool = False):
        serial = self.device_combo.currentData()
        if not serial:
            # Try refreshing once (with auto-download of ADB if missing)
            self.refresh_devices(manual=not silent)
            serial = self.device_combo.currentData()
            if not serial:
                if not silent:
                    QMessageBox.warning(
                        self,
                        "No Android Device Detected",
                        "Your phone is not currently visible to ADB.\n\n"
                        "• For Wi-Fi Connection (No cable/driver needed): Click '📶 Wi-Fi Phone (QR Scan)' "
                        "and scan the QR code from Settings → Developer Options → Wireless Debugging.\n\n"
                        "• For USB Connection: Click '🔄 Fix / Install ADB', unlock your phone, "
                        "switch USB mode from 'Charging' to 'File Transfer', and enable 'USB Debugging'.\n\n"
                        "• Using Chrome/Edge on PC? You do NOT need a phone connected — just use the Browser Extension!",
                    )
                return

        use_direct_adb = self.mode_combo.currentIndex() == 0
        self.status_label.setText("Status: CONNECTING...")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")

        if use_direct_adb:
            self.active_manager = self.adb_manager
            if self.adb_manager.connect(serial):
                self._is_connected = True
                self._connected_serial = serial
                self.status_label.setText(f"Status: CONNECTED ({serial})")
                self.status_label.setStyleSheet("color: #4ade80; font-weight: bold;")
                self.connect_btn.setText("🔄 Reconnect Device")
                self.connect_btn.setEnabled(True)
                self.mode_combo.setEnabled(True)
                self.device_connected.emit(serial)
            else:
                self._is_connected = False
                self._connected_serial = None
                self.status_label.setText("Status: ADB CONNECTION ERROR (Unlock phone & check USB/Wi-Fi Debugging)")
                self.status_label.setStyleSheet("color: #f87171; font-weight: bold;")
        else:
            self.active_manager = self.appium_manager
            if self.appium_manager.connect(serial):
                self._is_connected = True
                self._connected_serial = serial
                self.status_label.setText(f"Status: CONNECTED (Appium — {serial})")
                self.status_label.setStyleSheet("color: #4ade80; font-weight: bold;")
                self.connect_btn.setText("🔄 Reconnect Device")
                self.connect_btn.setEnabled(True)
                self.mode_combo.setEnabled(True)
                self.device_connected.emit(serial)
            else:
                self._is_connected = False
                self._connected_serial = None
                self.status_label.setText("Status: APPIUM ERROR (Is Appium Server running?)")
                self.status_label.setStyleSheet("color: #f87171; font-weight: bold;")

    def open_url(self):
        serial = self.device_combo.currentData()
        url = self.url_input.text().strip()

        if not serial:
            QMessageBox.warning(self, "Warning", "Please select a connected device first.")
            return

        if not url:
            QMessageBox.warning(self, "Warning", "Please enter a valid URL.")
            return

        success = DeviceManager.open_url(serial, url)
        if success:
            QMessageBox.information(self, "Success", "URL launched on the device!")
        else:
            QMessageBox.critical(self, "Error", "Failed to open URL. Is the device connected and unlocked?")
