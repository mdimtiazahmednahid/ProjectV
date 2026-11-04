from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QFileDialog, QMessageBox, QLineEdit,
    QLabel, QComboBox, QSpinBox, QCheckBox, QFrame, QMenu
)
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QDesktopServices, QAction
from app.models.share_profile import ShareProfile, format_reaction_with_emoji, normalize_reaction_type
from app.utils.contest_validator import IncrementalContestAggregator
from app.utils.advanced_filter_engine import (
    AdvancedFilterConfig,
    AdvancedFilterEngine,
    CustomAnalysisRule,
)
from app.utils.text_normalizer import normalize_text
from app.utils.url_normalizer import normalize_url, extract_canonical_identity_key
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
        self.custom_rules = []
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
            "unique_names": 0,
            "male": 0,
            "female": 0,
            "unknown_gender": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
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
            "Only Eligible / Qualified (Ready to Draw ✅)",
            "Raw Collected Items (All)",
            "Raw Reactions Only 👍",
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

        self.btn_toggle_adv = QPushButton("🎯 Sentra Advanced Filters & Action Toggles")
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
        # Sentra Advanced Filter & Action Toggle Bar
        # =========================================================================
        self.adv_frame = QFrame()
        self.adv_frame.setStyleSheet(
            "QFrame#AdvFilterFrame { background-color: #0f172a; border: 1px solid #334155; "
            "border-radius: 8px; padding: 4px; }"
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

        # --- Sub-row 0: 3-Field Chained Action Toggle Bar (Field 1 -> Dropdown 1 -> Field 2 -> Dropdown 2 -> Field 3) ---
        action_bar_layout = QHBoxLayout()
        action_bar_layout.setSpacing(4)

        lbl_act_title = QLabel("⚡ Action Toggle Bar:")
        lbl_act_title.setStyleSheet("color: #fde047; font-size: 11px; font-weight: 800;")
        action_bar_layout.addWidget(lbl_act_title)

        action_field_items = [
            "— Not Selected (Off) —",
            "✅ Reaction",
            "✅ Comment",
            "✅ Share",
        ]
        logic_op_items = [
            "AND (&)",
            "OR (|)",
            "NOT (AND NOT)",
            "OR NOT",
        ]

        # Action Field 1
        self.btn_act_f1 = QPushButton("✓ F1")
        self.btn_act_f1.setCheckable(True)
        self.btn_act_f1.setChecked(True)
        self.btn_act_f1.setToolTip("Toggle Action Field 1 ON or OFF. If OFF, Field 1 is not applied.")
        self.btn_act_f1.toggled.connect(self._on_act_field_btn_toggled)

        self.act_field1_combo = QComboBox()
        self.act_field1_combo.addItems(action_field_items)
        self.act_field1_combo.setCurrentIndex(1)  # 👍 Like
        self.act_field1_combo.setToolTip("Select Action Field 1 (Like, Comment, Share, or Not Selected).")
        self.act_field1_combo.currentIndexChanged.connect(lambda idx: self._on_act_field_combo_changed(1, idx))

        # Action Operator 1 (between Field 1 and Field 2)
        self.act_op1_combo = QComboBox()
        self.act_op1_combo.addItems(logic_op_items)
        self.act_op1_combo.setCurrentIndex(0)  # AND
        self.act_op1_combo.setToolTip(
            "Operator between Field 1 and Field 2:\n"
            "• AND (&): Both Field 1 and Field 2 must match\n"
            "• OR (|): Either Field 1 or Field 2 matches\n"
            "• NOT (AND NOT): Field 1 matches AND Field 2 does NOT match\n"
            "• OR NOT: Field 1 matches OR Field 2 does NOT match"
        )
        self.act_op1_combo.currentIndexChanged.connect(self._on_action_toggle_changed)

        # Action Field 2
        self.btn_act_f2 = QPushButton("✓ F2")
        self.btn_act_f2.setCheckable(True)
        self.btn_act_f2.setChecked(True)
        self.btn_act_f2.setToolTip("Toggle Action Field 2 ON or OFF. If OFF, Field 2 (and Operator 1) won't be applied.")
        self.btn_act_f2.toggled.connect(self._on_act_field_btn_toggled)

        self.act_field2_combo = QComboBox()
        self.act_field2_combo.addItems(action_field_items)
        self.act_field2_combo.setCurrentIndex(2)  # 💬 Comment
        self.act_field2_combo.setToolTip("Select Action Field 2 (Like, Comment, Share, or Not Selected).")
        self.act_field2_combo.currentIndexChanged.connect(lambda idx: self._on_act_field_combo_changed(2, idx))

        # Action Operator 2 (between Field 2 and Field 3)
        self.act_op2_combo = QComboBox()
        self.act_op2_combo.addItems(logic_op_items)
        self.act_op2_combo.setCurrentIndex(0)  # AND
        self.act_op2_combo.setToolTip(
            "Operator between Field 2 and Field 3 (Only applied when Field 3 is selected!):\n"
            "• AND (&): Must also match Field 3\n"
            "• OR (|): Or matches Field 3\n"
            "• NOT (AND NOT): And does NOT match Field 3\n"
            "• OR NOT: Or does NOT match Field 3"
        )
        self.act_op2_combo.currentIndexChanged.connect(self._on_action_toggle_changed)

        # Action Field 3
        self.btn_act_f3 = QPushButton("✓ F3")
        self.btn_act_f3.setCheckable(True)
        self.btn_act_f3.setChecked(True)
        self.btn_act_f3.setToolTip("Toggle Action Field 3 ON or OFF. If not selected, Field 3 won't be applied at all!")
        self.btn_act_f3.toggled.connect(self._on_act_field_btn_toggled)

        self.act_field3_combo = QComboBox()
        self.act_field3_combo.addItems(action_field_items)
        self.act_field3_combo.setCurrentIndex(3)  # 🔄 Share
        self.act_field3_combo.setToolTip("Select Action Field 3 (If 'Not Selected', Field 3 won't be applied).")
        self.act_field3_combo.currentIndexChanged.connect(lambda idx: self._on_act_field_combo_changed(3, idx))

        self.chk_act_group_right = QCheckBox("F1 op (F2 op F3)")
        self.chk_act_group_right.setToolTip(
            "Grouping Order when all 3 fields are active:\n"
            "• Unchecked (Default): (Field 1 [Op1] Field 2) [Op2] Field 3\n"
            "• Checked: Field 1 [Op1] (Field 2 [Op2] Field 3) — e.g. Comment AND (Like OR Share)"
        )
        self.chk_act_group_right.toggled.connect(self._on_action_toggle_changed)

        self.chk_one_entry_per_user = QCheckBox("1 Entry/Person")
        self.chk_one_entry_per_user.setToolTip(
            "Sentra Rule: Ensure each unique person name gets at most 1 winning lottery serial."
        )
        self.chk_one_entry_per_user.toggled.connect(self._on_filter_criteria_changed)

        self.lbl_analytics_summary = QLabel(
            "📊 Unique: 0  |  ♂ Male: 0  ♀ Female: 0  |  😊 Pos: 0  😐 Neu: 0  😠 Neg: 0"
        )
        self.lbl_analytics_summary.setStyleSheet(
            "background-color: #1e293b; color: #93c5fd; font-size: 11px; font-weight: bold; "
            "padding: 3px 8px; border-radius: 5px; border: 1px solid #334155;"
        )

        action_bar_layout.addWidget(self.btn_act_f1)
        action_bar_layout.addWidget(self.act_field1_combo)
        action_bar_layout.addWidget(self.act_op1_combo)
        action_bar_layout.addWidget(self.btn_act_f2)
        action_bar_layout.addWidget(self.act_field2_combo)
        action_bar_layout.addWidget(self.act_op2_combo)
        action_bar_layout.addWidget(self.btn_act_f3)
        action_bar_layout.addWidget(self.act_field3_combo)
        action_bar_layout.addWidget(self.chk_act_group_right)
        action_bar_layout.addWidget(self.chk_one_entry_per_user)
        action_bar_layout.addStretch()
        action_bar_layout.addWidget(self.lbl_analytics_summary)
        adv_main_layout.addLayout(action_bar_layout)

        # --- Sub-row A: 3-Field Chained Keyword Bar (Field 1 -> Dropdown 1 -> Field 2 -> Dropdown 2 -> Field 3) ---
        kw_row = QHBoxLayout()
        kw_row.setSpacing(4)

        lbl_kw_title = QLabel("🔤 Keyword Toggle Bar:")
        lbl_kw_title.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 800;")
        kw_row.addWidget(lbl_kw_title)

        # Keyword Field 1
        self.btn_kw_f1 = QPushButton("✓ K1")
        self.btn_kw_f1.setCheckable(True)
        self.btn_kw_f1.setChecked(True)
        self.btn_kw_f1.setToolTip("Toggle Keyword Field 1 ON or OFF.")
        self.btn_kw_f1.toggled.connect(self._on_action_toggle_changed)

        self.kw_field1_input = QLineEdit()
        self.kw_field1_input.setPlaceholderText("Field 1 keywords (e.g. apple, আপেল, 4, চার)")
        self.kw_field1_input.setToolTip(
            "Keyword Field 1: Enter word(s) or comma-separated synonyms.\n"
            "Supports Bangla + English numerals (4 = ৪) and whole-word matching."
        )
        self.kw_field1_input.textChanged.connect(self._on_action_toggle_changed)

        # Keyword Operator 1 (between Field 1 and Field 2)
        self.kw_op1_combo = QComboBox()
        self.kw_op1_combo.addItems(logic_op_items)
        self.kw_op1_combo.setCurrentIndex(0)  # AND
        self.kw_op1_combo.setToolTip(
            "Operator between Keyword Field 1 and Field 2:\n"
            "• AND (&)  • OR (|)  • NOT (AND NOT)  • OR NOT"
        )
        self.kw_op1_combo.currentIndexChanged.connect(self._on_action_toggle_changed)

        # Keyword Field 2
        self.btn_kw_f2 = QPushButton("✓ K2")
        self.btn_kw_f2.setCheckable(True)
        self.btn_kw_f2.setChecked(True)
        self.btn_kw_f2.setToolTip("Toggle Keyword Field 2 ON or OFF. If unchecked or empty, Field 2 won't be applied.")
        self.btn_kw_f2.toggled.connect(self._on_action_toggle_changed)

        self.kw_field2_input = QLineEdit()
        self.kw_field2_input.setPlaceholderText("Field 2 keywords (optional — off if empty)")
        self.kw_field2_input.setToolTip("Keyword Field 2: Ignored automatically if unchecked or left blank.")
        self.kw_field2_input.textChanged.connect(self._on_action_toggle_changed)

        # Keyword Operator 2 (between Field 2 and Field 3)
        self.kw_op2_combo = QComboBox()
        self.kw_op2_combo.addItems(logic_op_items)
        self.kw_op2_combo.setCurrentIndex(2)  # Default NOT (AND NOT) for Field 3 convenience, user can pick AND/OR/NOT
        self.kw_op2_combo.setToolTip(
            "Operator between Keyword Field 2 and Field 3 (Only applied if Field 3 is active & non-empty!):\n"
            "• AND (&)  • OR (|)  • NOT (AND NOT)  • OR NOT"
        )
        self.kw_op2_combo.currentIndexChanged.connect(self._on_action_toggle_changed)

        # Keyword Field 3
        self.btn_kw_f3 = QPushButton("✓ K3")
        self.btn_kw_f3.setCheckable(True)
        self.btn_kw_f3.setChecked(True)
        self.btn_kw_f3.setToolTip("Toggle Keyword Field 3 ON or OFF. If unchecked or empty, Field 3 won't be applied!")
        self.btn_kw_f3.toggled.connect(self._on_action_toggle_changed)

        self.kw_field3_input = QLineEdit()
        self.kw_field3_input.setPlaceholderText("Field 3 keywords (optional — off if empty)")
        self.kw_field3_input.setToolTip("Keyword Field 3: Ignored automatically if unchecked or left blank.")
        self.kw_field3_input.textChanged.connect(self._on_action_toggle_changed)

        self.chk_kw_group_right = QCheckBox("K1 op (K2 op K3)")
        self.chk_kw_group_right.setToolTip(
            "Grouping Order when all 3 keyword fields are active:\n"
            "• Unchecked (Default): (K1 [Op1] K2) [Op2] K3\n"
            "• Checked: K1 [Op1] (K2 [Op2] K3)"
        )
        self.chk_kw_group_right.toggled.connect(self._on_action_toggle_changed)

        # Keep aliases for backward-compatible references
        self.or_keywords_input = self.kw_field1_input
        self.and_keywords_input = self.kw_field2_input
        self.not_keywords_input = self.kw_field3_input

        kw_row.addWidget(self.btn_kw_f1)
        kw_row.addWidget(self.kw_field1_input, 2)
        kw_row.addWidget(self.kw_op1_combo)
        kw_row.addWidget(self.btn_kw_f2)
        kw_row.addWidget(self.kw_field2_input, 2)
        kw_row.addWidget(self.kw_op2_combo)
        kw_row.addWidget(self.btn_kw_f3)
        kw_row.addWidget(self.kw_field3_input, 2)
        kw_row.addWidget(self.chk_kw_group_right)
        self._update_action_toggle_button_styles()
        adv_main_layout.addLayout(kw_row)

        # --- Sub-row B: Match Mode + Extra Rule Constraints + Custom Rules & Bulk Actions ---
        rules_row = QHBoxLayout()
        rules_row.setSpacing(6)

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

        self.chk_require_tag = QCheckBox("@Mention/#Tag")
        self.chk_require_tag.setToolTip("Require comment or share text to include at least one @mention or #hashtag.")
        self.chk_require_tag.toggled.connect(self._on_filter_criteria_changed)

        lbl_gender = QLabel("Gender:")
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["All Genders", "Male ♂", "Female ♀", "Unknown ?"])
        self.gender_combo.currentIndexChanged.connect(self._on_filter_criteria_changed)

        lbl_sentiment = QLabel("Sentiment:")
        self.sentiment_combo = QComboBox()
        self.sentiment_combo.addItems(["All Sentiment", "Positive 😊", "Neutral 😐", "Negative 😠"])
        self.sentiment_combo.currentIndexChanged.connect(self._on_filter_criteria_changed)

        self.btn_custom_rules = QPushButton("🧠 +Custom Rule (0)")
        self.btn_custom_rules.setToolTip(
            "Open Sentra Global Analyzer Rule Builder to add custom TRUE/FALSE rule columns & filters."
        )
        self.btn_custom_rules.setStyleSheet(
            "background-color: #065f46; color: #a7f3d0; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 4px;"
        )
        self.btn_custom_rules.clicked.connect(self.open_custom_rule_builder)

        self.btn_dq_toggle = QPushButton("🚫 Disqualify")
        self.btn_dq_toggle.setToolTip("Manually Disqualify or Re-Qualify the selected participant row(s).")
        self.btn_dq_toggle.setStyleSheet(
            "background-color: #7f1d1d; color: #fecaca; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 4px;"
        )
        self.btn_dq_toggle.clicked.connect(self.toggle_disqualify_selected)

        self.btn_merge_selected = QPushButton("🔗 Merge Selected")
        self.btn_merge_selected.setToolTip(
            "Sentra Bulk Merge: Combine selected rows into a single participant (merging their Reactions, Comments, and Shares)."
        )
        self.btn_merge_selected.setStyleSheet(
            "background-color: #1d4ed8; color: #ffffff; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 4px;"
        )
        self.btn_merge_selected.clicked.connect(self.merge_selected_participants)

        self.btn_clean_dups = QPushButton("🧹 Clean Dups")
        self.btn_clean_dups.setToolTip(
            "Merge/remove duplicate same-name entries, keeping the consolidated record per name."
        )
        self.btn_clean_dups.setStyleSheet(
            "background-color: #334155; color: #e2e8f0; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 4px;"
        )
        self.btn_clean_dups.clicked.connect(self.clean_duplicate_names)

        self.btn_reset_filters = QPushButton("↺ Reset")
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
        rules_row.addWidget(lbl_sentiment)
        rules_row.addWidget(self.sentiment_combo)
        rules_row.addStretch()
        rules_row.addWidget(self.btn_custom_rules)
        rules_row.addWidget(self.btn_dq_toggle)
        rules_row.addWidget(self.btn_merge_selected)
        rules_row.addWidget(self.btn_clean_dups)
        rules_row.addWidget(self.btn_reset_filters)
        adv_main_layout.addLayout(rules_row)

        # --- Sub-row B2: Live Active Formula Preview Banner ---
        self.lbl_active_formula = QLabel("📐 Active Winner Rule: 👍 Like AND 💬 Comment AND 🔄 Share")
        self.lbl_active_formula.setStyleSheet(
            "background-color: #172554; color: #93c5fd; font-size: 11px; font-weight: bold; "
            "padding: 3px 8px; border-radius: 5px; border: 1px solid #1e40af;"
        )
        adv_main_layout.addWidget(self.lbl_active_formula)

        # --- Sub-row C: DrawSystem Interactive Quick Category Filter Pills (with Live Counts & %) ---
        pills_row = QHBoxLayout()
        pills_row.setSpacing(5)
        self._category_buttons = {}
        pill_specs = [
            ("all", "All", "#334155", "#2563eb"),
            ("qualified", "✅ Qualified Winners", "#065f46", "#10b981"),
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
        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            "Serial #", "Name & Avatar", "Reaction 👍", "Commented 💬", "Shared 🔄",
            "Score", "Contest Status", "Comment Text 💬", "Shared Caption 🔄",
            "Identity / Profile URL", "Shared Post Link 🔗"
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
        self.btn_print_lottery = QPushButton("🖨️ Print Lottery Slips (Qualified)")
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

    def _on_act_field_btn_toggled(self, *args):
        """
        Synchronizes the toggle button (✓ F1, ✓ F2, ✓ F3) with the dropdown selection:
        If the user re-checks a toggle button whose dropdown was '— Not Selected (Off) —',
        automatically select the default action for that slot (F1=Like, F2=Comment, F3=Share).
        """
        slot_defaults = [
            (self.btn_act_f1, self.act_field1_combo, 1),
            (self.btn_act_f2, self.act_field2_combo, 2),
            (self.btn_act_f3, self.act_field3_combo, 3),
        ]
        for btn, combo, default_idx in slot_defaults:
            if btn.isChecked() and combo.currentIndex() == 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(default_idx)
                combo.blockSignals(False)
        self._on_action_toggle_changed()

    def _on_act_field_combo_changed(self, slot_num: int, idx: int):
        """
        If user picks '— Not Selected (Off) —' (index 0) in a Field dropdown,
        automatically uncheck that field's toggle button so it's visually OFF and not applied.
        If user picks Like / Comment / Share (index > 0), automatically check that field's toggle button.
        """
        btn_map = {
            1: self.btn_act_f1,
            2: self.btn_act_f2,
            3: self.btn_act_f3,
        }
        btn = btn_map.get(slot_num)
        if btn is not None:
            btn.blockSignals(True)
            btn.setChecked(idx > 0)
            btn.blockSignals(False)
        self._on_action_toggle_changed()

    def _on_action_toggle_changed(self, *args):
        self._update_action_toggle_button_styles()
        self._on_filter_criteria_changed()

    def _update_action_toggle_button_styles(self):
        # 1) Style Action Toggle Bar (Field 1, Field 2, Field 3 + Dropdowns)
        act_slots = [
            (self.btn_act_f1, self.act_field1_combo, None, "F1", "#16a34a"),
            (self.btn_act_f2, self.act_field2_combo, self.act_op1_combo, "F2", "#2563eb"),
            (self.btn_act_f3, self.act_field3_combo, self.act_op2_combo, "F3", "#9333ea"),
        ]
        for btn, combo, op_combo, label, on_bg in act_slots:
            is_selected = btn.isChecked() and combo.currentIndex() > 0
            btn.setText(f"{'✓' if is_selected else '✗'} {label}")
            combo.setEnabled(btn.isChecked())
            if op_combo is not None:
                op_combo.setEnabled(is_selected)
            if is_selected:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {on_bg}; color: #ffffff; font-weight: 800; "
                    f"font-size: 11px; padding: 3px 8px; border-radius: 5px; border: 1px solid #ffffff; }}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background-color: #334155; color: #94a3b8; font-weight: bold; "
                    "font-size: 11px; padding: 3px 8px; border-radius: 5px; border: 1px solid #475569; }"
                )

        # 2) Style Keyword Toggle Bar (K1, K2, K3 + Dropdowns)
        kw_slots = [
            (self.btn_kw_f1, self.kw_field1_input, None, "K1", "#0284c7"),
            (self.btn_kw_f2, self.kw_field2_input, self.kw_op1_combo, "K2", "#0d9488"),
            (self.btn_kw_f3, self.kw_field3_input, self.kw_op2_combo, "K3", "#7c3aed"),
        ]
        for btn, line_edit, op_combo, label, on_bg in kw_slots:
            is_checked = btn.isChecked()
            has_text = bool((line_edit.text() or "").strip())
            is_active = is_checked and has_text
            line_edit.setEnabled(is_checked)
            if op_combo is not None:
                op_combo.setEnabled(is_active)
            btn.setText(f"{'✓' if is_checked else '✗'} {label}")
            if is_active:
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {on_bg}; color: #ffffff; font-weight: 800; "
                    f"font-size: 11px; padding: 3px 8px; border-radius: 5px; border: 1px solid #ffffff; }}"
                )
            elif is_checked:
                btn.setStyleSheet(
                    "QPushButton { background-color: #1e293b; color: #38bdf8; font-weight: bold; "
                    "font-size: 11px; padding: 3px 8px; border-radius: 5px; border: 1px solid #0284c7; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background-color: #334155; color: #94a3b8; font-weight: bold; "
                    "font-size: 11px; padding: 3px 8px; border-radius: 5px; border: 1px solid #475569; }"
                )
        self._update_active_formula_banner()

    def _update_active_formula_banner(self):
        if not hasattr(self, "lbl_active_formula") or not hasattr(self, "match_mode_combo"):
            return
        try:
            cfg = self.get_advanced_filter_config()
            self.lbl_active_formula.setText(f"📐 Active Winner Rule: {cfg.describe_full_rules()}")
        except Exception:
            pass

    def _on_view_mode_changed(self, idx: int):
        self.refresh_table()

    def _on_filter_criteria_changed(self, *args):
        self._update_active_formula_banner()
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

        # Also update the live FairDraw Analytics bar (Unique, Gender, Sentiment)
        c = self._last_category_counts
        self.lbl_analytics_summary.setText(
            f"📊 Unique: {c.get('unique_names', 0)}  |  "
            f"♂ Male: {c.get('male', 0)}  ♀ Female: {c.get('female', 0)}  |  "
            f"😊 Pos: {c.get('positive', 0)}  😐 Neu: {c.get('neutral', 0)}  😠 Neg: {c.get('negative', 0)}"
        )

    def get_advanced_filter_config(self) -> AdvancedFilterConfig:
        act_val_map = {
            0: "none",
            1: "like",
            2: "comment",
            3: "share",
        }
        logic_op_map = {
            0: "AND",
            1: "OR",
            2: "NOT",
            3: "OR_NOT",
        }
        mode_map = {
            0: "whole_word",
            1: "contains",
            2: "exact",
            3: "regex",
        }
        gender_map = {
            0: "all",
            1: "male",
            2: "female",
            3: "unknown",
        }
        sentiment_map = {
            0: "all",
            1: "positive",
            2: "neutral",
            3: "negative",
        }
        effective_category = self._active_quick_category
        if self.filter_combo.currentIndex() == 1 and effective_category == "all":
            effective_category = "qualified"

        f1_val = act_val_map.get(self.act_field1_combo.currentIndex(), "none")
        f2_val = act_val_map.get(self.act_field2_combo.currentIndex(), "none")
        f3_val = act_val_map.get(self.act_field3_combo.currentIndex(), "none")

        f1_on = self.btn_act_f1.isChecked() and f1_val != "none"
        f2_on = self.btn_act_f2.isChecked() and f2_val != "none"
        f3_on = self.btn_act_f3.isChecked() and f3_val != "none"

        active_actions = set()
        if f1_on:
            active_actions.add(f1_val)
        if f2_on:
            active_actions.add(f2_val)
        if f3_on:
            active_actions.add(f3_val)

        return AdvancedFilterConfig(
            require_like=("like" in active_actions),
            require_comment=("comment" in active_actions),
            require_share=("share" in active_actions),
            action_operator=logic_op_map.get(self.act_op1_combo.currentIndex(), "AND"),
            use_action_chain=True,
            act_f1_enabled=f1_on,
            act_f1_val=f1_val,
            act_op1=logic_op_map.get(self.act_op1_combo.currentIndex(), "AND"),
            act_f2_enabled=f2_on,
            act_f2_val=f2_val,
            act_op2=logic_op_map.get(self.act_op2_combo.currentIndex(), "AND"),
            act_f3_enabled=f3_on,
            act_f3_val=f3_val,
            act_group_right=self.chk_act_group_right.isChecked(),
            use_keyword_chain=True,
            kw_f1_enabled=self.btn_kw_f1.isChecked(),
            kw_f1_text=self.kw_field1_input.text() or "",
            kw_op1=logic_op_map.get(self.kw_op1_combo.currentIndex(), "AND"),
            kw_f2_enabled=self.btn_kw_f2.isChecked(),
            kw_f2_text=self.kw_field2_input.text() or "",
            kw_op2=logic_op_map.get(self.kw_op2_combo.currentIndex(), "NOT"),
            kw_f3_enabled=self.btn_kw_f3.isChecked(),
            kw_f3_text=self.kw_field3_input.text() or "",
            kw_group_right=self.chk_kw_group_right.isChecked(),
            or_keywords=self.kw_field1_input.text() or "",
            and_keywords=self.kw_field2_input.text() or "",
            not_keywords=self.kw_field3_input.text() or "",
            match_mode=mode_map.get(self.match_mode_combo.currentIndex(), "whole_word"),
            min_comment_length=self.spin_min_len.value(),
            min_word_count=self.spin_min_words.value(),
            exclude_invalid_emoji=self.chk_exclude_emoji.isChecked(),
            require_mention_or_hashtag=self.chk_require_tag.isChecked(),
            gender_filter=gender_map.get(self.gender_combo.currentIndex(), "all"),
            sentiment_filter=sentiment_map.get(self.sentiment_combo.currentIndex(), "all"),
            one_entry_per_user=self.chk_one_entry_per_user.isChecked(),
            quick_category=effective_category,
            custom_rules=list(self.custom_rules),
        )

    def open_custom_rule_builder(self):
        from app.gui.custom_rule_dialog import CustomRuleBuilderDialog
        dlg = CustomRuleBuilderDialog(self.custom_rules, parent=self)
        if dlg.exec():
            self.custom_rules = list(dlg.rules)
            self.btn_custom_rules.setText(f"🧠 +Custom Rule ({len(self.custom_rules)})")
            self.refresh_table()

    def reset_advanced_filters(self):
        widgets = (
            self.btn_act_f1,
            self.act_field1_combo,
            self.act_op1_combo,
            self.btn_act_f2,
            self.act_field2_combo,
            self.act_op2_combo,
            self.btn_act_f3,
            self.act_field3_combo,
            self.chk_act_group_right,
            self.chk_one_entry_per_user,
            self.btn_kw_f1,
            self.kw_field1_input,
            self.kw_op1_combo,
            self.btn_kw_f2,
            self.kw_field2_input,
            self.kw_op2_combo,
            self.btn_kw_f3,
            self.kw_field3_input,
            self.chk_kw_group_right,
            self.match_mode_combo,
            self.spin_min_len,
            self.spin_min_words,
            self.chk_exclude_emoji,
            self.chk_require_tag,
            self.gender_combo,
            self.sentiment_combo,
        )
        for w in widgets:
            w.blockSignals(True)
        self.btn_act_f1.setChecked(True)
        self.act_field1_combo.setCurrentIndex(1)  # 👍 Like
        self.act_op1_combo.setCurrentIndex(0)     # AND
        self.btn_act_f2.setChecked(True)
        self.act_field2_combo.setCurrentIndex(2)  # 💬 Comment
        self.act_op2_combo.setCurrentIndex(0)     # AND
        self.btn_act_f3.setChecked(True)
        self.act_field3_combo.setCurrentIndex(3)  # 🔄 Share
        self.chk_act_group_right.setChecked(False)
        self.chk_one_entry_per_user.setChecked(False)
        self.btn_kw_f1.setChecked(True)
        self.kw_field1_input.clear()
        self.kw_op1_combo.setCurrentIndex(0)      # AND
        self.btn_kw_f2.setChecked(True)
        self.kw_field2_input.clear()
        self.kw_op2_combo.setCurrentIndex(2)      # NOT
        self.btn_kw_f3.setChecked(True)
        self.kw_field3_input.clear()
        self.chk_kw_group_right.setChecked(False)
        self.match_mode_combo.setCurrentIndex(0)
        self.spin_min_len.setValue(0)
        self.spin_min_words.setValue(0)
        self.chk_exclude_emoji.setChecked(False)
        self.chk_require_tag.setChecked(False)
        self.gender_combo.setCurrentIndex(0)
        self.sentiment_combo.setCurrentIndex(0)
        for w in widgets:
            w.blockSignals(False)
        self._update_action_toggle_button_styles()
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

    def merge_selected_participants(self):
        """
        Matches DrawSystem's 'Bulk Merge' (`ParticipantController.php::bulkMerge`):
        Combines 2 or more selected rows into the first selected participant (merging
        their Likes, Comments, Shares, and Profile URL).
        """
        if not self._is_contest_view():
            return
        selected_rows = sorted({item.row() for item in self.table.selectedItems()})
        if len(selected_rows) < 2:
            QMessageBox.information(
                self,
                "Select 2+ Rows to Merge",
                "Hold Ctrl/Cmd or Shift to select at least 2 participant rows in the table, then click '🔗 Merge Selected'."
            )
            return

        selected_keys = []
        for row in selected_rows:
            name_item = self.table.item(row, 1)
            if name_item:
                k = name_item.data(Qt.UserRole + 2)
                if k and k not in selected_keys:
                    selected_keys.append(k)

        if len(selected_keys) < 2:
            return

        by_key = {p.normalized_key: p for p in self.participants}
        master = by_key.get(selected_keys[0])
        if not master:
            return

        merged_count = 0
        keys_to_remove = set(selected_keys[1:])
        merged_names_lower = set()
        merged_urls_lower = set()
        for k in selected_keys[1:]:
            other = by_key.get(k)
            if not other:
                continue
            if other.name:
                merged_names_lower.add(normalize_text(other.name).lower())
            if other.profile_url:
                merged_urls_lower.add(other.profile_url.strip().lower())
            master.liked = master.liked or other.liked
            master.commented = master.commented or other.commented
            master.shared = master.shared or other.shared
            for rt in getattr(other, "reaction_types", []):
                if rt and rt not in master.reaction_types:
                    master.reaction_types.append(rt)
            for c in other.comment_texts:
                if c not in master.comment_texts:
                    master.comment_texts.append(c)
            for s in other.share_contents:
                if s not in master.share_contents:
                    master.share_contents.append(s)
            for sp_url in getattr(other, "shared_post_urls", []):
                if sp_url and sp_url not in master.shared_post_urls:
                    master.shared_post_urls.append(sp_url)
            if not master.profile_url and other.profile_url:
                master.profile_url = other.profile_url
            if not master.avatar_hash and other.avatar_hash:
                master.avatar_hash = other.avatar_hash
                master.avatar_path = other.avatar_path
            merged_count += 1

        # Also unify underlying ShareProfile records so future profile syncs preserve this merge
        for sp in self.profiles:
            sp_nm = normalize_text(sp.name or "").lower()
            sp_url = (sp.profile_url or "").strip().lower()
            if (sp_url and sp_url in merged_urls_lower) or (sp_nm and sp_nm in merged_names_lower):
                sp.name = master.name
                if master.profile_url:
                    sp.profile_url = master.profile_url
                if master.avatar_hash and not sp.avatar_hash:
                    sp.avatar_hash = master.avatar_hash
                    sp.avatar_path = master.avatar_path

        self.aggregator.participants = [
            p for p in self.aggregator.participants if p.normalized_key not in keys_to_remove
        ]
        self.aggregator.recalculate_state()
        self._participants_dirty = True
        self._ensure_sorted_participants()
        self.refresh_table()
        self._emit_updated_counts()
        QMessageBox.information(
            self,
            "Participants Merged",
            f"Merged {merged_count + 1} selected entries into '{master.display_name}'!"
        )

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
                for rt in getattr(p, "reaction_types", []):
                    if rt and rt not in primary.reaction_types:
                        primary.reaction_types.append(rt)
                for c in p.comment_texts:
                    if c not in primary.comment_texts:
                        primary.comment_texts.append(c)
                for s in p.share_contents:
                    if s not in primary.share_contents:
                        primary.share_contents.append(s)
                for sp_url in getattr(p, "shared_post_urls", []):
                    if sp_url and sp_url not in primary.shared_post_urls:
                        primary.shared_post_urls.append(sp_url)
                if not primary.profile_url and p.profile_url:
                    primary.profile_url = p.profile_url
                if not primary.avatar_hash and p.avatar_hash:
                    primary.avatar_hash = p.avatar_hash
                    primary.avatar_path = p.avatar_path
                duplicates_merged += 1

        if duplicates_merged == 0:
            QMessageBox.information(self, "No Duplicates Found", "No duplicate participant names were found.")
            return

        # Propagate consolidated profile_url / avatar_hash to underlying raw profiles with the same name
        for sp in self.profiles:
            nm = normalize_text(sp.name or "").lower().strip()
            primary = by_name.get(nm)
            if primary:
                if primary.profile_url:
                    sp.profile_url = primary.profile_url
                if primary.avatar_hash:
                    sp.avatar_hash = primary.avatar_hash
                    sp.avatar_path = primary.avatar_path

        self.aggregator.participants = new_participants
        self.aggregator.recalculate_state()
        self._participants_dirty = True
        self._ensure_sorted_participants()
        self.refresh_table()
        self._emit_updated_counts()
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

        act_merge = QAction("🔗 Merge Selected Participants (Combine Actions & Comments)", self)
        act_merge.triggered.connect(self.merge_selected_participants)
        menu.addAction(act_merge)

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
        url_cols = (9, 10) if self._is_contest_view() else (2, 3)
        if col in url_cols:
            txt = (item.text() or "").strip()
            if txt.startswith("http://") or txt.startswith("https://"):
                QDesktopServices.openUrl(QUrl(txt))

    def _ingest_single_profile(self, profile: ShareProfile):
        if profile.profile_url:
            profile.profile_url = normalize_url(profile.profile_url)
        norm_name = IncrementalContestAggregator._clean_author_name(profile.name or "").lower()
        act_type = (getattr(profile, "action_type", "share") or "share").lower()
        id_key = extract_canonical_identity_key(profile.profile_url) if profile.profile_url else ""
        content_snip = (profile.content or "").strip()[:120]

        raw_key = (norm_name, act_type, id_key or "", content_snip)
        existing = self._raw_dedupe_map.get(raw_key)

        # For 'like', deduplicate by person regardless of whether the first pass had a reaction label or not, and upgrade the reaction in-place!
        if existing is None and act_type == "like":
            empty_like_key = (norm_name, "like", id_key or "", "")
            existing = self._raw_dedupe_map.get(empty_like_key)
            if existing is None:
                for k, v in self._raw_dedupe_map.items():
                    if k[0] == norm_name and k[1] == "like" and (k[2] == (id_key or "") or not k[2] or not id_key):
                        existing = v
                        break
            if existing is not None:
                self._raw_dedupe_map[raw_key] = existing

        # For 'share', if an earlier pass captured the sharer without caption (or truncated) and a later pass has full caption/post link, upgrade in-place!
        if existing is None and act_type == "share":
            empty_share_key = (norm_name, "share", id_key or "", "")
            existing = self._raw_dedupe_map.get(empty_share_key)
            if existing is not None:
                self._raw_dedupe_map[raw_key] = existing

        # If previously ingested without URL on an earlier day/pass, upgrade the URL-less record in-place!
        if existing is None and id_key:
            no_url_key = (norm_name, act_type, "", content_snip)
            existing = self._raw_dedupe_map.get(no_url_key)
            if existing is not None:
                self._raw_dedupe_map[raw_key] = existing

        # Conversely, if already ingested WITH URL on an earlier day and now seen without URL, reuse existing!
        if existing is None and not id_key:
            for k, v in self._raw_dedupe_map.items():
                if k[0] == norm_name and k[1] == act_type and (k[3] == content_snip or act_type in ("share", "like")) and k[2]:
                    existing = v
                    break

        if existing is not None:
            if profile.profile_url and (not existing.profile_url or "/people/" in existing.profile_url.lower()):
                existing.profile_url = profile.profile_url
            if getattr(profile, "shared_post_url", None) and not getattr(existing, "shared_post_url", None):
                existing.shared_post_url = profile.shared_post_url
            if not existing.avatar_hash and profile.avatar_hash:
                existing.avatar_hash = profile.avatar_hash
                existing.avatar_path = profile.avatar_path
            if getattr(profile, "last_seen_at", None):
                existing.last_seen_at = profile.last_seen_at
            if act_type == "like":
                r_inc = normalize_reaction_type(profile.reactions) or normalize_reaction_type(profile.content)
                if r_inc:
                    existing.reactions = r_inc
                    existing.content = r_inc
            elif profile.content and (not existing.content or len(profile.content) > len(existing.content)):
                existing.content = profile.content
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
            self.get_advanced_filter_config().has_any_rule_constraints()
            or self.get_advanced_filter_config().one_entry_per_user
            or self._disqualified_keys
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
        Returns all participants who are Qualified Winners (satisfy active Action Toggle Bar
        AND pass all active AND/OR/NOT/Length/Emoji/Gender/Sentiment/Custom rules AND are not disqualified).
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
            filtered_raw = []
            for p in raw_list:
                txt = (p.content or "").strip()
                if cfg.use_keyword_chain:
                    f1_txt = (cfg.kw_f1_text or "").strip()
                    f2_txt = (cfg.kw_f2_text or "").strip()
                    f3_txt = (cfg.kw_f3_text or "").strip()
                    f1_sel = bool(cfg.kw_f1_enabled and f1_txt)
                    f2_sel = bool(cfg.kw_f2_enabled and f2_txt)
                    f3_sel = bool(cfg.kw_f3_enabled and f3_txt)
                    f1_pass = AdvancedFilterEngine.evaluate_keyword_slot(txt, f1_txt, cfg.match_mode) if f1_sel else True
                    f2_pass = AdvancedFilterEngine.evaluate_keyword_slot(txt, f2_txt, cfg.match_mode) if f2_sel else True
                    f3_pass = AdvancedFilterEngine.evaluate_keyword_slot(txt, f3_txt, cfg.match_mode) if f3_sel else True
                    if not AdvancedFilterEngine.evaluate_three_slot_chain(
                        [(f1_sel, f1_pass), (f2_sel, f2_pass), (f3_sel, f3_pass)],
                        cfg.kw_op1,
                        cfg.kw_op2,
                        cfg.kw_group_right,
                    ):
                        continue
                else:
                    or_list = AdvancedFilterEngine.parse_keyword_list(cfg.or_keywords)
                    and_list = AdvancedFilterEngine.parse_keyword_list(cfg.and_keywords)
                    not_list = AdvancedFilterEngine.parse_keyword_list(cfg.not_keywords)
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
                base_headers = [
                    "Serial #", "Name & Avatar", "Reaction", "Comment", "Share",
                    "Score", "Contest Status", "Comment Text 💬", "Shared Caption 🔄",
                    "Identity / Profile URL", "Shared Post Link 🔗"
                ]
                rule_headers = [f"🧠 {r.name}" for r in self.custom_rules]
                all_headers = base_headers + rule_headers
                self.table.setColumnCount(len(all_headers))
                self.table.setHorizontalHeaderLabels(all_headers)

                displayed = self._get_filtered_participants()
                query = (self.search_input.text() or "").strip().lower()
                if query:
                    displayed = [
                        p for p in displayed
                        if query in p.display_name.lower()
                        or query in p.serial_code.lower()
                        or (p.profile_url and query in p.profile_url.lower())
                        or (p.primary_shared_post_url and query in p.primary_shared_post_url.lower())
                        or (p.combined_notes and query in p.combined_notes.lower())
                        or (p.combined_reactions and query in p.combined_reactions.lower())
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

                    liked_item = QTableWidgetItem(p.reaction_badge)
                    if p.reaction_types:
                        liked_item.setToolTip(f"Reacted: {p.combined_reactions}")
                    commented_item = QTableWidgetItem(
                        f"✅ Comment ({len(p.comment_texts)})" if p.commented else "❌ Comment"
                    )
                    shared_label = (
                        f"✅ Share ({len(p.share_contents)})"
                        if (p.shared and p.share_contents)
                        else ("✅ Share" if p.shared else "❌ Share")
                    )
                    shared_item = QTableWidgetItem(shared_label)
                    score_item = QTableWidgetItem(f"{p.actions_completed}/3")
                    if is_qual:
                        score_item.setFont(bold_font)
                    status_item = QTableWidgetItem(status_text)
                    if is_qual or is_bad:
                        status_item.setFont(bold_font)

                    comment_preview = p.combined_comments
                    if len(comment_preview) > 55:
                        comment_preview = comment_preview[:52] + "..."
                    comment_text_item = QTableWidgetItem(comment_preview)
                    comment_text_item.setToolTip(p.combined_comments)

                    share_caption_preview = p.combined_share_captions
                    if len(share_caption_preview) > 55:
                        share_caption_preview = share_caption_preview[:52] + "..."
                    share_caption_item = QTableWidgetItem(share_caption_preview)
                    share_caption_item.setToolTip(p.combined_share_captions)

                    id_text = p.profile_url or (f"AvatarHash:{p.avatar_hash[:8]}" if p.avatar_hash else "")
                    url_item = QTableWidgetItem(id_text)
                    if p.profile_url:
                        url_item.setToolTip(p.profile_url)

                    shared_post_link = p.primary_shared_post_url
                    shared_post_item = QTableWidgetItem(shared_post_link)
                    if p.shared_post_urls:
                        shared_post_item.setToolTip("\n".join(p.shared_post_urls))

                    row_items = [
                        serial_item, name_item, liked_item, commented_item, shared_item,
                        score_item, status_item, comment_text_item, share_caption_item,
                        url_item, shared_post_item
                    ]
                    for r_obj in self.custom_rules:
                        passed_r = ev.custom_rule_results.get(r_obj.id, False) if ev else False
                        r_item = QTableWidgetItem("✅ TRUE" if passed_r else "❌ FALSE")
                        if passed_r:
                            r_item.setFont(bold_font)
                        row_items.append(r_item)

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
                        elif col == 9 and p.profile_url:
                            cell_item.setForeground(link_fg)
                        elif col == 10 and shared_post_link:
                            cell_item.setForeground(link_fg)
                        else:
                            cell_item.setForeground(row_fg)
                        self.table.setItem(row, col, cell_item)
            else:
                self.table.setColumnCount(9)
                self.table.setHorizontalHeaderLabels([
                    "Name", "Action", "Profile URL", "Shared Post Link 🔗", "Content / Shared Caption",
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
                        or (getattr(p, "shared_post_url", None) and query in p.shared_post_url.lower())
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
                    if profile.profile_url:
                        url_item.setToolTip(profile.profile_url)

                    post_url_str = getattr(profile, "shared_post_url", None) or ""
                    post_url_item = QTableWidgetItem(post_url_str)
                    if post_url_str:
                        post_url_item.setToolTip(post_url_str)

                    content_preview = profile.content or ""
                    if len(content_preview) > 55:
                        content_preview = content_preview[:52] + "..."
                    content_item = QTableWidgetItem(content_preview)
                    content_item.setToolTip(profile.content or "")

                    raw_react_str = profile.reactions or "0"
                    if getattr(profile, "action_type", "share") == "like":
                        r_fmt = format_reaction_with_emoji(profile.reactions or profile.content)
                        if r_fmt:
                            raw_react_str = r_fmt
                        elif raw_react_str == "0":
                            raw_react_str = "Reacted"
                    react_item = QTableWidgetItem(raw_react_str)
                    comm_item = QTableWidgetItem(profile.comments or "0")
                    conf_item = QTableWidgetItem(f"{profile.confidence:.2f}")
                    seen_item = QTableWidgetItem(profile.first_seen_at.split('.')[0].replace('T', ' '))

                    raw_cells = [
                        name_item, action_item, url_item, post_url_item, content_item,
                        react_item, comm_item, conf_item, seen_item
                    ]
                    r_bg = raw_bg_even if row % 2 == 0 else raw_bg_odd
                    for col, c_item in enumerate(raw_cells):
                        c_item.setBackground(r_bg)
                        if (col == 2 and profile.profile_url) or (col == 3 and post_url_str):
                            c_item.setForeground(link_fg)
                        else:
                            c_item.setForeground(raw_fg)
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
            prefix = "sentra_eligible" if self.filter_combo.currentIndex() == 1 else "sentra_results"
        return f"{prefix}_{timestamp}.{ext}"

    def _disqualify_from_live_draw(self, winner):
        if winner and winner.normalized_key:
            self._disqualified_keys.add(winner.normalized_key)
            self.refresh_table()

    def open_live_lottery_draw(self):
        eligible = self.get_qualified_winners()
        cfg = self.get_advanced_filter_config()
        rule_desc = cfg.describe_full_rules()

        if not eligible:
            QMessageBox.information(
                self,
                "No Qualified Winners Match",
                f"No participants currently match your active Action & Keyword rules:\n\n"
                f"• {rule_desc}\n\n"
                f"Adjust the Action Toggle Bar (👍 Like / 💬 Comment / 🔄 Share) or keyword filters above!"
            )
            return
        from app.gui.live_lottery_dialog import LiveLotteryDialog
        dlg = LiveLotteryDialog(
            eligible,
            parent=self,
            rule_summary_text=rule_desc,
            on_disqualify_callback=self._disqualify_from_live_draw,
        )
        dlg.exec()

    def export_printable_lottery(self):
        self._ensure_sorted_participants()
        if not self.participants:
            QMessageBox.information(self, "No Data", "Collect Likes, Comments, and Shares first to generate lottery tickets.")
            return
        qualified = self.get_qualified_winners()
        qualified_keys = {p.normalized_key for p in qualified}
        if self._active_quick_category == "qualified" or self.filter_combo.currentIndex() == 1:
            default_scope = "qualified" if qualified else "all"
        elif self._active_quick_category in ("disqualified", "wrong", "no_comments"):
            default_scope = "disqualified"
        else:
            default_scope = "all"

        from app.database.repository import ensure_writable_data_dir
        data_dir = ensure_writable_data_dir("data")
        filename = self._get_default_filename("html", prefix="sentra_lottery_tickets")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Sentra Printable Lottery Tickets (HTML/PDF)",
            os.path.join(data_dir, filename),
            "HTML Printable Document (*.html)"
        )
        if path:
            if LotteryPrintExporter.export_printable_tickets(
                self.participants,
                path,
                qualified_keys=qualified_keys,
                evaluations=self._last_evaluations,
                default_scope=default_scope,
            ):
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))
                QMessageBox.information(
                    self,
                    "Lottery Tickets Ready",
                    f"Printable Lottery Slips & Judge Verification Sheet opened in your browser!\n\n"
                    f"• Total Participants Embedded: {len(self.participants)} ({len(qualified)} Qualified ✅, {len(self.participants) - len(qualified)} Disqualified/Incomplete ❌)\n"
                    f"• Use the 'Show:' dropdown at the top of the page to switch between All Participants, Qualified Only, or Disqualified Only.\n\n"
                    f"Saved to: {path}"
                )
            else:
                QMessageBox.critical(self, "Export Error", "Failed to generate printable lottery tickets.")

    def export_csv(self):
        if not self.profiles:
            return
        from app.database.repository import ensure_writable_data_dir
        data_dir = ensure_writable_data_dir("data")
        filename = self._get_default_filename("csv")
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", os.path.join(data_dir, filename), "CSV Files (*.csv)")
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
        from app.database.repository import ensure_writable_data_dir
        data_dir = ensure_writable_data_dir("data")
        filename = self._get_default_filename("json")
        path, _ = QFileDialog.getSaveFileName(self, "Export JSON", os.path.join(data_dir, filename), "JSON Files (*.json)")
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
        from app.database.repository import ensure_writable_data_dir
        data_dir = ensure_writable_data_dir("data")
        filename = self._get_default_filename("xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Export XLSX", os.path.join(data_dir, filename), "Excel Files (*.xlsx)")
        if path:
            if self._is_contest_view():
                ok = XLSXExporter.export_contest(self._get_filtered_participants(), path)
            else:
                ok = XLSXExporter.export(self._get_filtered_raw_profiles(), path)
            if ok:
                QMessageBox.information(self, "Export", "XLSX Export successful.")
            else:
                QMessageBox.critical(self, "Export", "XLSX Export failed. Is openpyxl installed?")
