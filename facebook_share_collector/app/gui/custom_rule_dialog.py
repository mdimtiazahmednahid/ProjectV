import uuid
from typing import List
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QListWidget, QListWidgetItem, QFrame, QMessageBox
)
from PySide6.QtCore import Qt
from app.utils.advanced_filter_engine import CustomAnalysisRule


class CustomRuleBuilderDialog(QDialog):
    """
    Implements DrawSystem's 'Global Analyzer -> Create Rule' Modal (`analyzer.blade.php` lines 162-203, 442-550):
    Allows the user to define custom intelligence rules that:
      1. Add dynamic TRUE / FALSE columns to the Contest Validation table.
      2. Optionally enforce that a participant must pass the rule to be a Qualified Winner.
    """

    RULE_TYPES = [
        ("keyword_match", "Keyword Match — Whole Word (OR: Any word)"),
        ("keyword_contains", "Keyword Contains — Partial Substring (OR)"),
        ("keyword_all", "Keyword Match ALL — Must contain EVERY word (AND)"),
        ("keyword_exact", "Exact Answer Match — Strictly exact comment"),
        ("keyword_exclude", "Keyword Exclude — Must NOT contain words (NOT)"),
        ("boolean_expr", "Boolean Expression — e.g. (apple OR আপেল) AND 4 NOT 14"),
        ("action_combo", "Custom Action Formula — e.g. (like AND comment) OR share"),
        ("regex_match", "Regex Pattern Match (Advanced)"),
        ("length_greater", "Comment Length >= X characters"),
        ("has_tags", "Has @Mentions or #Hashtags"),
    ]

    def __init__(self, existing_rules: List[CustomAnalysisRule], parent=None):
        super().__init__(parent)
        self.rules: List[CustomAnalysisRule] = [
            CustomAnalysisRule(
                id=r.id,
                name=r.name,
                rule_type=r.rule_type,
                value=r.value,
                enforce_for_qualification=r.enforce_for_qualification,
            )
            for r in existing_rules
        ]
        self.setWindowTitle("⚙️ FairDraw Custom Intelligence Rule Builder")
        self.resize(620, 480)
        self.setStyleSheet(
            "QDialog { background-color: #0f172a; color: #f8fafc; }"
            "QLabel { color: #e2e8f0; font-size: 12px; font-weight: bold; }"
            "QLineEdit, QComboBox { background-color: #1e293b; color: #ffffff; border: 1px solid #475569; "
            "border-radius: 6px; padding: 6px 8px; font-size: 12px; }"
            "QCheckBox { color: #cbd5e1; font-size: 12px; font-weight: bold; }"
        )
        self._setup_ui()
        self._refresh_list()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        header = QLabel("🧠 Create & Manage Custom Analysis Rules (Adds Dynamic Columns + Winner Filters)")
        header.setStyleSheet("color: #4ade80; font-size: 14px; font-weight: 800;")
        root.addWidget(header)

        form_card = QFrame()
        form_card.setStyleSheet(
            "QFrame { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 8px; }"
        )
        form_layout = QVBoxLayout(form_card)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Rule Name (Column Header):"))
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("e.g. Right Quiz Answer, Is Genuine, Has Tag...")
        r1.addWidget(self.inp_name, 1)
        form_layout.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Rule Logic Type:"))
        self.combo_type = QComboBox()
        for _, label in self.RULE_TYPES:
            self.combo_type.addItem(label)
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        r2.addWidget(self.combo_type, 1)
        form_layout.addLayout(r2)

        r3 = QHBoxLayout()
        self.lbl_val = QLabel("Keywords / Value:")
        self.inp_val = QLineEdit()
        self.inp_val.setPlaceholderText("e.g. apple, আপেল, 4, চার")
        r3.addWidget(self.lbl_val)
        r3.addWidget(self.inp_val, 1)
        form_layout.addLayout(r3)

        r4 = QHBoxLayout()
        self.chk_enforce = QCheckBox("Require TRUE to Qualify as Winner (Uncheck for Info-Only Column)")
        self.chk_enforce.setChecked(True)
        btn_add = QPushButton("➕ Add Rule")
        btn_add.setStyleSheet(
            "background-color: #16a34a; color: white; font-weight: bold; padding: 6px 14px; border-radius: 6px;"
        )
        btn_add.clicked.connect(self.add_rule)
        r4.addWidget(self.chk_enforce)
        r4.addStretch()
        r4.addWidget(btn_add)
        form_layout.addLayout(r4)

        root.addWidget(form_card)

        root.addWidget(QLabel("Active Custom Rules:"))
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { background-color: #141923; color: #f8fafc; border: 1px solid #334155; "
            "border-radius: 6px; padding: 4px; font-size: 12px; }"
        )
        root.addWidget(self.list_widget, 1)

        bottom = QHBoxLayout()
        btn_del = QPushButton("🗑 Delete Selected Rule")
        btn_del.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold; padding: 6px 12px; border-radius: 6px;")
        btn_del.clicked.connect(self.delete_selected_rule)

        btn_clear = QPushButton("Clear All Rules")
        btn_clear.setStyleSheet("background-color: #475569; color: white; font-weight: bold; padding: 6px 12px; border-radius: 6px;")
        btn_clear.clicked.connect(self.clear_all_rules)

        btn_ok = QPushButton("✅ Apply Rules & Close")
        btn_ok.setStyleSheet("background-color: #2563eb; color: white; font-weight: 800; padding: 7px 18px; border-radius: 6px;")
        btn_ok.clicked.connect(self.accept)

        bottom.addWidget(btn_del)
        bottom.addWidget(btn_clear)
        bottom.addStretch()
        bottom.addWidget(btn_ok)
        root.addLayout(bottom)

    def _on_type_changed(self, idx: int):
        rtype = self.RULE_TYPES[idx][0]
        if rtype == "has_tags":
            self.inp_val.setEnabled(False)
            self.inp_val.setPlaceholderText("No value needed — checks for @mention or #hashtag")
        elif rtype == "length_greater":
            self.inp_val.setEnabled(True)
            self.inp_val.setPlaceholderText("Enter minimum character count, e.g. 20")
        elif rtype == "regex_match":
            self.inp_val.setEnabled(True)
            self.inp_val.setPlaceholderText(r"e.g. ^[0-9]+$ or (apple|আপেল)")
        elif rtype == "boolean_expr":
            self.inp_val.setEnabled(True)
            self.inp_val.setPlaceholderText("e.g. (apple OR আপেল) AND fresh NOT fake")
        elif rtype == "action_combo":
            self.inp_val.setEnabled(True)
            self.inp_val.setPlaceholderText("e.g. (like AND comment) OR share, comment AND NOT share")
        else:
            self.inp_val.setEnabled(True)
            self.inp_val.setPlaceholderText("e.g. apple, আপেল, 4, চার (comma-separated)")

    def add_rule(self):
        name = (self.inp_name.text() or "").strip()
        rtype = self.RULE_TYPES[self.combo_type.currentIndex()][0]
        val = (self.inp_val.text() or "").strip()
        if not name:
            QMessageBox.warning(self, "Missing Rule Name", "Please enter a column header name for this rule.")
            return
        if rtype != "has_tags" and not val:
            QMessageBox.warning(self, "Missing Rule Value", "Please enter keywords, number, or pattern for this rule.")
            return

        new_rule = CustomAnalysisRule(
            id=f"r_{uuid.uuid4().hex[:6]}",
            name=name,
            rule_type=rtype,
            value=val,
            enforce_for_qualification=self.chk_enforce.isChecked(),
        )
        self.rules.append(new_rule)
        self.inp_name.clear()
        self.inp_val.clear()
        self._refresh_list()

    def delete_selected_rule(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.rules):
            self.rules.pop(row)
            self._refresh_list()

    def clear_all_rules(self):
        self.rules.clear()
        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        for r in self.rules:
            mode_tag = "MUST PASS ✓" if r.enforce_for_qualification else "INFO COLUMN"
            item = QListWidgetItem(f"[{mode_tag}] {r.name}  —  ({r.rule_type}: {r.value or '@/# tags'})")
            self.list_widget.addItem(item)

