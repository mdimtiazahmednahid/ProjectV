import os
import secrets
from typing import List
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from app.models.share_profile import ContestParticipant


class LiveLotteryDialog(QDialog):
    """
    Interactive '🎡 Live Spin Draw (3/3 Eligible Winners)' Stage Window for Facebook Live Draws.
    Uses `secrets.SystemRandom()` cryptographic randomness with a smooth roulette spin animation,
    displays the Winner Spotlight Card (Serial #, Avatar, Name, Comment, and Profile URL),
    and tracks drawn winners so hosts can draw multiple prizes without repeats.
    """

    def __init__(self, eligible_participants: List[ContestParticipant], parent=None):
        super().__init__(parent)
        self.eligible = list(eligible_participants)
        self.remaining = list(eligible_participants)
        self.drawn_winners: List[ContestParticipant] = []
        self._rng = secrets.SystemRandom()
        self._spin_ticks_left = 0
        self._current_winner: ContestParticipant = None

        self.setWindowTitle(f"🎡 Live Contest Lottery Draw — {len(self.eligible)} Eligible (3/3) Winners")
        self.resize(820, 540)
        self.setStyleSheet(
            "QDialog { background-color: #0b1120; color: #f8fafc; }"
            "QLabel { color: #f8fafc; }"
        )

        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._on_spin_tick)

        self._setup_ui()

    def _setup_ui(self):
        root_layout = QHBoxLayout(self)

        # Left column: Spotlight Stage
        stage_layout = QVBoxLayout()

        title_lbl = QLabel(f"🏆 LIVE CONTEST WINNER DRAW ({len(self.eligible)} ELIGIBLE 3/3)")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(
            "background: #1e293b; color: #38bdf8; font-size: 16px; font-weight: 800; "
            "padding: 10px; border-radius: 8px; border: 1px solid #334155;"
        )
        stage_layout.addWidget(title_lbl)

        self.card = QFrame()
        self.card.setStyleSheet(
            "QFrame { background-color: #064e3b; border: 3px solid #10b981; border-radius: 14px; padding: 18px; }"
        )
        card_layout = QVBoxLayout(self.card)
        card_layout.setAlignment(Qt.AlignCenter)

        self.lbl_serial = QLabel("READY TO SPIN")
        self.lbl_serial.setAlignment(Qt.AlignCenter)
        self.lbl_serial.setStyleSheet("color: #4ade80; font-size: 28px; font-weight: 900; border: none;")
        card_layout.addWidget(self.lbl_serial)

        self.lbl_avatar = QLabel()
        self.lbl_avatar.setFixedSize(96, 96)
        self.lbl_avatar.setAlignment(Qt.AlignCenter)
        self.lbl_avatar.setStyleSheet(
            "background-color: #0f172a; border: 2px solid #34d399; border-radius: 48px;"
        )
        card_layout.addWidget(self.lbl_avatar, 0, Qt.AlignCenter)

        self.lbl_name = QLabel("Click '🎰 Draw Random Winner' Below!")
        self.lbl_name.setAlignment(Qt.AlignCenter)
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setStyleSheet("color: #ffffff; font-size: 24px; font-weight: 800; border: none; margin-top: 6px;")
        card_layout.addWidget(self.lbl_name)

        self.lbl_comment = QLabel("All participants in this pool completed Like 👍 + Comment 💬 + Share 🔄")
        self.lbl_comment.setAlignment(Qt.AlignCenter)
        self.lbl_comment.setWordWrap(True)
        self.lbl_comment.setStyleSheet("color: #d1fae5; font-size: 13px; border: none; margin-top: 4px;")
        card_layout.addWidget(self.lbl_comment)

        self.btn_open_profile = QPushButton("🌐 Open Winner's Facebook Profile")
        self.btn_open_profile.setVisible(False)
        self.btn_open_profile.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: bold; font-size: 13px; "
            "padding: 8px 16px; border-radius: 6px; margin-top: 8px;"
        )
        self.btn_open_profile.clicked.connect(self._open_winner_url)
        card_layout.addWidget(self.btn_open_profile, 0, Qt.AlignCenter)

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
        hist_lbl = QLabel("🏅 Drawn Winners Log")
        hist_lbl.setStyleSheet("color: #fbbf24; font-weight: 800; font-size: 14px;")
        right_layout.addWidget(hist_lbl)

        self.winners_list = QListWidget()
        self.winners_list.setStyleSheet(
            "QListWidget { background-color: #141923; color: #f8fafc; border: 1px solid #334155; "
            "border-radius: 8px; font-size: 13px; padding: 6px; }"
        )
        self.winners_list.itemDoubleClicked.connect(self._on_history_item_double_clicked)
        right_layout.addWidget(self.winners_list, 1)

        root_layout.addLayout(right_layout, 2)

    def _display_participant_on_stage(self, p: ContestParticipant, final: bool = False):
        self.lbl_serial.setText(f"{'🎉 WINNER ' if final else ''}{p.serial_code}")
        self.lbl_name.setText(p.display_name)
        notes = p.combined_notes or "Liked 👍 · Commented 💬 · Shared 🔄"
        self.lbl_comment.setText(notes[:140])

        if p.avatar_path and os.path.isfile(p.avatar_path):
            pix = QPixmap(p.avatar_path)
            if not pix.isNull():
                self.lbl_avatar.setPixmap(pix.scaled(90, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.lbl_avatar.setText("👤")
        else:
            self.lbl_avatar.setPixmap(QPixmap())
            self.lbl_avatar.setText("👤")

        if final and p.profile_url:
            self.btn_open_profile.setVisible(True)
            self.btn_open_profile.setToolTip(p.profile_url)
        else:
            self.btn_open_profile.setVisible(False)

    def start_spin(self):
        if not self.remaining:
            self.lbl_serial.setText("ALL DRAWN!")
            self.lbl_name.setText("All eligible winners have been drawn. Click '🔄 Reset Pool' to draw again.")
            return

        self.btn_spin.setEnabled(False)
        self.btn_open_profile.setVisible(False)
        self._spin_ticks_left = 22
        self._spin_timer.start(65)

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
            winner = self._rng.choice(self.remaining)
            self.remaining.remove(winner)
            self.drawn_winners.append(winner)
            self._current_winner = winner
            self._display_participant_on_stage(winner, final=True)

            prize_num = len(self.drawn_winners)
            item = QListWidgetItem(f"Prize #{prize_num}: {winner.serial_code} — {winner.display_name}")
            item.setData(Qt.UserRole, winner.profile_url or "")
            self.winners_list.addItem(item)
            self.btn_spin.setEnabled(True)

    def reset_pool(self):
        self._spin_timer.stop()
        self.remaining = list(self.eligible)
        self.drawn_winners.clear()
        self.winners_list.clear()
        self.lbl_serial.setText("READY TO SPIN")
        self.lbl_name.setText("Pool Reset — Click '🎰 Draw Random Winner'!")
        self.lbl_comment.setText(f"{len(self.remaining)} eligible (3/3) winners in pool.")
        self.btn_open_profile.setVisible(False)
        self.btn_spin.setEnabled(True)

    def _open_winner_url(self):
        if self._current_winner and self._current_winner.profile_url:
            QDesktopServices.openUrl(QUrl(self._current_winner.profile_url))

    def _on_history_item_double_clicked(self, item: QListWidgetItem):
        url = item.data(Qt.UserRole)
        if url and (url.startswith("http://") or url.startswith("https://")):
            QDesktopServices.openUrl(QUrl(url))

