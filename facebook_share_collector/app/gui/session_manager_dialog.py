from typing import List
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QFont
from app.database.repository import DatabaseRepository


class SessionManagerDialog(QDialog):
    """
    Production Session Manager & Multi-Session Merger Dialog.
    Lets the user inspect all saved SQLite sessions (with Likes, Comments, Shares, and URL counts),
    select any combination of Phone + Web sessions to merge and cross-sync, or start a fresh session.
    """

    def __init__(self, db: DatabaseRepository, parent=None):
        super().__init__(parent)
        self.db = db
        self.selected_session_ids: List[str] = []
        self.start_new_requested: bool = False

        self.setWindowTitle("📂 Sentra — Session Manager & Multi-Session Merger")
        self.resize(860, 520)
        self.setStyleSheet(
            "QDialog { background-color: #0f172a; color: #f8fafc; }"
            "QLabel { color: #e2e8f0; }"
        )

        self._setup_ui()
        self._populate_sessions()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(
            "<b>📂 Sentra — Manage & Merge Saved Sessions</b> — "
            "Check one or more sessions below (e.g. a Phone Shares session + a Web Reactions/Comments session) "
            "and click <b>Load & Sync Selected Sessions</b>."
        )
        header.setWordWrap(True)
        header.setStyleSheet(
            "background: #1e293b; border: 1px solid #334155; padding: 10px; border-radius: 6px; font-size: 12px;"
        )
        layout.addWidget(header)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Select", "Session ID", "Started At", "Reactions 👍", "Comments 💬", "Shares 🔄", "With URL 🔗", "Total Raw"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #0f172a; color: #f1f5f9; gridline-color: #334155; font-size: 12px; }"
            "QHeaderView::section { background-color: #1e293b; color: #38bdf8; font-weight: bold; padding: 6px; border: 1px solid #334155; }"
        )
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()

        self.btn_select_top3 = QPushButton("☑️ Select Top 3 Recent")
        self.btn_select_top3.setStyleSheet(
            "background-color: #334155; color: #f8fafc; font-weight: bold; padding: 7px 12px; border-radius: 5px;"
        )
        self.btn_select_top3.clicked.connect(self._select_top_3)

        self.btn_new_session = QPushButton("🆕 Start Fresh Empty Session")
        self.btn_new_session.setStyleSheet(
            "background-color: #0284c7; color: white; font-weight: bold; padding: 7px 14px; border-radius: 5px;"
        )
        self.btn_new_session.clicked.connect(self._on_start_fresh)

        self.btn_delete = QPushButton("🗑 Delete Checked")
        self.btn_delete.setStyleSheet(
            "background-color: #991b1b; color: white; font-weight: bold; padding: 7px 12px; border-radius: 5px;"
        )
        self.btn_delete.clicked.connect(self._on_delete_checked)

        self.btn_load = QPushButton("✅ Load & Sync Selected Sessions")
        self.btn_load.setStyleSheet(
            "background-color: #16a34a; color: white; font-weight: bold; padding: 8px 18px; border-radius: 5px;"
        )
        self.btn_load.clicked.connect(self._on_load_selected)

        btn_row.addWidget(self.btn_select_top3)
        btn_row.addWidget(self.btn_new_session)
        btn_row.addWidget(self.btn_delete)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_load)
        layout.addLayout(btn_row)

    def _populate_sessions(self):
        sessions = self.db.get_sessions()
        summaries = self.db.get_session_action_summaries()
        # Filter out empty sessions with 0 records unless it's the only one
        non_empty = [s for s in sessions if summaries.get(s.id, {}).get("total", 0) > 0]
        display_sessions = non_empty if non_empty else sessions

        self.table.setRowCount(len(display_sessions))
        bg_even = QBrush(QColor(20, 25, 35))
        bg_odd = QBrush(QColor(26, 33, 46))
        fg = QBrush(QColor(241, 245, 249))
        bold_font = QFont()
        bold_font.setBold(True)

        for idx, s in enumerate(display_sessions):
            stats = summaries.get(s.id, {"like": 0, "comment": 0, "share": 0, "total": s.total_profiles or 0, "urls": 0})
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk_item.setCheckState(Qt.Checked if idx < 3 else Qt.Unchecked)
            chk_item.setData(Qt.UserRole, s.id)

            sid_item = QTableWidgetItem(s.id[:8])
            sid_item.setFont(bold_font)
            start_str = (s.start_time or "").split(".")[0].replace("T", " ")
            time_item = QTableWidgetItem(start_str)
            like_item = QTableWidgetItem(str(stats["like"]))
            comm_item = QTableWidgetItem(str(stats["comment"]))
            share_item = QTableWidgetItem(str(stats["share"]))
            url_item = QTableWidgetItem(str(stats["urls"]))
            total_item = QTableWidgetItem(str(stats["total"]))
            total_item.setFont(bold_font)

            row_cells = [chk_item, sid_item, time_item, like_item, comm_item, share_item, url_item, total_item]
            row_bg = bg_even if idx % 2 == 0 else bg_odd
            for col, cell in enumerate(row_cells):
                cell.setBackground(row_bg)
                cell.setForeground(fg)
                self.table.setItem(idx, col, cell)

    def _get_checked_session_ids(self) -> List[str]:
        checked = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                sid = item.data(Qt.UserRole)
                if sid:
                    checked.append(sid)
        return checked

    def _select_top_3(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked if row < 3 else Qt.Unchecked)

    def _on_start_fresh(self):
        self.start_new_requested = True
        self.selected_session_ids = []
        self.accept()

    def _on_delete_checked(self):
        checked = self._get_checked_session_ids()
        if not checked:
            QMessageBox.information(self, "No Sessions Checked", "Check one or more sessions to delete.")
            return
        ans = QMessageBox.question(
            self,
            "Confirm Session Deletion",
            f"Are you sure you want to permanently delete {len(checked)} selected session(s) from the database?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self.db.delete_sessions(checked)
            self._populate_sessions()

    def _on_load_selected(self):
        checked = self._get_checked_session_ids()
        if not checked:
            QMessageBox.information(self, "No Sessions Checked", "Please check at least one session to load.")
            return
        self.selected_session_ids = checked
        self.start_new_requested = False
        self.accept()

