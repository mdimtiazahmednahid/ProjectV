from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                                 QPushButton, QGroupBox, QLabel, QCheckBox)
from PySide6.QtCore import Signal
import datetime

class CollectorPanel(QGroupBox):
    start_requested = Signal()
    start_action_requested = Signal(str)  # "like", "comment", or "share"
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    inspect_requested = Signal()
    paste_clipboard_requested = Signal()
    open_bookmarklet_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("Step-by-Step Contest Collector Controls", parent)
        
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        # Stats Row 1: Action & Contest Counts
        stats_layout = QHBoxLayout()
        self.lbl_status = QLabel("Status: IDLE")
        self.lbl_profiles = QLabel("Total Raw: 0")
        self.lbl_likes = QLabel("Likes 👍: 0")
        self.lbl_comments = QLabel("Comments 💬: 0")
        self.lbl_shares = QLabel("Shares 🔄: 0")
        self.lbl_eligible = QLabel("Eligible (All 3 ✅): 0")
        self.lbl_eligible.setStyleSheet("font-weight: bold; color: #4ade80;")
        self.lbl_scrolls = QLabel("Scrolls: 0")
        self.lbl_new = QLabel("New this pass: 0")
        
        for lbl in (
            self.lbl_status, self.lbl_likes, self.lbl_comments, self.lbl_shares,
            self.lbl_eligible, self.lbl_profiles, self.lbl_scrolls, self.lbl_new
        ):
            stats_layout.addWidget(lbl)
            
        # Settings
        settings_layout = QHBoxLayout()
        self.chk_auto_retry = QCheckBox("Auto-Retry on scroll stop (5s)")
        self.chk_auto_retry.setChecked(True)
        self.chk_auto_save = QCheckBox("Auto-Export CSV")
        self.chk_auto_save.setChecked(True)
        self.chk_scroll_top = QCheckBox("Scroll to top on start")
        self.chk_scroll_top.setChecked(False)
        self.chk_clipboard_sync = QCheckBox("📋 Auto-Import from Browser Extension Clipboard")
        self.chk_clipboard_sync.setChecked(True)
        self.chk_clipboard_sync.setStyleSheet("font-weight: bold; color: #60a5fa;")

        self.btn_open_bookmarklet = QPushButton("🔖 Get Browser Bookmark")
        self.btn_open_bookmarklet.setStyleSheet("background-color: #6a1b9a; color: white; font-weight: bold; padding: 4px 10px;")
        self.btn_open_bookmarklet.setToolTip("Open the 1-Click Browser Bookmarklet & Extension setup page in your browser.")
        self.btn_open_bookmarklet.clicked.connect(self.open_bookmarklet_requested.emit)

        self.btn_paste_clipboard = QPushButton("📥 Import Extension Batch")
        self.btn_paste_clipboard.setStyleSheet("background-color: #1565c0; color: white; font-weight: bold; padding: 4px 10px;")
        self.btn_paste_clipboard.setToolTip("Manually import a batch copied by the Browser Bookmarklet or Extension.")
        self.btn_paste_clipboard.clicked.connect(self.paste_clipboard_requested.emit)

        settings_layout.addWidget(self.chk_auto_retry)
        settings_layout.addWidget(self.chk_auto_save)
        settings_layout.addWidget(self.chk_scroll_top)
        settings_layout.addWidget(self.chk_clipboard_sync)
        settings_layout.addStretch()
        settings_layout.addWidget(self.btn_open_bookmarklet)
        settings_layout.addWidget(self.btn_paste_clipboard)
            
        # Step-by-Step Action Buttons + Playback Controls
        btn_layout = QHBoxLayout()
        
        self.btn_inspect = QPushButton("Inspect UI")
        self.btn_inspect.clicked.connect(self.inspect_requested.emit)
        
        self.btn_collect_likes = QPushButton("1. Collect Likes 👍")
        self.btn_collect_likes.clicked.connect(lambda: self.start_action_requested.emit("like"))
        self.btn_collect_likes.setEnabled(False)

        self.btn_collect_comments = QPushButton("2. Collect Comments 💬")
        self.btn_collect_comments.clicked.connect(lambda: self.start_action_requested.emit("comment"))
        self.btn_collect_comments.setEnabled(False)

        self.btn_collect_shares = QPushButton("3. Collect Shares 🔄")
        self.btn_collect_shares.clicked.connect(lambda: self.start_action_requested.emit("share"))
        self.btn_collect_shares.setEnabled(False)

        # Keep btn_start alias for backward compatibility
        self.btn_start = self.btn_collect_shares
        
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self.pause_requested.emit)
        self.btn_pause.setEnabled(False)
        
        self.btn_resume = QPushButton("Resume")
        self.btn_resume.clicked.connect(self.resume_requested.emit)
        self.btn_resume.setEnabled(False)
        
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        self.btn_stop.setEnabled(False)
        
        btn_layout.addWidget(self.btn_inspect)
        btn_layout.addWidget(self.btn_collect_likes)
        btn_layout.addWidget(self.btn_collect_comments)
        btn_layout.addWidget(self.btn_collect_shares)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.btn_resume)
        btn_layout.addWidget(self.btn_stop)
        
        self.layout.addLayout(stats_layout)
        self.layout.addLayout(settings_layout)
        self.layout.addLayout(btn_layout)

    def set_collection_buttons_enabled(self, enabled: bool):
        self.btn_collect_likes.setEnabled(enabled)
        self.btn_collect_comments.setEnabled(enabled)
        self.btn_collect_shares.setEnabled(enabled)

    def update_status(self, status: str):
        self.lbl_status.setText(f"Status: {status}")
        
        # State machine for buttons
        if (
            status.startswith("COLLECTING")
            or status.startswith("SCROLLING")
            or status.startswith("EXPANDING")
            or status == "WAITING 5s (LAZY LOAD)"
        ):
            self.set_collection_buttons_enabled(False)
            self.btn_pause.setEnabled(True)
            self.btn_resume.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_inspect.setEnabled(False)
        elif status == "PAUSED":
            self.set_collection_buttons_enabled(False)
            self.btn_pause.setEnabled(False)
            self.btn_resume.setEnabled(True)
            self.btn_stop.setEnabled(True)
            self.btn_inspect.setEnabled(True)
        elif status in ("COMPLETED", "IDLE"):
            self.set_collection_buttons_enabled(True)
            self.btn_pause.setEnabled(False)
            self.btn_resume.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.btn_inspect.setEnabled(True)

    def update_stats(self, total_profiles, total_scrolls, new_this_pass):
        self.lbl_profiles.setText(f"Total Raw: {total_profiles}")
        self.lbl_scrolls.setText(f"Scrolls: {total_scrolls}")
        self.lbl_new.setText(f"New this pass: {new_this_pass}")

    def update_contest_counts(self, counts: dict):
        self.lbl_likes.setText(f"Likes 👍: {counts.get('likes', 0)}")
        self.lbl_comments.setText(f"Comments 💬: {counts.get('comments', 0)}")
        self.lbl_shares.setText(f"Shares 🔄: {counts.get('shares', 0)}")
        self.lbl_eligible.setText(f"Eligible (All 3 ✅): {counts.get('eligible', 0)}")
        if counts.get("total_participants", 0) == 0:
            self.update_stats(0, 0, 0)
