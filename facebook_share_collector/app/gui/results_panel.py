from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                                 QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, 
                                 QFileDialog, QMessageBox, QLineEdit, QLabel, QComboBox)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QDesktopServices
from app.models.share_profile import ShareProfile
from app.utils.contest_validator import IncrementalContestAggregator
from app.exporters.csv_exporter import CSVExporter
from app.exporters.json_exporter import JSONExporter
from app.exporters.xlsx_exporter import XLSXExporter
from app.exporters.lottery_print_exporter import LotteryPrintExporter
import datetime
import json
import os

class ResultsPanel(QWidget):
    profile_clicked = Signal(str, int)
    scroll_top_requested = Signal()
    load_last_session_requested = Signal()
    manage_sessions_requested = Signal()
    counts_changed = Signal(dict)

    MAX_TABLE_DISPLAY_ROWS = 1500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profiles = []
        self._raw_dedupe_map = {}
        self.aggregator = IncrementalContestAggregator()
        self.participants = []
        self._participants_dirty = False
        self._icon_cache = {}
        
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(350)
        self._refresh_timer.timeout.connect(self.refresh_table)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        # Search & Filter Bar
        search_layout = QHBoxLayout()
        self.filter_label = QLabel("View Mode:")
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All Participants (Contest Validation)",
            "Only Eligible (All 3 Done ✅ — Ready to Print)",
            "Raw Collected Items (All)",
            "Raw Likes Only 👍",
            "Raw Comments Only 💬",
            "Raw Shares Only 🔄",
        ])
        self.filter_combo.currentIndexChanged.connect(self.refresh_table)

        self.search_label = QLabel("Search (#Serial or Name):")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type #0001 or Name (Enter to find on device)...")
        self.search_input.textChanged.connect(self.search_name)
        self.search_input.returnPressed.connect(self._trigger_device_search)
        
        self.btn_find_device = QPushButton("Find on Device")
        self.btn_find_device.clicked.connect(self._trigger_device_search)
        
        search_layout.addWidget(self.filter_label)
        search_layout.addWidget(self.filter_combo)
        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.btn_find_device)
        
        # Table
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Serial #", "Name & Avatar", "Liked 👍", "Commented 💬", "Shared 🔄",
            "Score", "Contest Status", "Comment / Share Text", "Identity / Profile URL"
        ])
        self.table.setStyleSheet(
            "QTableWidget { background-color: #141923; color: #f8fafc; gridline-color: #2d3748; "
            "selection-background-color: #1d4ed8; selection-color: #ffffff; font-size: 12px; }"
            "QHeaderView::section { background-color: #1e293b; color: #e2e8f0; font-weight: bold; "
            "padding: 6px; border: 1px solid #334155; }"
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemClicked.connect(self._on_item_clicked)
        
        # Export & Lottery Print Buttons
        btn_layout = QHBoxLayout()
        self.btn_print_lottery = QPushButton("🖨️ Print Lottery Slips (3/3 Eligible)")
        self.btn_print_lottery.setStyleSheet("font-weight: bold; background-color: #1b8a2f; color: white; padding: 6px 12px;")
        self.btn_print_lottery.clicked.connect(self.export_printable_lottery)

        self.btn_live_spin = QPushButton("🎡 Live Spin Draw")
        self.btn_live_spin.setStyleSheet("font-weight: bold; background-color: #7c3aed; color: white; padding: 6px 12px;")
        self.btn_live_spin.clicked.connect(self.open_live_lottery_draw)

        self.btn_csv = QPushButton("Export CSV")
        self.btn_csv.clicked.connect(self.export_csv)
        self.btn_json = QPushButton("Export JSON")
        self.btn_json.clicked.connect(self.export_json)
        self.btn_xlsx = QPushButton("Export XLSX")
        self.btn_xlsx.clicked.connect(self.export_xlsx)
        
        self.btn_load_session = QPushButton("📂 Load Latest Session")
        self.btn_load_session.clicked.connect(self.load_last_session_requested.emit)

        self.btn_manage_sessions = QPushButton("🗂 Manage / Merge Sessions")
        self.btn_manage_sessions.setStyleSheet("font-weight: bold; background-color: #0284c7; color: white; padding: 6px 10px;")
        self.btn_manage_sessions.clicked.connect(self.manage_sessions_requested.emit)

        self.btn_scroll_top = QPushButton("Scroll to Top")
        self.btn_scroll_top.clicked.connect(self.scroll_top_requested.emit)
        
        self.btn_clear = QPushButton("Clear Results")
        self.btn_clear.clicked.connect(self.clear_results)
        
        btn_layout.addWidget(self.btn_print_lottery)
        btn_layout.addWidget(self.btn_live_spin)
        btn_layout.addWidget(self.btn_csv)
        btn_layout.addWidget(self.btn_json)
        btn_layout.addWidget(self.btn_xlsx)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_load_session)
        btn_layout.addWidget(self.btn_manage_sessions)
        btn_layout.addWidget(self.btn_scroll_top)
        btn_layout.addWidget(self.btn_clear)
        
        self.layout.addLayout(search_layout)
        self.layout.addWidget(self.table)
        self.layout.addLayout(btn_layout)

    def _get_cached_icon(self, avatar_path: str):
        if not avatar_path:
            return None
        icon = self._icon_cache.get(avatar_path)
        if icon is not None:
            return icon
        if os.path.isfile(avatar_path) and os.path.getsize(avatar_path) > 64:
            icon = QIcon(avatar_path)
            self._icon_cache[avatar_path] = icon
            return icon
        return None

    def _on_item_clicked(self, item):
        col = item.column()
        url_col = 8 if self._is_contest_view() else 2
        if col == url_col:
            txt = (item.text() or "").strip()
            if txt.startswith("http://") or txt.startswith("https://"):
                QDesktopServices.openUrl(QUrl(txt))

    def _ingest_single_profile(self, profile: ShareProfile):
        raw_key = (
            (profile.name or "").strip().lower(),
            (getattr(profile, "action_type", "share") or "share").lower(),
            (profile.profile_url or "").strip().lower(),
            (profile.content or "").strip()[:120],
        )
        existing = self._raw_dedupe_map.get(raw_key)
        if existing is not None:
            if not existing.profile_url and profile.profile_url:
                existing.profile_url = profile.profile_url
            if not existing.avatar_hash and profile.avatar_hash:
                existing.avatar_hash = profile.avatar_hash
                existing.avatar_path = profile.avatar_path
        else:
            self._raw_dedupe_map[raw_key] = profile
            self.profiles.append(profile)
        self.aggregator.add_profile(profile)
        self._participants_dirty = True

    def _ensure_sorted_participants(self):
        if self._participants_dirty:
            self.participants = self.aggregator.get_sorted_participants()
            self._participants_dirty = False
        return self.participants

    def add_profile(self, profile: ShareProfile):
        self._ingest_single_profile(profile)
        self.counts_changed.emit(self.aggregator.get_counts())
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def add_profiles_batch(self, profiles_list):
        if not profiles_list:
            return
        for p in profiles_list:
            self._ingest_single_profile(p)
        self._ensure_sorted_participants()
        self.counts_changed.emit(self.aggregator.get_counts())
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def rebuild_from_profiles(self):
        """
        Re-runs the Contest Aggregator after the Hybrid Sync Profile tab enriches
        existing ShareProfile records with matched Profile URLs and Avatar Hashes.
        """
        self.aggregator.clear()
        for p in self.profiles:
            self.aggregator.add_profile(p)
        self._participants_dirty = True
        self._ensure_sorted_participants()
        self.counts_changed.emit(self.aggregator.get_counts())
        self.refresh_table()

    def _is_contest_view(self) -> bool:
        return self.filter_combo.currentIndex() in (0, 1)

    def _get_filtered_participants(self):
        self._ensure_sorted_participants()
        if self.filter_combo.currentIndex() == 1:
            return [p for p in self.participants if p.is_eligible]
        return self.participants

    def _get_filtered_raw_profiles(self):
        idx = self.filter_combo.currentIndex()
        if idx == 3:
            return [p for p in self.profiles if getattr(p, "action_type", "share") == "like"]
        elif idx == 4:
            return [p for p in self.profiles if getattr(p, "action_type", "share") == "comment"]
        elif idx == 5:
            return [p for p in self.profiles if getattr(p, "action_type", "share") == "share"]
        return self.profiles

    def refresh_table(self):
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            if self._is_contest_view():
                self.table.setColumnCount(9)
                self.table.setHorizontalHeaderLabels([
                    "Serial #", "Name & Avatar", "Liked 👍", "Commented 💬", "Shared 🔄",
                    "Score", "Contest Status", "Comment / Share Text", "Identity / Profile URL"
                ])
                displayed = self._get_filtered_participants()
                query = (self.search_input.text() or "").strip().lower()
                if query:
                    displayed = [
                        p for p in displayed
                        if query in p.display_name.lower()
                        or query in p.serial_code.lower()
                        or (p.profile_url and query in p.profile_url.lower())
                    ]
                displayed_slice = displayed[: self.MAX_TABLE_DISPLAY_ROWS]
                self.table.setRowCount(len(displayed_slice))
                eligible_bg = QBrush(QColor(6, 78, 59))        # Deep rich emerald green (#064e3b)
                eligible_fg = QBrush(QColor(240, 253, 244))    # Bright crisp white-mint (#f0fdf4)
                eligible_accent_fg = QBrush(QColor(74, 222, 128))  # Vibrant mint (#4ade80)
                normal_bg_even = QBrush(QColor(20, 25, 35))    # Dark slate (#141923)
                normal_bg_odd = QBrush(QColor(26, 33, 46))     # Slightly lighter dark slate (#1a212e)
                normal_fg = QBrush(QColor(241, 245, 249))      # High-contrast white-gray (#f1f5f9)
                link_fg = QBrush(QColor(96, 165, 250))         # Bright sky blue (#60a5fa)
                bold_font = QFont()
                bold_font.setBold(True)

                for row, p in enumerate(displayed_slice):

                    serial_item = QTableWidgetItem(p.serial_code)
                    if p.is_eligible:
                        serial_item.setFont(bold_font)

                    name_item = QTableWidgetItem(p.display_name)
                    if p.is_eligible:
                        name_item.setFont(bold_font)
                    name_item.setData(Qt.UserRole, p.scroll_index)
                    name_item.setData(Qt.UserRole + 1, p.name)
                    icon = self._get_cached_icon(p.avatar_path)
                    if icon:
                        name_item.setIcon(icon)

                    liked_item = QTableWidgetItem("✅ Yes" if p.liked else "❌ No")
                    commented_item = QTableWidgetItem(
                        f"✅ Yes ({len(p.comment_texts)})" if p.commented else "❌ No"
                    )
                    shared_item = QTableWidgetItem("✅ Yes" if p.shared else "❌ No")
                    score_item = QTableWidgetItem(f"{p.actions_completed}/3")
                    if p.is_eligible:
                        score_item.setFont(bold_font)
                    status_item = QTableWidgetItem(p.status_label)
                    if p.is_eligible:
                        status_item.setFont(bold_font)

                    notes_preview = p.combined_notes
                    if len(notes_preview) > 60:
                        notes_preview = notes_preview[:57] + "..."
                    notes_item = QTableWidgetItem(notes_preview)
                    notes_item.setToolTip(p.combined_notes)

                    id_text = p.profile_url or (f"AvatarHash:{p.avatar_hash[:8]}" if p.avatar_hash else "")
                    url_item = QTableWidgetItem(id_text)

                    row_items = [
                        serial_item, name_item, liked_item, commented_item, shared_item,
                        score_item, status_item, notes_item, url_item
                    ]
                    row_bg = eligible_bg if p.is_eligible else (normal_bg_even if row % 2 == 0 else normal_bg_odd)
                    row_fg = eligible_fg if p.is_eligible else normal_fg
                    for col, cell_item in enumerate(row_items):
                        cell_item.setBackground(row_bg)
                        if p.is_eligible and col in (0, 5, 6):
                            cell_item.setForeground(eligible_accent_fg)
                        elif col == 8 and p.profile_url:
                            cell_item.setForeground(link_fg)
                        else:
                            cell_item.setForeground(row_fg)
                        self.table.setItem(row, col, cell_item)
            else:
                self.table.setColumnCount(8)
                self.table.setHorizontalHeaderLabels([
                    "Name", "Action", "Profile URL", "Content",
                    "Reactions", "Comments", "Confidence", "First Seen"
                ])
                raw_bg_even = QBrush(QColor(20, 25, 35))
                raw_bg_odd = QBrush(QColor(26, 33, 46))
                raw_fg = QBrush(QColor(241, 245, 249))
                link_fg = QBrush(QColor(96, 165, 250))
                raw_list = self._get_filtered_raw_profiles()
                query = (self.search_input.text() or "").strip().lower()
                if query:
                    raw_list = [
                        p for p in raw_list
                        if query in (p.name or "").lower()
                        or (p.profile_url and query in p.profile_url.lower())
                        or (p.content and query in p.content.lower())
                    ]
                raw_slice = raw_list[-self.MAX_TABLE_DISPLAY_ROWS :] if len(raw_list) > self.MAX_TABLE_DISPLAY_ROWS else raw_list
                self.table.setRowCount(len(raw_slice))
                for row, profile in enumerate(raw_slice):

                    name_item = QTableWidgetItem(profile.name)
                    name_item.setData(Qt.UserRole, profile.scroll_index)
                    name_item.setData(Qt.UserRole + 1, profile.name)
                    icon = self._get_cached_icon(getattr(profile, "avatar_path", None))
                    if icon:
                        name_item.setIcon(icon)

                    action_item = QTableWidgetItem((getattr(profile, "action_type", "share") or "share").upper())
                    url_item = QTableWidgetItem(profile.profile_url or "")

                    content_preview = profile.content or ""
                    if len(content_preview) > 50:
                        content_preview = content_preview[:47] + "..."
                    content_item = QTableWidgetItem(content_preview)
                    content_item.setToolTip(profile.content or "")

                    react_item = QTableWidgetItem(profile.reactions or "0")
                    comm_item = QTableWidgetItem(profile.comments or "0")
                    conf_item = QTableWidgetItem(f"{profile.confidence:.2f}")
                    seen_item = QTableWidgetItem(profile.first_seen_at.split('.')[0].replace('T', ' '))

                    raw_cells = [
                        name_item, action_item, url_item, content_item,
                        react_item, comm_item, conf_item, seen_item
                    ]
                    r_bg = raw_bg_even if row % 2 == 0 else raw_bg_odd
                    for col, c_item in enumerate(raw_cells):
                        c_item.setBackground(r_bg)
                        c_item.setForeground(link_fg if (col == 2 and profile.profile_url) else raw_fg)
                        self.table.setItem(row, col, c_item)
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.scrollToBottom()

    def search_name(self, text):
        self.refresh_table()
        if not text:
            self.table.clearSelection()
            return
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _trigger_device_search(self):
        selected_items = self.table.selectedItems()
        name_col = 1 if self._is_contest_view() else 0
        if selected_items:
            row = selected_items[0].row()
            name_item = self.table.item(row, name_col)
            if name_item:
                scroll_index = name_item.data(Qt.UserRole) or 0
                raw_name = name_item.data(Qt.UserRole + 1) or name_item.text()
                self.profile_clicked.emit(raw_name, scroll_index)
        elif self.search_input.text():
            self.profile_clicked.emit(self.search_input.text(), 0)

    def clear_results(self):
        self.table.setRowCount(0)
        self.profiles.clear()
        self._raw_dedupe_map.clear()
        self.aggregator.clear()
        self.participants.clear()
        self._participants_dirty = False
        self.counts_changed.emit({
            "total_participants": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "eligible": 0,
        })

    def _get_default_filename(self, ext, prefix=None):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        if not prefix:
            prefix = "facebook_contest_eligible" if self.filter_combo.currentIndex() == 1 else "facebook_contest_results"
        return f"{prefix}_{timestamp}.{ext}"

    def open_live_lottery_draw(self):
        self._ensure_sorted_participants()
        eligible = [p for p in self.participants if p.is_eligible]
        if not eligible:
            QMessageBox.information(
                self,
                "No 3/3 Eligible Winners Yet",
                "No participants have completed all 3 contest actions (Like + Comment + Share) yet.\n\n"
                "Collect Likes, Comments, and Shares (or load a saved session) first!"
            )
            return
        from app.gui.live_lottery_dialog import LiveLotteryDialog
        dlg = LiveLotteryDialog(eligible, parent=self)
        dlg.exec()

    def export_printable_lottery(self):
        self._ensure_sorted_participants()
        if not self.participants:
            QMessageBox.information(self, "No Data", "Collect Likes, Comments, and Shares first to generate lottery tickets.")
            return
        filename = self._get_default_filename("html", prefix="facebook_lottery_tickets")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Printable Lottery Tickets (HTML/PDF)",
            os.path.join("data", filename),
            "HTML Printable Document (*.html)"
        )
        if path:
            if LotteryPrintExporter.export_printable_tickets(self.participants, path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))
                QMessageBox.information(
                    self,
                    "Lottery Tickets Ready",
                    f"Printable Lottery Slips & Judge Verification Sheet opened in your browser!\n\nClick 'Print Tickets / Save as PDF' at the top of the page.\nSaved to: {path}"
                )
            else:
                QMessageBox.critical(self, "Export Error", "Failed to generate printable lottery tickets.")

    def export_csv(self):
        if not self.profiles:
            return
        filename = self._get_default_filename("csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", os.path.join("data", filename), "CSV Files (*.csv)")
        if path:
            if self._is_contest_view():
                ok = CSVExporter.export_contest(self._get_filtered_participants(), path)
            else:
                ok = CSVExporter.export(self._get_filtered_raw_profiles(), path)
            if ok:
                QMessageBox.information(self, "Export", "CSV Export successful.")

    def export_json(self):
        if not self.profiles:
            return
        filename = self._get_default_filename("json")
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", os.path.join("data", filename), "JSON Files (*.json)")
        if path:
            if self._is_contest_view():
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    data = [p.to_dict() for p in self._get_filtered_participants()]
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    QMessageBox.information(self, "Export", "JSON Export successful.")
                except Exception as e:
                    QMessageBox.critical(self, "Export", f"JSON Export failed: {e}")
            else:
                if JSONExporter.export(self._get_filtered_raw_profiles(), path):
                    QMessageBox.information(self, "Export", "JSON Export successful.")

    def export_xlsx(self):
        if not self.profiles:
            return
        filename = self._get_default_filename("xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Export XLSX", os.path.join("data", filename), "Excel Files (*.xlsx)")
        if path:
            if self._is_contest_view():
                ok = XLSXExporter.export_contest(self._get_filtered_participants(), path)
            else:
                ok = XLSXExporter.export(self._get_filtered_raw_profiles(), path)
            if ok:
                QMessageBox.information(self, "Export", "XLSX Export successful.")
            else:
                QMessageBox.critical(self, "Export", "XLSX Export failed. Is openpyxl installed?")
