import logging
import os
import time
from typing import List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QLabel, QComboBox, QLineEdit, QProgressBar,
    QMessageBox, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal, QThread, QSize, QUrl
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QDesktopServices

from app.models.share_profile import ShareProfile
from app.utils.profile_sync_engine import ProfileSyncEngine, SyncCandidateRow
from app.utils.url_normalizer import normalize_url

logger = logging.getLogger(__name__)


class ProfileSyncBatchWorker(QThread):
    """
    Chunked background worker that downloads Web avatar thumbnails (in small rate-limited batches),
    computes their 64-bit perceptual dHash, and runs the 3-Layer Phone ↔ Web matcher without
    blocking the UI thread on large datasets (10,000+ rows).
    """

    progress_updated = Signal(int, int, str)  # current, total, status_text
    batch_finished = Signal(int)              # number of newly hashed/matched profiles

    def __init__(self, sync_engine: ProfileSyncEngine, profiles: List[ShareProfile], only_eligible_names: set = None):
        super().__init__()
        self.sync_engine = sync_engine
        self.profiles = profiles
        self.only_eligible_names = only_eligible_names
        self._is_running = True
        self._is_paused = False

    def run(self):
        # Identify Web profiles that have a web avatar URL (stored in share_url) but no avatar_hash yet
        candidates: List[ShareProfile] = []
        for p in self.profiles:
            if p.share_url and p.share_url.startswith("http") and not p.avatar_hash:
                if self.only_eligible_names is not None:
                    from app.utils.contest_validator import IncrementalContestAggregator
                    norm = IncrementalContestAggregator._clean_author_name(p.name or "").lower()
                    if norm not in self.only_eligible_names:
                        continue
                candidates.append(p)

        total = len(candidates)
        hashed_count = 0

        for idx, p in enumerate(candidates, start=1):
            if not self._is_running:
                break
            while self._is_paused and self._is_running:
                time.sleep(0.25)

            self.progress_updated.emit(
                idx,
                max(total, 1),
                f"Layer 2 Avatar Hashing ({idx}/{total}): {p.name}"
            )
            dhash, thumb_path = self.sync_engine.fetch_and_hash_web_avatar(p.share_url)
            if dhash:
                p.avatar_hash = dhash
                if thumb_path and not p.avatar_path:
                    p.avatar_path = thumb_path
                hashed_count += 1

            # Gentle pacing every 15 items so network/disk stays responsive
            if idx % 15 == 0:
                time.sleep(0.15)

        self.batch_finished.emit(hashed_count)

    def pause(self):
        self._is_paused = True

    def resume(self):
        self._is_paused = False

    def stop(self):
        self._is_running = False
        self._is_paused = False


