from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                 QLabel, QComboBox, QPushButton, QGroupBox, QLineEdit, QMessageBox)
from PySide6.QtCore import Signal, QTimer
from app.automation.device_manager import DeviceManager
from app.automation.appium_manager import AppiumManager
from app.automation.adb_controller import ADBManager


class DevicePanel(QGroupBox):
    # Signal emitted when a device is connected successfully
    device_connected = Signal(str)

    def __init__(self, appium_manager: AppiumManager, adb_manager: ADBManager = None, parent=None):
        super().__init__("Device & Zero-Setup Connection (Optional if using Browser Extension)", parent)
        self.appium_manager = appium_manager
        self.adb_manager = adb_manager or ADBManager()
        self.active_manager = self.adb_manager
        self._is_connected = False
        self._last_device_signature = None

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # ADB Devices + Engine Mode
        adb_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.refresh_btn = QPushButton("Refresh Devices")
        self.refresh_btn.clicked.connect(lambda: self.refresh_devices(manual=True))

        self.restart_adb_btn = QPushButton("🔄 Fix / Restart ADB")
        self.restart_adb_btn.setToolTip(
            "Restarts the ADB USB daemon (adb kill-server && adb start-server) "
            "if your plugged-in phone is not showing up."
        )
        self.restart_adb_btn.clicked.connect(self.restart_adb_and_refresh)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Direct ADB Mode (Zero-Setup — No Appium Needed)",
            "Appium Server Mode (127.0.0.1:4723)"
        ])

        adb_layout.addWidget(QLabel("Device:"))
        adb_layout.addWidget(self.device_combo, 1)
        adb_layout.addWidget(QLabel("Engine:"))
        adb_layout.addWidget(self.mode_combo)
        adb_layout.addWidget(self.refresh_btn)
        adb_layout.addWidget(self.restart_adb_btn)

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

        # Auto-poll every 3 seconds while disconnected so plugging in / unlocking phone updates immediately
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self._auto_poll_devices)
        self._poll_timer.start()

    def _auto_poll_devices(self):
        if self._is_connected:
            return
        self.refresh_devices(manual=False)

    def refresh_devices(self, manual: bool = False):
        devices = DeviceManager.get_connected_devices(auto_reconnect=manual)
        sig = tuple((d.get("serial"), d.get("state"), d.get("model")) for d in devices)
        if not manual and sig == self._last_device_signature and self.device_combo.count() > 0:
            return
        self._last_device_signature = sig

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
                    serial
                )
                pending_states.append("unauthorized")
            elif state == "offline":
                self.device_combo.addItem(
                    f"⚠️ {serial} (OFFLINE — Click '🔄 Fix / Restart ADB' or re-plug USB)",
                    serial
                )
                pending_states.append("offline")
            else:
                self.device_combo.addItem(f"⏳ {serial} ({state})", serial)
                pending_states.append(state)

        if self.device_combo.count() == 0:
            self.device_combo.addItem("No devices found (Check USB File Transfer mode & USB Debugging)", None)
            if not self._is_connected:
                self.status_label.setText("Status: NO USB DEVICE DETECTED")
                self.status_label.setStyleSheet("color: #f87171; font-weight: bold;")
        elif not self._is_connected:
            if ready_count > 0:
                self.status_label.setText("Status: PHONE DETECTED — Click 'Connect Device'")
                self.status_label.setStyleSheet("color: #fbbf24; font-weight: bold;")
            elif "unauthorized" in pending_states:
                self.status_label.setText("Status: TAP 'ALLOW USB DEBUGGING' ON PHONE SCREEN")
                self.status_label.setStyleSheet("color: #fb923c; font-weight: bold;")
            else:
                self.status_label.setText(f"Status: DEVICE {pending_states[0].upper()} — Click '🔄 Fix / Restart ADB'")
                self.status_label.setStyleSheet("color: #fb923c; font-weight: bold;")

    def restart_adb_and_refresh(self):
        self.status_label.setText("Status: RESTARTING ADB DAEMON...")
        self.status_label.setStyleSheet("color: #fbbf24; font-weight: bold;")
        ok, log_msg, devices = DeviceManager.restart_adb_server()
        self._last_device_signature = None
        self.refresh_devices(manual=True)

        if not devices:
            extra_hint = ""
            if "e00002be" in log_msg or "Unable to create an interface plug-in" in log_msg:
                extra_hint = (
                    "\n\n⚠️ macOS USB Exclusive Lock Detected (e00002be):\n"
                    "Another app (like Chrome 'chrome://inspect', Android File Transfer, or Photos) "
                    "is holding exclusive access to your phone's USB port.\n"
                    "• Close any 'chrome://inspect' tab or Android File Transfer app, OR\n"
                    "• Unplug and re-plug the USB cable and select 'File Transfer (MTP)'."
                )
            QMessageBox.information(
                self,
                "ADB Restarted — Still No Device Detected",
                "ADB Server was restarted, but macOS still sees 0 Android ADB devices.\n\n"
                "Quick Checklist for your plugged-in phone:\n"
                "1. Unlock your phone screen.\n"
                "2. Swipe down the top notification bar → tap the 'USB Charging this device' notification "
                "→ switch USB mode to 'File Transfer / Android Auto' or 'PTP'.\n"
                "3. Go to Settings → Developer Options → turn 'USB Debugging' OFF and back ON.\n"
                "4. Tap 'Allow' on the 'Allow USB debugging?' popup on your phone.\n"
                "5. Make sure your USB cable is a data cable (not power-only)."
                f"{extra_hint}"
            )

    def get_active_manager(self):
        return self.active_manager

    def connect_appium(self):
        serial = self.device_combo.currentData()
        if not serial:
            # Try refreshing once in case the phone was just plugged in
            self.refresh_devices(manual=True)
            serial = self.device_combo.currentData()
            if not serial:
                QMessageBox.warning(
                    self,
                    "No Android Device Detected",
                    "Your phone is not currently visible to ADB.\n\n"
                    "• If you want to use your Phone: Click '🔄 Fix / Restart ADB', unlock your phone, "
                    "switch USB mode from 'Charging' to 'File Transfer', and ensure 'USB Debugging' is enabled.\n\n"
                    "• If you are scraping from Chrome/Edge (on the left of your screen): "
                    "You do NOT need to connect a phone! Just use the Browser Extension or '🔖 Get Browser Bookmark' "
                    "and batches will import automatically."
                )
                return

        use_direct_adb = self.mode_combo.currentIndex() == 0
        self.status_label.setText("Status: CONNECTING...")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")

        if use_direct_adb:
            self.active_manager = self.adb_manager
            if self.adb_manager.connect(serial):
                self._is_connected = True
                self.status_label.setText("Status: CONNECTED (Direct ADB Zero-Setup)")
                self.status_label.setStyleSheet("color: #4ade80; font-weight: bold;")
                self.device_connected.emit(serial)
                self.connect_btn.setEnabled(False)
                self.mode_combo.setEnabled(False)
            else:
                self.status_label.setText("Status: ADB CONNECTION ERROR (Unlock phone & check USB Debugging)")
                self.status_label.setStyleSheet("color: #f87171; font-weight: bold;")
        else:
            self.active_manager = self.appium_manager
            if self.appium_manager.connect(serial):
                self._is_connected = True
                self.status_label.setText("Status: CONNECTED (Appium)")
                self.status_label.setStyleSheet("color: #4ade80; font-weight: bold;")
                self.device_connected.emit(serial)
                self.connect_btn.setEnabled(False)
                self.mode_combo.setEnabled(False)
            else:
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
