from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QFileDialog, QMessageBox, QLineEdit,
    QLabel, QComboBox, QSpinBox, QCheckBox, QFrame, QMenu
)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QDesktopServices, QAction
from app.models.share_profile import ShareProfile
from app.utils.contest_validator import IncrementalContestAggregator
from app.utils.advanced_filter_engine import (
    AdvancedFilterConfig,
    AdvancedFilterEngine,
)
from app.utils.text_normalizer import normalize_text
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
        self._disqualified_keys = set()
        self._last_evaluations = {}
        self._last_category_counts = {
            "all": 0,
            "qualified": 0,
            "correct": 0,
            "wrong": 0,
            "invalid": 0,
            "no_comments": 0,
            "duplicates": 0,
            "disqualified": 0,
        }
        self._active_quick_category = "all"

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(350)
        self._refresh_timer.timeout.connect(self.refresh_table)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(6, 4, 6, 4)
        self.layout.setSpacing(6)
        self.setLayout(self.layout)

        # =========================================================================
        # Row 1: View Mode + Search + Find on Device + Toggle Advanced Filter Bar
        # =========================================================================
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
        self.filter_combo.currentIndexChanged.connect(self._on_view_mode_changed)

        self.search_label = QLabel("Search (#Serial / Name / Text):")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type #0001, Name, or Keyword (Enter to find on device)...")
        self.search_input.textChanged.connect(self.search_name)
        self.search_input.returnPressed.connect(self._trigger_device_search)

        self.btn_find_device = QPushButton("Find on Device")
        self.btn_find_device.clicked.connect(self._trigger_device_search)

        self.btn_toggle_adv = QPushButton("🎯 Advanced Filters (AND / OR / NOT)")
        self.btn_toggle_adv.setCheckable(True)
        self.btn_toggle_adv.setChecked(True)
        self.btn_toggle_adv.setStyleSheet(
            "QPushButton { background-color: #1e293b; color: #38bdf8; font-weight: bold; "
            "padding: 5px 10px; border: 1px solid #0284c7; border-radius: 5px; }"
            "QPushButton:checked { background-color: #0369a1; color: #ffffff; }"
        )
        self.btn_toggle_adv.toggled.connect(self._toggle_advanced_filter_panel)

        search_layout.addWidget(self.filter_label)
        search_layout.addWidget(self.filter_combo)
        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_input, 1)
        search_layout.addWidget(self.btn_find_device)
        search_layout.addWidget(self.btn_toggle_adv)

        # =========================================================================
        # Row 2 & 3: FairDraw (DrawSystem) Advanced Boolean Filter & Rule Panel
        # =========================================================================
        self.adv_frame = QFrame()
        self.adv_frame.setStyleSheet(
            "QFrame#AdvFilterFrame { background-color: #0f172a; border: 1px solid #334155; "
            "border-radius: 7px; padding: 4px; }"
            "QLabel { color: #cbd5e1; font-size: 11px; font-weight: bold; }"
            "QLineEdit { background-color: #1e293b; color: #f8fafc; border: 1px solid #475569; "
            "border-radius: 4px; padding: 4px 6px; font-size: 12px; }"
            "QComboBox, QSpinBox { background-color: #1e293b; color: #f8fafc; border: 1px solid #475569; "
            "border-radius: 4px; padding: 3px 6px; font-size: 11px; }"
            "QCheckBox { color: #cbd5e1; font-size: 11px; font-weight: bold; }"
        )
        self.adv_frame.setObjectName("AdvFilterFrame")
        adv_main_layout = QVBoxLayout(self.adv_frame)
        adv_main_layout.setContentsMargins(8, 6, 8, 6)
        adv_main_layout.setSpacing(6)

        # --- Sub-row A: Boolean Keyword Inputs (OR / AND / NOT / Expression) ---
        kw_row = QHBoxLayout()
        kw_row.setSpacing(6)

        lbl_or = QLabel("✅ OR (Any Right Answer):")
        lbl_or.setStyleSheet("color: #4ade80; font-weight: bold;")
        self.or_keywords_input = QLineEdit()
        self.or_keywords_input.setPlaceholderText("e.g. apple, আপেল, 4, চার, ready")
        self.or_keywords_input.setToolTip(
            "OR Logic (Match ANY): Participant passes if their comment/share contains AT LEAST ONE of these comma-separated answers.\n"
            "You can also type inline boolean queries like: (apple OR আপেল) AND fresh NOT fake"
        )
        self.or_keywords_input.textChanged.connect(self._on_filter_criteria_changed)

        lbl_and = QLabel("🔗 AND (Must Have ALL):")
        lbl_and.setStyleSheet("color: #60a5fa; font-weight: bold;")
        self.and_keywords_input = QLineEdit()
        self.and_keywords_input.setPlaceholderText("e.g. done, shared (Must match ALL)")
        self.and_keywords_input.setToolTip(
            "AND Logic (Match ALL): Participant must include EVERY comma-separated keyword listed here."
        )
        self.and_keywords_input.textChanged.connect(self._on_filter_criteria_changed)

        lbl_not = QLabel("🚫 NOT (Wrong / Exclude):")
        lbl_not.setStyleSheet("color: #f87171; font-weight: bold;")
        self.not_keywords_input = QLineEdit()
        self.not_keywords_input.setPlaceholderText("e.g. 14, wrong, spam, fake (Exclude)")
        self.not_keywords_input.setToolTip(
            "NOT Logic (Exclude / Wrong Answer): Immediately marks comment as Wrong Answer & excludes participant if ANY of these keywords appear."
        )
        self.not_keywords_input.textChanged.connect(self._on_filter_criteria_changed)

        kw_row.addWidget(lbl_or)
        kw_row.addWidget(self.or_keywords_input, 2)
        kw_row.addWidget(lbl_and)
        kw_row.addWidget(self.and_keywords_input, 2)
        kw_row.addWidget(lbl_not)
        kw_row.addWidget(self.not_keywords_input, 2)
        adv_main_layout.addLayout(kw_row)

        # --- Sub-row B: Match Mode + Extra Rule Constraints + Participant Actions ---
        rules_row = QHBoxLayout()
        rules_row.setSpacing(8)

        lbl_mode = QLabel("Match Mode:")
        self.match_mode_combo = QComboBox()
        self.match_mode_combo.addItems([
            "Whole Word (Smart Bangla+EN Boundary)",
            "Contains (Partial Text Match)",
            "Exact Match (Strict Answer Only)",
            "Regex Pattern",
        ])
        self.match_mode_combo.setToolTip(
            "• Whole Word (Smart Boundary): '4' matches 'Ans is 4' but NOT '14'; 'ভালো' matches 'আমি ভালো' but NOT 'ভালোবাসি'.\n"
            "• Contains (Partial): Matches substring anywhere inside a word.\n"
            "• Exact Match: Entire comment must equal the keyword.\n"
            "• Regex: Custom regular expression."
        )
        self.match_mode_combo.currentIndexChanged.connect(self._on_filter_criteria_changed)

        lbl_min_len = QLabel("Min Chars:")
        self.spin_min_len = QSpinBox()
        self.spin_min_len.setRange(0, 500)
        self.spin_min_len.setValue(0)
        self.spin_min_len.setToolTip("Require comment to have at least X characters.")
        self.spin_min_len.valueChanged.connect(self._on_filter_criteria_changed)

        lbl_min_words = QLabel("Min Words:")
        self.spin_min_words = QSpinBox()
        self.spin_min_words.setRange(0, 100)
        self.spin_min_words.setValue(0)
        self.spin_min_words.setToolTip("Require comment to have at least X words.")
        self.spin_min_words.valueChanged.connect(self._on_filter_criteria_changed)

        self.chk_exclude_emoji = QCheckBox("No Emoji-Only")
        self.chk_exclude_emoji.setToolTip(
            "Exclude comments that only contain emojis or punctuation (requires English or Bangla letters/numbers)."
        )
        self.chk_exclude_emoji.toggled.connect(self._on_filter_criteria_changed)

        self.chk_require_tag = QCheckBox("Require @Mention / #Tag")
        self.chk_require_tag.setToolTip("Require comment or share text to include at least one @mention or #hashtag.")
        self.chk_require_tag.toggled.connect(self._on_filter_criteria_changed)

        lbl_gender = QLabel("Gender:")
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["All Genders", "Male ♂", "Female ♀", "Unknown ?"])
        self.gender_combo.currentIndexChanged.connect(self._on_filter_criteria_changed)

        self.btn_dq_toggle = QPushButton("🚫 Disqualify / Qualify")
        self.btn_dq_toggle.setToolTip("Manually Disqualify or Re-Qualify the selected participant row(s).")
        self.btn_dq_toggle.setStyleSheet(
            "background-color: #7f1d1d; color: #fecaca; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 4px;"
        )
        self.btn_dq_toggle.clicked.connect(self.toggle_disqualify_selected)

        self.btn_clean_dups = QPushButton("🧹 Clean Duplicates")
        self.btn_clean_dups.setToolTip(
            "Merge/remove duplicate same-name entries, keeping the highest-scoring record per name."
        )
        self.btn_clean_dups.setStyleSheet(
            "background-color: #334155; color: #e2e8f0; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 4px;"
        )
        self.btn_clean_dups.clicked.connect(self.clean_duplicate_names)

        self.btn_reset_filters = QPushButton("↺ Reset Filters")
        self.btn_reset_filters.setStyleSheet(
            "background-color: #475569; color: #ffffff; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 4px;"
        )
        self.btn_reset_filters.clicked.connect(self.reset_advanced_filters)

        rules_row.addWidget(lbl_mode)
        rules_row.addWidget(self.match_mode_combo)
        rules_row.addWidget(lbl_min_len)
        rules_row.addWidget(self.spin_min_len)
        rules_row.addWidget(lbl_min_words)
        rules_row.addWidget(self.spin_min_words)
        rules_row.addWidget(self.chk_exclude_emoji)
        rules_row.addWidget(self.chk_require_tag)
        rules_row.addWidget(lbl_gender)
        rules_row.addWidget(self.gender_combo)
        rules_row.addStretch()
        rules_row.addWidget(self.btn_dq_toggle)
        rules_row.addWidget(self.btn_clean_dups)
        rules_row.addWidget(self.btn_reset_filters)
        adv_main_layout.addLayout(rules_row)

        # --- Sub-row C: DrawSystem Interactive Quick Category Filter Pills (with Live Counts & %) ---
        pills_row = QHBoxLayout()
        pills_row.setSpacing(5)
        self._category_buttons = {}
        pill_specs = [
            ("all", "All", "#334155", "#2563eb"),
            ("qualified", "✅ Qualified (3/3 + Rules)", "#065f46", "#10b981"),
            ("correct", "🎯 Correct Answer", "#1e3a8a", "#3b82f6"),
            ("wrong", "❌ Wrong Answer", "#7f1d1d", "#ef4444"),
            ("invalid", "⚠️ Invalid / Emoji-Only", "#78350f", "#f59e0b"),
            ("no_comments", "💬 No Comments", "#374151", "#6b7280"),
            ("duplicates", "👥 Duplicates", "#4c1d95", "#8b5cf6"),
            ("disqualified", "🚫 Disqualified", "#450a0a", "#dc2626"),
        ]
        for cat_key, base_label, idle_bg, active_border in pill_specs:
            btn = QPushButton(f"{base_label}: 0")
            btn.setCheckable(True)
            btn.setChecked(cat_key == "all")
            btn.setProperty("base_label", base_label)
            btn.setProperty("idle_bg", idle_bg)
            btn.setProperty("active_border", active_border)
            btn.clicked.connect(lambda checked, k=cat_key: self.set_quick_category(k))
            self._category_buttons[cat_key] = btn
            pills_row.addWidget(btn)
        pills_row.addStretch()
        self._update_pill_styles()
        adv_main_layout.addLayout(pills_row)

        # =========================================================================
        # Table
        # =========================================================================
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
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.table.itemClicked.connect(self._on_item_clicked)

        # =========================================================================
        # Export & Lottery Print Buttons
        # =========================================================================
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
        self.layout.addWidget(self.adv_frame)
        self.layout.addWidget(self.table, 1)
        self.layout.addLayout(btn_layout)

    def _toggle_advanced_filter_panel(self, checked: bool):
        self.adv_frame.setVisible(checked)

    def _on_view_mode_changed(self, idx: int):
        if idx == 1 and self._active_quick_category == "all":
            # Sync combo box "Only Eligible" with quick pill
            pass
        self.refresh_table()

    def _on_filter_criteria_changed(self, *args):
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def set_quick_category(self, category_key: str):
        self._active_quick_category = category_key
        for k, btn in self._category_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(k == category_key)
            btn.blockSignals(False)
        self._update_pill_styles()
        self.refresh_table()

    def _update_pill_styles(self):
        total = max(self._last_category_counts.get("all", 0), 0)
        for k, btn in self._category_buttons.items():
            base_label = btn.property("base_label")
            idle_bg = btn.property("idle_bg")
            active_border = btn.property("active_border")
            cnt = self._last_category_counts.get(k, 0)
            if k == "all" or total == 0:
                text = f"{base_label}: {cnt}"
            else:
                pct = (cnt / total) * 100.0
                text = f"{base_label}: {cnt} ({pct:.1f}%)"
            btn.setText(text)
            if k == self._active_quick_category:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {active_border}; color: #ffffff; font-weight: 800; "
                    f"font-size: 11px; padding: 4px 9px; border-radius: 11px; border: 2px solid #ffffff; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {idle_bg}; color: #e2e8f0; font-weight: bold; "
                    f"font-size: 11px; padding: 4px 8px; border-radius: 11px; border: 1px solid {active_border}; }}"
                    f"QPushButton:hover {{ background-color: {active_border}; color: #ffffff; }}"
                )

    def get_advanced_filter_config(self) -> AdvancedFilterConfig:
        mode_idx = self.match_mode_combo.currentIndex()
        mode_map = {
            0: "whole_word",
            1: "contains",
            2: "exact",
            3: "regex",
        }
        gender_idx = self.gender_combo.currentIndex()
        gender_map = {
            0: "all",
            1: "male",
            2: "female",
            3: "unknown",
        }
        effective_category = self._active_quick_category
        if self.filter_combo.currentIndex() == 1 and effective_category == "all":
            effective_category = "qualified"

        return AdvancedFilterConfig(
            or_keywords=self.or_keywords_input.text() or "",
            and_keywords=self.and_keywords_input.text() or "",
            not_keywords=self.not_keywords_input.text() or "",
            match_mode=mode_map.get(mode_idx, "whole_word"),
            min_comment_length=self.spin_min_len.value(),
            min_word_count=self.spin_min_words.value(),
            exclude_invalid_emoji=self.chk_exclude_emoji.isChecked(),
            require_mention_or_hashtag=self.chk_require_tag.isChecked(),
            gender_filter=gender_map.get(gender_idx, "all"),
            quick_category=effective_category,
        )

    def reset_advanced_filters(self):
        for w in (
            self.or_keywords_input,
            self.and_keywords_input,
            self.not_keywords_input,
            self.match_mode_combo,
            self.spin_min_len,
            self.spin_min_words,
            self.chk_exclude_emoji,
            self.chk_require_tag,
            self.gender_combo,
        ):
            w.blockSignals(True)
        self.or_keywords_input.clear()
        self.and_keywords_input.clear()
        self.not_keywords_input.clear()
        self.match_mode_combo.setCurrentIndex(0)
        self.spin_min_len.setValue(0)
        self.spin_min_words.setValue(0)
        self.chk_exclude_emoji.setChecked(False)
        self.chk_require_tag.setChecked(False)
        self.gender_combo.setCurrentIndex(0)
        for w in (
            self.or_keywords_input,
            self.and_keywords_input,
            self.not_keywords_input,
            self.match_mode_combo,
            self.spin_min_len,
            self.spin_min_words,
            self.chk_exclude_emoji,
            self.chk_require_tag,
            self.gender_combo,
        ):
            w.blockSignals(False)
        self.set_quick_category("all")

    def toggle_disqualify_selected(self):
        if not self._is_contest_view():
            return
        selected_rows = sorted({item.row() for item in self.table.selectedItems()})
        if not selected_rows:
            QMessageBox.information(
                self,
                "Select Participant(s)",
                "Select one or more rows in the Contest Validation table first to Disqualify or Re-Qualify them."
            )
            return
        toggled = 0
        for row in selected_rows:
            name_item = self.table.item(row, 1)
            if not name_item:
                continue
            norm_key = name_item.data(Qt.UserRole + 2)
            if not norm_key:
                continue
            if norm_key in self._disqualified_keys:
                self._disqualified_keys.remove(norm_key)
            else:
                self._disqualified_keys.add(norm_key)
            toggled += 1
        if toggled > 0:
            self.refresh_table()

    def clean_duplicate_names(self):
        """
        Matches DrawSystem's 'Clean Duplicates': merges participants sharing the exact same
        normalized display name into a single consolidated participant (combining Likes, Comments,
        Shares, and Profile URL) so no person gets multiple lottery slips under the same name.
        """
        self._ensure_sorted_participants()
        if not self.participants:
            return
        by_name = {}
        duplicates_merged = 0
        new_participants = []
        for p in self.participants:
            nm = normalize_text(p.name or "").lower().strip()
            if not nm:
                new_participants.append(p)
                continue
            if nm not in by_name:
                p.disambiguator = ""
                by_name[nm] = p
                new_participants.append(p)
            else:
                primary = by_name[nm]
                primary.liked = primary.liked or p.liked
                primary.commented = primary.commented or p.commented
                primary.shared = primary.shared or p.shared
                for c in p.comment_texts:
                    if c not in primary.comment_texts:
                        primary.comment_texts.append(c)
                for s in p.share_contents:
                    if s not in primary.share_contents:
                        primary.share_contents.append(s)
                if not primary.profile_url and p.profile_url:
                    primary.profile_url = p.profile_url
                if not primary.avatar_hash and p.avatar_hash:
                    primary.avatar_hash = p.avatar_hash
                    primary.avatar_path = p.avatar_path
                duplicates_merged += 1

        if duplicates_merged == 0:
            QMessageBox.information(self, "No Duplicates Found", "No duplicate participant names were found.")
            return

        self.aggregator.participants = new_participants
        self._participants_dirty = True
        self._ensure_sorted_participants()
        self.refresh_table()
        QMessageBox.information(
            self,
            "Duplicates Cleaned",
            f"Merged {duplicates_merged} duplicate same-name record(s) into unique participants!"
        )

    def _show_table_context_menu(self, pos):
        if not self._is_contest_view():
            return
        menu = QMenu(self)
        act_dq = QAction("🚫 Toggle Disqualify / Qualify Selected", self)
        act_dq.triggered.connect(self.toggle_disqualify_selected)
        menu.addAction(act_dq)

        act_find = QAction("📱 Find Selected on Device", self)
        act_find.triggered.connect(self._trigger_device_search)
        menu.addAction(act_find)

        act_clean = QAction("🧹 Clean Duplicate Names", self)
        act_clean.triggered.connect(self.clean_duplicate_names)
        menu.addAction(act_clean)

        menu.exec(self.table.viewport().mapToGlobal(pos))

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

    def _emit_updated_counts(self):
        base_counts = dict(self.aggregator.get_counts())
        if self._last_category_counts and (
            self.get_advanced_filter_config().has_any_rule_constraints() or self._disqualified_keys
        ):
            base_counts["eligible"] = self._last_category_counts.get("qualified", base_counts.get("eligible", 0))
        self.counts_changed.emit(base_counts)

    def add_profile(self, profile: ShareProfile):
        self._ingest_single_profile(profile)
        self._emit_updated_counts()
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def add_profiles_batch(self, profiles_list):
        if not profiles_list:
            return
        for p in profiles_list:
            self._ingest_single_profile(p)
        self._ensure_sorted_participants()
        self._emit_updated_counts()
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
        self.refresh_table()
        self._emit_updated_counts()

    def _is_contest_view(self) -> bool:
        return self.filter_combo.currentIndex() in (0, 1)

    def _get_filtered_participants(self):
        self._ensure_sorted_participants()
        cfg = self.get_advanced_filter_config()
        filtered, evals, cat_counts = AdvancedFilterEngine.evaluate_all(
            self.participants, cfg, self._disqualified_keys
        )
        self._last_evaluations = evals
        self._last_category_counts = cat_counts
        self._update_pill_styles()
        self._emit_updated_counts()
        return filtered

    def get_qualified_winners(self):
        """
        Returns all participants who are Qualified Winners (completed 3/3 actions AND
        pass all active AND/OR/NOT/Length/Emoji/Gender rules AND are not disqualified).
        """
        self._ensure_sorted_participants()
        cfg = self.get_advanced_filter_config()
        _, evals, _ = AdvancedFilterEngine.evaluate_all(
            self.participants, cfg, self._disqualified_keys
        )
        self._last_evaluations = evals
        return [
            p for p in self.participants
            if evals.get(p.normalized_key) and evals[p.normalized_key].is_qualified_winner
        ]

    def _get_filtered_raw_profiles(self):
        idx = self.filter_combo.currentIndex()
        raw_list = self.profiles
        if idx == 3:
            raw_list = [p for p in self.profiles if getattr(p, "action_type", "share") == "like"]
        elif idx == 4:
            raw_list = [p for p in self.profiles if getattr(p, "action_type", "share") == "comment"]
        elif idx == 5:
            raw_list = [p for p in self.profiles if getattr(p, "action_type", "share") == "share"]

        cfg = self.get_advanced_filter_config()
        if cfg.has_active_keyword_rules():
            or_list = AdvancedFilterEngine.parse_keyword_list(cfg.or_keywords)
            and_list = AdvancedFilterEngine.parse_keyword_list(cfg.and_keywords)
            not_list = AdvancedFilterEngine.parse_keyword_list(cfg.not_keywords)
            filtered_raw = []
            for p in raw_list:
                txt = (p.content or "").strip()
                if not_list and any(AdvancedFilterEngine.match_single_keyword(txt, k, cfg.match_mode) for k in not_list):
                    continue
                if or_list and not any(AdvancedFilterEngine.match_single_keyword(txt, k, cfg.match_mode) for k in or_list):
                    continue
                if and_list and not all(AdvancedFilterEngine.match_single_keyword(txt, k, cfg.match_mode) for k in and_list):
                    continue
                filtered_raw.append(p)
            raw_list = filtered_raw
        return raw_list

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
                        or (p.combined_notes and query in p.combined_notes.lower())
                    ]
                displayed_slice = displayed[: self.MAX_TABLE_DISPLAY_ROWS]
                self.table.setRowCount(len(displayed_slice))
                eligible_bg = QBrush(QColor(6, 78, 59))            # Deep rich emerald green (#064e3b)
                eligible_fg = QBrush(QColor(240, 253, 244))        # Bright crisp white-mint (#f0fdf4)
                eligible_accent_fg = QBrush(QColor(74, 222, 128))  # Vibrant mint (#4ade80)
                wrong_bg = QBrush(QColor(69, 10, 10))              # Deep crimson for disqualified / wrong answer
                wrong_fg = QBrush(QColor(254, 202, 202))           # Soft rose text
                normal_bg_even = QBrush(QColor(20, 25, 35))        # Dark slate (#141923)
                normal_bg_odd = QBrush(QColor(26, 33, 46))         # Slightly lighter dark slate (#1a212e)
                normal_fg = QBrush(QColor(241, 245, 249))          # High-contrast white-gray (#f1f5f9)
                link_fg = QBrush(QColor(96, 165, 250))             # Bright sky blue (#60a5fa)
                bold_font = QFont()
                bold_font.setBold(True)

                for row, p in enumerate(displayed_slice):
                    ev = self._last_evaluations.get(p.normalized_key)
                    is_qual = ev.is_qualified_winner if ev else p.is_eligible
                    is_bad = bool(ev and (ev.is_disqualified or ev.is_wrong_answer))
                    status_text = ev.reason_badge if (ev and ev.reason_badge) else p.status_label

                    serial_item = QTableWidgetItem(p.serial_code)
                    if is_qual:
                        serial_item.setFont(bold_font)

                    name_item = QTableWidgetItem(p.display_name)
                    if is_qual:
                        name_item.setFont(bold_font)
                    name_item.setData(Qt.UserRole, p.scroll_index)
                    name_item.setData(Qt.UserRole + 1, p.name)
                    name_item.setData(Qt.UserRole + 2, p.normalized_key)
                    icon = self._get_cached_icon(p.avatar_path)
                    if icon:
                        name_item.setIcon(icon)

                    liked_item = QTableWidgetItem("✅ Yes" if p.liked else "❌ No")
                    commented_item = QTableWidgetItem(
                        f"✅ Yes ({len(p.comment_texts)})" if p.commented else "❌ No"
                    )
                    shared_item = QTableWidgetItem("✅ Yes" if p.shared else "❌ No")
                    score_item = QTableWidgetItem(f"{p.actions_completed}/3")
                    if is_qual:
                        score_item.setFont(bold_font)
                    status_item = QTableWidgetItem(status_text)
                    if is_qual or is_bad:
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
                    if is_qual:
                        row_bg = eligible_bg
                        row_fg = eligible_fg
                    elif is_bad:
                        row_bg = wrong_bg
                        row_fg = wrong_fg
                    else:
                        row_bg = normal_bg_even if row % 2 == 0 else normal_bg_odd
                        row_fg = normal_fg

                    for col, cell_item in enumerate(row_items):
                        cell_item.setBackground(row_bg)
                        if is_qual and col in (0, 5, 6):
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
        self._disqualified_keys.clear()
        self._last_evaluations.clear()
        for k in self._last_category_counts:
            self._last_category_counts[k] = 0
        self._update_pill_styles()
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
        eligible = self.get_qualified_winners()
        if not eligible:
            QMessageBox.information(
                self,
                "No Qualified 3/3 Winners Match",
                "No participants currently match all 3 contest actions (Like + Comment + Share) AND active keyword/filter rules.\n\n"
                "Check your OR/AND/NOT keyword filters or collect Likes, Comments, and Shares first!"
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
        qualified = self.get_qualified_winners()
        target_pool = qualified if qualified else self._get_filtered_participants()
        filename = self._get_default_filename("html", prefix="facebook_lottery_tickets")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Printable Lottery Tickets (HTML/PDF)",
            os.path.join("data", filename),
            "HTML Printable Document (*.html)"
        )
        if path:
            if LotteryPrintExporter.export_printable_tickets(target_pool, path):
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