class SyncProfilePanel(QWidget):
    """
    Separate, non-breaking '🔄 Sync Profile' tab for hybrid Phone + Web validation:
      1. Displays a pre-sync checklist (Avatar Picture, Name, Liked, Commented, Shared, Source).
      2. Matches Phone records (e.g. Shares/Comments with cropped Avatar pHash) against Web records
         (e.g. Likes/Comments with Profile URL + Web Avatar) across 3 validation layers.
      3. Pushes verified Profile URLs back to the main Contest Validation & Live Lottery table on demand.
    """

    sync_applied = Signal(int)  # Emits number of updated ShareProfile records

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sync_engine = ProfileSyncEngine()
        self.raw_profiles_ref: List[ShareProfile] = []
        self.rows: List[SyncCandidateRow] = []
        self.worker: ProfileSyncBatchWorker = None
        self._retired_workers: List[ProfileSyncBatchWorker] = []
        self._icon_cache = {}

        self._setup_ui()

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

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header banner explaining the Hybrid Phone + Web workflow
        banner = QLabel(
            "🔗 <b>Hybrid Phone + Web Profile Sync (Separate Validation Layer):</b> "
            "Collect Shares/Comments/Likes from Phone (gets Avatar + Name + Checklist) and Likes/Comments from Web "
            "(gets Profile URL + Avatar). Click <b>⚡ 2. Run Multi-Layer Batch Sync</b> to match exact Name + Avatar pHash "
            "in safe batches, then click <b>✅ 3. Apply Verified URLs to Main Contest List</b>."
        )
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background-color: #1e293b; color: #e2e8f0; padding: 8px 12px; "
            "border-radius: 6px; border: 1px solid #334155; font-size: 12px;"
        )
        layout.addWidget(banner)

        # Top Controls Row
        ctrl_layout = QHBoxLayout()

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All Checklist Profiles",
            "Only 3/3 Eligible Winners (Priority Sync ✅)",
            "Hybrid Matched (Phone ↔ Web Synced ✅)",
            "Needs URL or Same-Name Collision Only (⏳ / 🟡)"
        ])
        self.filter_combo.currentIndexChanged.connect(self.refresh_table_view)

        self.scope_combo = QComboBox()
        self.scope_combo.addItems([
            "Batch Scope: 3/3 Eligible & Multi-Action First (Fastest)",
            "Batch Scope: All Collected Profiles"
        ])

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by participant name...")
        self.search_input.textChanged.connect(self.refresh_table_view)

        self.btn_refresh = QPushButton("🔄 1. Refresh Checklist")
        self.btn_refresh.clicked.connect(self.rebuild_checklist)

        self.btn_run_sync = QPushButton("⚡ 2. Run Multi-Layer Batch Sync")
        self.btn_run_sync.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: bold; padding: 6px 12px;"
        )
        self.btn_run_sync.clicked.connect(self.start_batch_sync)

        self.btn_stop_sync = QPushButton("⏹ Stop Sync")
        self.btn_stop_sync.setEnabled(False)
        self.btn_stop_sync.clicked.connect(self.stop_batch_sync)

        self.btn_apply = QPushButton("✅ 3. Apply Verified URLs to Main Contest List")
        self.btn_apply.setStyleSheet(
            "background-color: #15803d; color: white; font-weight: bold; padding: 6px 12px;"
        )
        self.btn_apply.clicked.connect(self.apply_to_main_contest)

        ctrl_layout.addWidget(QLabel("View:"))
        ctrl_layout.addWidget(self.filter_combo)
        ctrl_layout.addWidget(self.scope_combo)
        ctrl_layout.addWidget(self.search_input, 1)
        ctrl_layout.addWidget(self.btn_refresh)
        ctrl_layout.addWidget(self.btn_run_sync)
        ctrl_layout.addWidget(self.btn_stop_sync)
        ctrl_layout.addWidget(self.btn_apply)
        layout.addLayout(ctrl_layout)

        # Summary + Progress Bar Row
        status_layout = QHBoxLayout()
        self.lbl_summary = QLabel("Checklist: 0 participants | Synced with URL: 0 | 3/3 Eligible: 0")
        self.lbl_summary.setStyleSheet("font-weight: bold; color: #93c5fd;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(260)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)

        status_layout.addWidget(self.lbl_summary, 1)
        status_layout.addWidget(self.progress_bar)
        layout.addLayout(status_layout)

        # Checklist Table
        self.table = QTableWidget(0, 8)
        self.table.setIconSize(QSize(36, 36))
        self.table.setHorizontalHeaderLabels([
            "Avatar & Name",
            "Reaction",
            "Comment",
            "Share",
            "Score",
            "Data Source",
            "Multi-Layer Validation Status",
            "Resolved Profile URL (Double-Click to Edit / Click to Open)"
        ])
        self.table.setStyleSheet(
            "QTableWidget { background-color: #141923; color: #f8fafc; gridline-color: #2d3748; "
            "selection-background-color: #1d4ed8; selection-color: #ffffff; font-size: 12px; }"
            "QHeaderView::section { background-color: #1e293b; color: #e2e8f0; font-weight: bold; "
            "padding: 6px; border: 1px solid #334155; }"
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._on_table_item_edited)
        self.table.itemClicked.connect(self._on_table_item_clicked)
        layout.addWidget(self.table, 1)

    def bind_profiles(self, profiles_list: List[ShareProfile]):
        """
        Binds a reference to the main `ResultsPanel.profiles` list so SyncProfilePanel
        can inspect and enrich it non-destructively.
        """
        self.raw_profiles_ref = profiles_list

    def rebuild_checklist(self):
        self.rows = self.sync_engine.build_sync_checklist(self.raw_profiles_ref)
        self.refresh_table_view()

    def _get_filtered_rows(self) -> List[SyncCandidateRow]:
        mode = self.filter_combo.currentIndex()
        query = (self.search_input.text() or "").strip().lower()
        filtered = []

        for r in self.rows:
            if query and query not in r.name.lower() and query not in (r.profile_url or "").lower():
                continue
            if mode == 1 and not r.is_eligible:
                continue
            if mode == 2 and r.sync_status not in ("VERIFIED_3_LAYER", "VERIFIED_UNIQUE_NAME", "VERIFIED_WEB_DIRECT"):
                continue
            if mode == 3 and r.sync_status not in ("PHONE_ONLY_NEEDS_URL", "NEEDS_AVATAR_DISAMBIGUATION"):
                continue
            filtered.append(r)
        return filtered

    MAX_TABLE_DISPLAY_ROWS = 1500

    def refresh_table_view(self):
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        try:
            displayed = self._get_filtered_rows()
            displayed_slice = displayed[: self.MAX_TABLE_DISPLAY_ROWS]
            self.table.setRowCount(len(displayed_slice))

            bold_font = QFont()
            bold_font.setBold(True)
            verified_bg = QBrush(QColor(6, 78, 59))          # Deep emerald (#064e3b)
            verified_fg = QBrush(QColor(240, 253, 244))      # Bright white-mint (#f0fdf4)
            verified_accent_fg = QBrush(QColor(74, 222, 128))  # Vibrant mint (#4ade80)
            warn_bg = QBrush(QColor(113, 63, 18))            # Deep amber (#713f12)
            warn_fg = QBrush(QColor(254, 249, 195))          # Crisp light gold (#fef9c3)
            normal_bg_even = QBrush(QColor(20, 25, 35))      # Dark slate (#141923)
            normal_bg_odd = QBrush(QColor(26, 33, 46))       # Slightly lighter dark slate (#1a212e)
            normal_fg = QBrush(QColor(241, 245, 249))        # Crisp white-gray (#f1f5f9)
            link_fg = QBrush(QColor(96, 165, 250))           # Bright sky blue (#60a5fa)

            for row_idx, r in enumerate(displayed_slice):

                name_item = QTableWidgetItem(r.name)
                if r.is_eligible:
                    name_item.setFont(bold_font)
                name_item.setData(Qt.UserRole, r.row_id)
                name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
                icon = self._get_cached_icon(r.avatar_path)
                if icon:
                    name_item.setIcon(icon)

                liked_item = QTableWidgetItem("✅ Reaction" if r.liked else "❌ Reaction")
                liked_item.setFlags(liked_item.flags() & ~Qt.ItemIsEditable)

                comm_item = QTableWidgetItem("✅ Comment" if r.commented else "❌ Comment")
                if r.comment_preview:
                    comm_item.setToolTip(r.comment_preview)
                comm_item.setFlags(comm_item.flags() & ~Qt.ItemIsEditable)

                share_item = QTableWidgetItem("✅ Share" if r.shared else "❌ Share")
                share_item.setFlags(share_item.flags() & ~Qt.ItemIsEditable)

                score_item = QTableWidgetItem(r.actions_score_str)
                if r.is_eligible:
                    score_item.setFont(bold_font)
                score_item.setFlags(score_item.flags() & ~Qt.ItemIsEditable)

                src_item = QTableWidgetItem(r.source_badge)
                src_item.setFlags(src_item.flags() & ~Qt.ItemIsEditable)

                status_item = QTableWidgetItem(r.status_display)
                if r.is_eligible:
                    status_item.setFont(bold_font)
                status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)

                url_item = QTableWidgetItem(r.profile_url or "")
                url_item.setData(Qt.UserRole, r.row_id)
                url_item.setToolTip("Click to open in browser, or double-click to paste/edit Profile URL.")

                cells = [
                    name_item, liked_item, comm_item, share_item,
                    score_item, src_item, status_item, url_item
                ]
                is_verified_winner = (
                    r.sync_status in ("VERIFIED_3_LAYER", "VERIFIED_UNIQUE_NAME", "VERIFIED_WEB_DIRECT")
                    and r.is_eligible
                )
                for col, cell in enumerate(cells):
                    if is_verified_winner:
                        cell.setBackground(verified_bg)
                        cell.setForeground(verified_accent_fg if col in (4, 6) else verified_fg)
                    elif r.sync_status == "NEEDS_AVATAR_DISAMBIGUATION":
                        cell.setBackground(warn_bg)
                        cell.setForeground(warn_fg)
                    else:
                        cell.setBackground(normal_bg_even if row_idx % 2 == 0 else normal_bg_odd)
                        cell.setForeground(normal_fg)

                    if col == 7 and r.profile_url:
                        cell.setForeground(link_fg)
                    self.table.setItem(row_idx, col, cell)

            total_count = len(self.rows)
            with_url = sum(1 for r in self.rows if r.profile_url)
            hybrid_synced = sum(1 for r in self.rows if r.sync_status in ("VERIFIED_3_LAYER", "VERIFIED_UNIQUE_NAME"))
            eligible_count = sum(1 for r in self.rows if r.is_eligible)
            self.lbl_summary.setText(
                f"Checklist: {total_count} unique people | "
                f"Hybrid Phone↔Web Synced: {hybrid_synced} | "
                f"With Profile URL: {with_url} | "
                f"3/3 Eligible Winners: {eligible_count}"
            )
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.blockSignals(False)

    def _on_table_item_edited(self, item: QTableWidgetItem):
        if item.column() != 7:
            return
        row_id = item.data(Qt.UserRole)
        new_url = normalize_url((item.text() or "").strip())
        for r in self.rows:
            if r.row_id == row_id:
                r.profile_url = new_url if new_url else None
                if r.profile_url:
                    r.sync_status = "VERIFIED_3_LAYER"
                    r.confidence_pct = 100
                break

    def _on_table_item_clicked(self, item: QTableWidgetItem):
        if item.column() == 7:
            txt = (item.text() or "").strip()
            if txt.startswith("http://") or txt.startswith("https://"):
                QDesktopServices.openUrl(QUrl(txt))

    def start_batch_sync(self):
        if not self.raw_profiles_ref:
            QMessageBox.information(
                self,
                "No Collected Data Yet",
                "Collect Likes, Comments, or Shares from your Phone or Browser Extension first, "
                "then run Batch Sync!"
            )
            return

        if self.worker:
            if self.worker.isRunning():
                return
            if self.worker not in self._retired_workers:
                self._retired_workers.append(self.worker)

        self.rebuild_checklist()

        only_eligible = None
        if self.scope_combo.currentIndex() == 0:
            only_eligible = {
                r.normalized_name
                for r in self.rows
                if r.is_eligible or (int(r.liked) + int(r.commented) + int(r.shared)) >= 2
            }
            if not only_eligible:
                only_eligible = None

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.btn_run_sync.setEnabled(False)
        self.btn_stop_sync.setEnabled(True)

        self.worker = ProfileSyncBatchWorker(
            self.sync_engine,
            self.raw_profiles_ref,
            only_eligible_names=only_eligible
        )
        self.worker.progress_updated.connect(self._on_worker_progress)
        self.worker.batch_finished.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_progress(self, current: int, total: int, status_text: str):
        pct = int((current / max(total, 1)) * 100)
        self.progress_bar.setValue(pct)
        self.lbl_summary.setText(status_text)

    def _on_worker_finished(self, hashed_count: int):
        self.progress_bar.setVisible(False)
        self.btn_run_sync.setEnabled(True)
        self.btn_stop_sync.setEnabled(False)
        self.rebuild_checklist()
        updated = self.sync_engine.apply_synced_urls_to_profiles(self.rows)
        if updated > 0:
            self.sync_applied.emit(updated)

    def stop_batch_sync(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()

    def apply_to_main_contest(self):
        if not self.rows:
            self.rebuild_checklist()
        updated = self.sync_engine.apply_synced_urls_to_profiles(self.rows)
        self.sync_applied.emit(updated)
        QMessageBox.information(
            self,
            "Sync Applied to Main Contest List",
            f"Successfully synced & verified Profile URLs and Avatars across { len(self.rows) } participants "
            f"({updated} raw action records enriched with URLs)!\n\n"
            f"Switch to Tab 1 ('Contest Validation & Live Lottery List') to view or print your lottery tickets."
        )
