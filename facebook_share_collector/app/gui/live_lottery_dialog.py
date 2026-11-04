import os
import secrets
from typing import Callable, List, Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QSpinBox, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from app.models.share_profile import ContestParticipant


class LiveLotteryDialog(QDialog):
    """
    Interactive '🎡 Live Spin Draw (Qualified Winners)' Stage Window for Facebook Live Draws,
    incorporating FairDraw / DrawSystem (`draw.blade.php` & `winner_card.blade.php`) features:
      - Cryptographic randomness (`secrets.SystemRandom()`)
      - Multi-Winner Draw selector (Draw 1 to 10 winners at once) & Configurable Spin Duration
      - Pre-Draw Eligibility Summary Banner (Total Pool, Active Action & Keyword Rules)
      - '🚫 Disqualify & Re-spin' button (removes disqualified winner and immediately spins a replacement)
      - '📸 Save Winner Card PNG' button (exports the Cyber Winner Spotlight Card as a high-res PNG image)
    """

    def __init__(
        self,
        eligible_participants: List[ContestParticipant],
        parent=None,
        rule_summary_text: str = "Like 👍 AND Comment 💬 AND Share 🔄 (3/3)",
        on_disqualify_callback: Optional[Callable[[ContestParticipant], None]] = None,
    ):
        super().__init__(parent)
        self.eligible = list(eligible_participants)
        self.remaining = list(eligible_participants)
        self.drawn_winners: List[ContestParticipant] = []
        self._last_batch_winners: List[ContestParticipant] = []
        self._rng = secrets.SystemRandom()
        self._spin_ticks_left = 0
        self._target_winners_count = 1
        self._current_winner: Optional[ContestParticipant] = None
        self.rule_summary_text = rule_summary_text
        self.on_disqualify_callback = on_disqualify_callback

        self.setWindowTitle(f"🎡 FairDraw Live Contest Lottery — {len(self.eligible)} Qualified Winners")
        self.resize(920, 600)
        self.setStyleSheet(
            "QDialog { background-color: #0b1120; color: #f8fafc; }"
            "QLabel { color: #f8fafc; }"
        )

        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._on_spin_tick)

        self._setup_ui()

    def _setup_ui(self):
        root_layout = QHBoxLayout(self)
        root_layout.setSpacing(14)

        # Left column: Spotlight Stage
        stage_layout = QVBoxLayout()
        stage_layout.setSpacing(8)

        title_lbl = QLabel(f"🏆 LIVE CONTEST WINNER DRAW ({len(self.eligible)} QUALIFIED IN POOL)")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(
            "background: #1e293b; color: #38bdf8; font-size: 16px; font-weight: 800; "
            "padding: 10px; border-radius: 8px; border: 1px solid #334155;"
        )
        stage_layout.addWidget(title_lbl)

        self.lbl_rules_banner = QLabel(f"🎯 Active Rule: {self.rule_summary_text}")
        self.lbl_rules_banner.setAlignment(Qt.AlignCenter)
        self.lbl_rules_banner.setWordWrap(True)
        self.lbl_rules_banner.setStyleSheet(
            "background: #0f172a; color: #a7f3d0; font-size: 12px; font-weight: bold; "
            "padding: 6px 10px; border-radius: 6px; border: 1px solid #059669;"
        )
        stage_layout.addWidget(self.lbl_rules_banner)

        # Draw Settings Bar (Number of Winners + Spin Duration from DrawSystem)
        cfg_bar = QHBoxLayout()
        lbl_num = QLabel("Winners per Spin:")
        lbl_num.setStyleSheet("color: #cbd5e1; font-size: 12px; font-weight: bold;")
        self.spin_num_winners = QSpinBox()
        self.spin_num_winners.setRange(1, 10)
        self.spin_num_winners.setValue(1)
        self.spin_num_winners.setStyleSheet(
            "background: #1e293b; color: #ffffff; border: 1px solid #475569; border-radius: 5px; padding: 4px 8px; font-weight: bold;"
        )

        lbl_dur = QLabel("Spin Duration (sec):")
        lbl_dur.setStyleSheet("color: #cbd5e1; font-size: 12px; font-weight: bold;")
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(1, 30)
        self.spin_duration.setValue(3)
        self.spin_duration.setStyleSheet(
            "background: #1e293b; color: #ffffff; border: 1px solid #475569; border-radius: 5px; padding: 4px 8px; font-weight: bold;"
        )

        self.lbl_pool_status = QLabel(f"Remaining Pool: {len(self.remaining)}")
        self.lbl_pool_status.setStyleSheet("color: #fbbf24; font-size: 12px; font-weight: 800;")

        cfg_bar.addWidget(lbl_num)
        cfg_bar.addWidget(self.spin_num_winners)
        cfg_bar.addSpacing(10)
        cfg_bar.addWidget(lbl_dur)
        cfg_bar.addWidget(self.spin_duration)
        cfg_bar.addStretch()
        cfg_bar.addWidget(self.lbl_pool_status)
        stage_layout.addLayout(cfg_bar)

        # Cyber Winner Card (Captured when exporting PNG)
        self.card = QFrame()
        self.card.setStyleSheet(
            "QFrame { background-color: #064e3b; border: 3px solid #10b981; border-radius: 16px; padding: 18px; }"
        )
        card_layout = QVBoxLayout(self.card)
        card_layout.setAlignment(Qt.AlignCenter)

        self.lbl_serial = QLabel("READY TO SPIN")
        self.lbl_serial.setAlignment(Qt.AlignCenter)
        self.lbl_serial.setStyleSheet("color: #4ade80; font-size: 28px; font-weight: 900; border: none;")
        card_layout.addWidget(self.lbl_serial)

        self.lbl_avatar = QLabel("👤")
        self.lbl_avatar.setFixedSize(96, 96)
        self.lbl_avatar.setAlignment(Qt.AlignCenter)
        self.lbl_avatar.setStyleSheet(
            "background-color: #0f172a; border: 2px solid #34d399; border-radius: 48px; font-size: 36px;"
        )
        card_layout.addWidget(self.lbl_avatar, 0, Qt.AlignCenter)

        self.lbl_name = QLabel("Click '🎰 Draw Random Winner' Below!")
        self.lbl_name.setAlignment(Qt.AlignCenter)
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setStyleSheet("color: #ffffff; font-size: 24px; font-weight: 800; border: none; margin-top: 6px;")
        card_layout.addWidget(self.lbl_name)

        self.lbl_actions_done = QLabel("👍 Like · 💬 Comment · 🔄 Share")
        self.lbl_actions_done.setAlignment(Qt.AlignCenter)
        self.lbl_actions_done.setStyleSheet("color: #fde047; font-size: 12px; font-weight: bold; border: none;")
        card_layout.addWidget(self.lbl_actions_done)

        self.lbl_comment = QLabel("All participants in this pool passed your active contest rules.")
        self.lbl_comment.setAlignment(Qt.AlignCenter)
        self.lbl_comment.setWordWrap(True)
        self.lbl_comment.setStyleSheet("color: #d1fae5; font-size: 13px; border: none; margin-top: 4px;")
        card_layout.addWidget(self.lbl_comment)

        # Winner Action Buttons inside Spotlight Card
        winner_btn_row = QHBoxLayout()
        self.btn_open_profile = QPushButton("🌐 Open Winner Profile")
        self.btn_open_profile.setVisible(False)
        self.btn_open_profile.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: bold; font-size: 12px; "
            "padding: 7px 14px; border-radius: 6px;"
        )
        self.btn_open_profile.clicked.connect(self._open_winner_url)

        self.btn_save_card = QPushButton("📸 Save Winner Card (PNG)")
        self.btn_save_card.setVisible(False)
        self.btn_save_card.setStyleSheet(
            "background-color: #0d9488; color: white; font-weight: bold; font-size: 12px; "
            "padding: 7px 14px; border-radius: 6px;"
        )
        self.btn_save_card.clicked.connect(self.save_winner_card_png)

        self.btn_dq_respin = QPushButton("🚫 Disqualify & Re-spin")
        self.btn_dq_respin.setVisible(False)
        self.btn_dq_respin.setStyleSheet(
            "background-color: #dc2626; color: white; font-weight: bold; font-size: 12px; "
            "padding: 7px 14px; border-radius: 6px;"
        )
        self.btn_dq_respin.clicked.connect(self.disqualify_and_respin)

        winner_btn_row.addStretch()
        winner_btn_row.addWidget(self.btn_open_profile)
        winner_btn_row.addWidget(self.btn_save_card)
        winner_btn_row.addWidget(self.btn_dq_respin)
        winner_btn_row.addStretch()
        card_layout.addLayout(winner_btn_row)

        stage_layout.addWidget(self.card, 1)

        btn_bar = QHBoxLayout()
        self.btn_spin = QPushButton("🎰 Draw Random Winner (Cryptographic Fair Spin)")
        self.btn_spin.setStyleSheet(
            "background-color: #16a34a; color: white; font-size: 15px; font-weight: 800; "
            "padding: 12px 20px; border-radius: 8px;"
        )
        self.btn_spin.clicked.connect(self.start_spin)

        self.btn_reset = QPushButton("🔄 Reset Pool")
        self.btn_reset.setStyleSheet(
            "background-color: #334155; color: #e2e8f0; font-weight: bold; padding: 12px 14px; border-radius: 8px;"
        )
        self.btn_reset.clicked.connect(self.reset_pool)

        btn_bar.addWidget(self.btn_spin, 1)
        btn_bar.addWidget(self.btn_reset)
        stage_layout.addLayout(btn_bar)

        root_layout.addLayout(stage_layout, 3)

        # Right column: Drawn Winners History
        right_layout = QVBoxLayout()
        hist_lbl = QLabel("🏅 Drawn Winners Log (Double-click to open profile)")
        hist_lbl.setStyleSheet("color: #fbbf24; font-weight: 800; font-size: 13px;")
        right_layout.addWidget(hist_lbl)

        self.winners_list = QListWidget()
        self.winners_list.setStyleSheet(
            "QListWidget { background-color: #141923; color: #f8fafc; border: 1px solid #334155; "
            "border-radius: 8px; font-size: 13px; padding: 6px; }"
        )
        self.winners_list.itemClicked.connect(self._on_history_item_clicked)
        self.winners_list.itemDoubleClicked.connect(self._on_history_item_double_clicked)
        right_layout.addWidget(self.winners_list, 1)

        self.btn_export_winners = QPushButton("💾 Export Drawn Winners (CSV)")
        self.btn_export_winners.setStyleSheet(
            "background-color: #1e293b; color: #38bdf8; font-weight: bold; font-size: 12px; "
            "padding: 8px 12px; border-radius: 6px; border: 1px solid #0284c7;"
        )
        self.btn_export_winners.clicked.connect(self.export_drawn_winners_csv)
        right_layout.addWidget(self.btn_export_winners)

        root_layout.addLayout(right_layout, 2)

    def _format_actions_badge(self, p: ContestParticipant) -> str:
        parts = []
        parts.append("👍 Liked ✓" if p.liked else "👍 Like ✗")
        parts.append(f"💬 Commented ({len(p.comment_texts)}) ✓" if p.commented else "💬 Comment ✗")
        parts.append("🔄 Shared ✓" if p.shared else "🔄 Share ✗")
        return "  ·  ".join(parts)

    def _display_participant_on_stage(self, p: ContestParticipant, final: bool = False, extra_winners: Optional[List[ContestParticipant]] = None):
        if final and extra_winners and len(extra_winners) > 1:
            serials = ", ".join(w.serial_code for w in extra_winners)
            names = " | ".join(w.display_name for w in extra_winners)
            self.lbl_serial.setText(f"🎉 {len(extra_winners)} WINNERS: {serials}")
            self.lbl_name.setText(names)
        else:
            self.lbl_serial.setText(f"{'🎉 WINNER ' if final else ''}{p.serial_code}")
            self.lbl_name.setText(p.display_name)

        self.lbl_actions_done.setText(self._format_actions_badge(p))
        notes = p.combined_notes or "Verified Contest Participant"
        self.lbl_comment.setText(notes[:160])

        if p.avatar_path and os.path.isfile(p.avatar_path):
            pix = QPixmap(p.avatar_path)
            if not pix.isNull():
                self.lbl_avatar.setPixmap(pix.scaled(90, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.lbl_avatar.setText("👤")
        else:
            self.lbl_avatar.setPixmap(QPixmap())
            self.lbl_avatar.setText("👤")

        if final:
            self.btn_save_card.setVisible(True)
            self.btn_dq_respin.setVisible(True)
            if p.profile_url:
                self.btn_open_profile.setVisible(True)
                self.btn_open_profile.setToolTip(p.profile_url)
            else:
                self.btn_open_profile.setVisible(False)
        else:
            self.btn_open_profile.setVisible(False)
            self.btn_save_card.setVisible(False)
            self.btn_dq_respin.setVisible(False)

    def start_spin(self):
        if not self.remaining:
            self.lbl_serial.setText("ALL DRAWN!")
            self.lbl_name.setText("All qualified winners have been drawn. Click '🔄 Reset Pool' to draw again.")
            return

        self._target_winners_count = min(self.spin_num_winners.value(), len(self.remaining))
        duration_sec = max(1, self.spin_duration.value())
        interval_ms = 65
        self._spin_ticks_left = max(12, int((duration_sec * 1000) / interval_ms))

        self.btn_spin.setEnabled(False)
        self.btn_open_profile.setVisible(False)
        self.btn_save_card.setVisible(False)
        self.btn_dq_respin.setVisible(False)
        self._spin_timer.start(interval_ms)

    def _on_spin_tick(self):
        if not self.remaining:
            self._spin_timer.stop()
            self.btn_spin.setEnabled(True)
            return

        candidate = self._rng.choice(self.remaining)
        self._spin_ticks_left -= 1

        if self._spin_ticks_left > 0:
            self._display_participant_on_stage(candidate, final=False)
        else:
            self._spin_timer.stop()
            count_to_draw = min(self._target_winners_count, len(self.remaining))
            # Cryptographic selection without replacement (DrawSystem WinnerSelectionService / Fisher-Yates)
            batch_winners = self._rng.sample(self.remaining, count_to_draw)
            self._last_batch_winners = batch_winners
            for w in batch_winners:
                self.remaining.remove(w)
                self.drawn_winners.append(w)
                prize_num = len(self.drawn_winners)
                comment_snip = f' — "{w.comment_texts[0][:35]}"' if w.comment_texts else ""
                item = QListWidgetItem(f"🏆 Prize #{prize_num}: {w.serial_code} — {w.display_name}{comment_snip}")
                item.setData(Qt.UserRole, w.profile_url or "")
                item.setData(Qt.UserRole + 1, w.normalized_key)
                self.winners_list.addItem(item)

            self._current_winner = batch_winners[0]
            self._display_participant_on_stage(batch_winners[0], final=True, extra_winners=batch_winners)
            self.lbl_pool_status.setText(f"Remaining Pool: {len(self.remaining)}")
            self.btn_spin.setEnabled(True)

    def disqualify_and_respin(self):
        """
        Matches DrawSystem's '🚫 Disqualify & Re-spin' (`draw.blade.php` lines 1299-1350):
        Marks the current winner as disqualified, removes them from the winners log,
        and immediately spins a replacement winner!
        """
        if not self._current_winner:
            return
        dq_winner = self._current_winner
        if self.on_disqualify_callback:
            self.on_disqualify_callback(dq_winner)
        if dq_winner in self.drawn_winners:
            self.drawn_winners.remove(dq_winner)
        if dq_winner in self.eligible:
            self.eligible.remove(dq_winner)
        if dq_winner in self.remaining:
            self.remaining.remove(dq_winner)

        # Remove from QListWidget and re-number remaining prizes
        self._refresh_winners_list_widget()

        self.lbl_pool_status.setText(f"Remaining Pool: {len(self.remaining)}")
        self._current_winner = None
        if self.remaining:
            self.spin_num_winners.setValue(1)
            self.start_spin()
        else:
            self.lbl_serial.setText("NO REMAINING POOL")
            self.lbl_name.setText(f"Disqualified {dq_winner.display_name}. No more candidates in pool.")
            self.btn_dq_respin.setVisible(False)
            self.btn_save_card.setVisible(False)
            self.btn_open_profile.setVisible(False)

    def _refresh_winners_list_widget(self):
        self.winners_list.clear()
        for prize_num, w in enumerate(self.drawn_winners, 1):
            comment_snip = f' — "{w.comment_texts[0][:35]}"' if w.comment_texts else ""
            item = QListWidgetItem(f"🏆 Prize #{prize_num}: {w.serial_code} — {w.display_name}{comment_snip}")
            item.setData(Qt.UserRole, w.profile_url or "")
            item.setData(Qt.UserRole + 1, w.normalized_key)
            self.winners_list.addItem(item)

    def export_drawn_winners_csv(self):
        if not self.drawn_winners:
            QMessageBox.information(self, "No Winners Drawn Yet", "Spin to draw at least one winner before exporting.")
            return
        from app.exporters.csv_exporter import CSVExporter
        os.makedirs("data", exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Drawn Winners (CSV)",
            os.path.join("data", "drawn_winners.csv"),
            "CSV Files (*.csv)"
        )
        if path:
            if CSVExporter.export_contest(self.drawn_winners, path):
                QMessageBox.information(self, "Winners Exported", f"Exported {len(self.drawn_winners)} drawn winner(s) to:\n{path}")
            else:
                QMessageBox.critical(self, "Export Error", "Could not export drawn winners CSV.")

    def save_winner_card_png(self):
        """
        Matches DrawSystem's Winner Card PNG Download (`winner_card.blade.php` lines 85-120):
        Renders the spotlight winner card directly to a crisp PNG file (hiding UI buttons during capture).
        """
        if not self._current_winner:
            return
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in self._current_winner.name).strip("_") or "winner"
        default_name = f"winner_{self._current_winner.serial_code.lstrip('#')}_{safe_name}.png"
        os.makedirs("data", exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Winner Card Image (PNG)",
            os.path.join("data", default_name),
            "PNG Image (*.png)"
        )
        if path:
            was_open_vis = self.btn_open_profile.isVisible()
            was_save_vis = self.btn_save_card.isVisible()
            was_dq_vis = self.btn_dq_respin.isVisible()
            self.btn_open_profile.setVisible(False)
            self.btn_save_card.setVisible(False)
            self.btn_dq_respin.setVisible(False)
            try:
                pixmap = self.card.grab()
            finally:
                self.btn_open_profile.setVisible(was_open_vis)
                self.btn_save_card.setVisible(was_save_vis)
                self.btn_dq_respin.setVisible(was_dq_vis)
            if pixmap.save(path, "PNG"):
                QMessageBox.information(self, "Winner Card Saved", f"Saved official Winner Card PNG to:\n{path}")
            else:
                QMessageBox.critical(self, "Error", "Could not save Winner Card PNG.")

    def reset_pool(self):
        self._spin_timer.stop()
        self.remaining = list(self.eligible)
        self.drawn_winners.clear()
        self._last_batch_winners.clear()
        self.winners_list.clear()
        self.lbl_serial.setText("READY TO SPIN")
        self.lbl_name.setText("Pool Reset — Click '🎰 Draw Random Winner'!")
        self.lbl_comment.setText(f"{len(self.remaining)} qualified winners in pool.")
        self.lbl_pool_status.setText(f"Remaining Pool: {len(self.remaining)}")
        self.btn_open_profile.setVisible(False)
        self.btn_save_card.setVisible(False)
        self.btn_dq_respin.setVisible(False)
        self.btn_spin.setEnabled(True)

    def _open_winner_url(self):
        if self._current_winner and self._current_winner.profile_url:
            QDesktopServices.openUrl(QUrl(self._current_winner.profile_url))

    def _on_history_item_clicked(self, item: QListWidgetItem):
        norm_key = item.data(Qt.UserRole + 1)
        if not norm_key:
            return
        found = next((w for w in self.drawn_winners if w.normalized_key == norm_key), None)
        if found:
            self._current_winner = found
            self._display_participant_on_stage(found, final=True)

    def _on_history_item_double_clicked(self, item: QListWidgetItem):
        url = item.data(Qt.UserRole)
        if url and (url.startswith("http://") or url.startswith("https://")):
            QDesktopServices.openUrl(QUrl(url))
