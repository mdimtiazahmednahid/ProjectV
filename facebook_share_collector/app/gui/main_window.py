import logging
import os
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QSplitter, 
                               QTabWidget, QMessageBox, QApplication)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from app.gui.device_panel import DevicePanel
from app.gui.collector_panel import CollectorPanel
from app.gui.results_panel import ResultsPanel
from app.gui.sync_profile_panel import SyncProfilePanel
from app.gui.logs_panel import LogsPanel
from app.automation.appium_manager import AppiumManager
from app.automation.adb_controller import ADBManager
from app.automation.collector_engine import CollectorEngine
from app.automation.browser_dom_extractor import BrowserDOMExtractor, CLIPBOARD_BATCH_PREFIX
from app.automation.scroll_controller import ScrollController
from app.automation.ui_inspector import UIInspector
from app.models.collection_session import CollectionSession
from app.database.repository import DatabaseRepository
from app.config.settings import get_settings
from app.exporters.csv_exporter import CSVExporter

logger = logging.getLogger(__name__)

class SearchWorker(QThread):
    finished = Signal(bool, str, int) # success, message, final_scroll_index
    
    def __init__(self, driver, name, current_scroll_index=0, target_scroll_index=0):
        super().__init__()
        self.driver = driver
        self.name = name
        self.current_scroll_index = current_scroll_index
        self.target_scroll_index = target_scroll_index
        
    def run(self):
        try:
            controller = ScrollController(self.driver)
            
            diff = self.target_scroll_index - self.current_scroll_index
            
            if diff > 0:
                logger.info(f"Fast-forwarding {diff} scrolls...")
                controller.scroll_by_steps(1, diff)
            elif diff < 0:
                logger.info(f"Fast-rewinding {abs(diff)} scrolls...")
                controller.scroll_by_steps(-1, abs(diff))
            
            # The user requested a simple reversal of scrolls to save time and complexity.
            # We skip the complex text-matching search and assume we are at the target location.
            self.finished.emit(True, f"Successfully jumped to scroll index {self.target_scroll_index} for '{self.name}'.", self.target_scroll_index)
        except Exception as e:
            self.finished.emit(False, f"Error during search: {e}", self.current_scroll_index)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Facebook Contest Validator & Live Lottery Prep (Likes + Comments + Shares)")
        self.resize(1180, 780)
        
        self.settings = get_settings()
        self.appium_manager = AppiumManager(
            host=self.settings.get('appium.host', '127.0.0.1'),
            port=self.settings.get('appium.port', 4723)
        )
        self.adb_manager = ADBManager()
        self.db = DatabaseRepository()
        self.engine = None
        self.search_worker = None
        self._retired_threads = []
        self._checking_clipboard = False
        self.current_session = None
        self.current_device_scroll_index = 0
        self._db_write_buffer = []
        self._processed_clipboard_batches = set()

        self._setup_ui()
        self._setup_clipboard_bridge()

    def _retire_thread_safely(self, thread_obj):
        if not thread_obj:
            return
        if thread_obj not in self._retired_threads:
            self._retired_threads.append(thread_obj)
            thread_obj.finished.connect(
                lambda t=thread_obj: self._retired_threads.remove(t) if t in self._retired_threads else None
            )

    def _setup_clipboard_bridge(self):
        # Poll every 1.2s on the Main GUI Thread so background clipboard writes from Chrome
        # are picked up cleanly without macOS pasteboard notification re-entrancy crashes.
        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.setInterval(1200)
        self._clipboard_timer.timeout.connect(lambda: self._check_clipboard_for_extension_batch(manual=False))
        self._clipboard_timer.start()

        # Debounced full cross-sync + CSV auto-save timer for mass loads (20k+ users)
        self._deferred_sync_timer = QTimer(self)
        self._deferred_sync_timer.setSingleShot(True)
        self._deferred_sync_timer.setInterval(2500)
        self._deferred_sync_timer.timeout.connect(self._run_deferred_sync_and_autosave)

    def _run_deferred_sync_and_autosave(self):
        if not self.results_panel.profiles:
            return
        sync_rows = self.sync_profile_panel.sync_engine.build_sync_checklist(self.results_panel.profiles)
        enriched = self.sync_profile_panel.sync_engine.apply_synced_urls_to_profiles(sync_rows)
        if enriched > 0:
            self.results_panel.rebuild_from_profiles()
            self.db.save_profiles_batch(self.results_panel.profiles)
        else:
            self.results_panel.refresh_table()
        if self.tabs.currentIndex() == 1:
            self.sync_profile_panel.rebuild_checklist()
        if self.collector_panel.chk_auto_save.isChecked():
            self._do_auto_save()

    def _check_clipboard_for_extension_batch(self, manual: bool = False):
        if self._checking_clipboard:
            return
        self._checking_clipboard = True
        try:
            if not manual and not self.collector_panel.chk_clipboard_sync.isChecked():
                return

            clipboard = QApplication.clipboard()
            if not clipboard:
                return

            text = clipboard.text() or ""
            if not text.strip().startswith(CLIPBOARD_BATCH_PREFIX):
                if manual:
                    QMessageBox.information(
                        self,
                        "No Extension Batch in Clipboard",
                        "The clipboard does not currently contain an FB Contest Extension batch.\n\n"
                        "Use the Chrome/Edge Extension or Bookmarklet on facebook.com and click "
                        "'1. Auto-Scrape Likes', '2. Auto-Scrape Comments', or '3. Auto-Scrape Shares'."
                    )
                return

            session_id = self._ensure_session_id()
            parsed = BrowserDOMExtractor.parse_clipboard_batch(text, session_id=session_id)
            if not parsed:
                return

            batch_id, profiles = parsed
            if batch_id in self._processed_clipboard_batches:
                if manual:
                    QMessageBox.information(
                        self,
                        "Batch Already Imported",
                        f"Extension batch '{batch_id}' ({len(profiles)} profiles) has already been imported into this session."
                    )
                return

            self._processed_clipboard_batches.add(batch_id)
            self._db_write_buffer.extend(profiles)
            self._flush_db_buffer()
            self.results_panel.add_profiles_batch(profiles)

            total_raw = len(self.results_panel.profiles)
            if self.current_session:
                self.current_session.total_profiles = total_raw
                self.db.update_session(self.current_session)

            # For normal loads (<= 3,000 raw records) or manual click, cross-sync immediately;
            # for mass loads (20k+ users / > 3,000 raw records), debounce cross-sync + CSV write
            # so streaming 800 clipboard batches stays 60fps smooth!
            enriched = 0
            if total_raw <= 3000 or manual:
                sync_rows = self.sync_profile_panel.sync_engine.build_sync_checklist(self.results_panel.profiles)
                enriched = self.sync_profile_panel.sync_engine.apply_synced_urls_to_profiles(sync_rows)
                if enriched > 0:
                    self.results_panel.rebuild_from_profiles()
                    self.db.save_profiles_batch(self.results_panel.profiles)
                else:
                    self.results_panel.refresh_table()
                if self.tabs.currentIndex() == 1:
                    self.sync_profile_panel.rebuild_checklist()
                if self.collector_panel.chk_auto_save.isChecked():
                    self._do_auto_save()
            else:
                self._deferred_sync_timer.start()

            self.collector_panel.update_stats(total_raw, self.current_device_scroll_index, len(profiles))
            self.collector_panel.lbl_status.setText(f"Status: EXT BATCH IMPORTED (+{len(profiles)} with links)")
            logger.info(
                f"Auto-imported Browser Extension batch '{batch_id}' ({len(profiles)} profiles with links; {enriched} hybrid records synced)."
            )
            if manual:
                QMessageBox.information(
                    self,
                    "Extension Batch Imported",
                    f"Imported {len(profiles)} profiles (with canonical Facebook profile links) from clipboard!"
                )
        except Exception as e:
            logger.error(f"Clipboard batch import error: {e}", exc_info=True)
        finally:
            self._checking_clipboard = False

    def _open_bookmarklet_page(self):
        try:
            html_path = BrowserDOMExtractor.generate_bookmarklet_page()
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(html_path)))
            logger.info(f"Opened Bookmarklet setup page: {html_path}")
        except Exception as e:
            logger.error(f"Failed to generate bookmarklet page: {e}")
            QMessageBox.critical(self, "Error", f"Could not generate bookmarklet page: {e}")

    def _setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        layout = QVBoxLayout()
        main_widget.setLayout(layout)
        
        # Top controls
        self.device_panel = DevicePanel(self.appium_manager, self.adb_manager)
        self.device_panel.device_connected.connect(self._on_device_connected)
        
        self.collector_panel = CollectorPanel()
        self.collector_panel.start_requested.connect(lambda: self._start_collection("share"))
        self.collector_panel.start_action_requested.connect(self._start_collection)
        self.collector_panel.pause_requested.connect(self._pause_collection)
        self.collector_panel.resume_requested.connect(self._resume_collection)
        self.collector_panel.stop_requested.connect(self._stop_collection)
        self.collector_panel.inspect_requested.connect(self._inspect_ui)
        self.collector_panel.paste_clipboard_requested.connect(
            lambda: self._check_clipboard_for_extension_batch(manual=True)
        )
        self.collector_panel.open_bookmarklet_requested.connect(self._open_bookmarklet_page)
        
        layout.addWidget(self.device_panel)
        layout.addWidget(self.collector_panel)
        
        # Bottom split view (Results / Logs)
        splitter = QSplitter(Qt.Vertical)
        
        self.results_panel = ResultsPanel()
        self.results_panel.profile_clicked.connect(self._scroll_to_profile_on_device)
        self.results_panel.scroll_top_requested.connect(self._scroll_to_top_on_device)
        self.results_panel.load_last_session_requested.connect(self._load_latest_session)
        self.results_panel.manage_sessions_requested.connect(self._open_session_manager)
        self.results_panel.counts_changed.connect(self.collector_panel.update_contest_counts)

        self.sync_profile_panel = SyncProfilePanel()
        self.sync_profile_panel.bind_profiles(self.results_panel.profiles)
        self.sync_profile_panel.sync_applied.connect(self._on_sync_profile_applied)

        self.logs_panel = LogsPanel()
        
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabBar::tab { background: #1e293b; color: #cbd5e1; padding: 8px 16px; "
            "border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; font-weight: bold; }"
            "QTabBar::tab:selected { background: #2563eb; color: #ffffff; }"
            "QTabBar::tab:hover:!selected { background: #334155; color: #f8fafc; }"
        )
        self.tabs.addTab(self.results_panel, "🏆 Contest Validation & Live Lottery List")
        self.tabs.addTab(self.sync_profile_panel, "🔄 Sync Profile (Hybrid Phone + Web Matcher)")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.logs_panel)
        splitter.setSizes([450, 180])
        
        layout.addWidget(splitter, 1)

    def _on_tab_changed(self, index: int):
        if index == 1:
            self.sync_profile_panel.rebuild_checklist()

    def _on_sync_profile_applied(self, updated_count: int):
        self.results_panel.rebuild_from_profiles()
        if self.results_panel.profiles:
            self.db.save_profiles_batch(self.results_panel.profiles)
        if self.collector_panel.chk_auto_save.isChecked():
            self._do_auto_save()
        logger.info(f"Hybrid Sync Profile applied: enriched {updated_count} records with verified Profile URLs.")

    def _ensure_session_id(self) -> str:
        if not self.current_session:
            self.current_session = CollectionSession()
            self.db.create_session(self.current_session)
        return self.current_session.id

    def _get_active_manager(self):
        return self.device_panel.get_active_manager()

    def _on_device_connected(self, serial):
        self.collector_panel.set_collection_buttons_enabled(True)
        self.collector_panel.btn_inspect.setEnabled(True)

    def _load_latest_session(self):
        sessions = self.db.get_sessions()
        if not sessions:
            QMessageBox.information(self, "No Saved Sessions", "No previous collection sessions found in database.")
            return
        self._load_sessions_by_ids([s.id for s in sessions[:3]])

    def _open_session_manager(self):
        from app.gui.session_manager_dialog import SessionManagerDialog
        dlg = SessionManagerDialog(self.db, parent=self)
        if dlg.exec():
            if dlg.start_new_requested:
                self.results_panel.clear_results()
                self.sync_profile_panel.rebuild_checklist()
                self.current_session = CollectionSession()
                self.db.create_session(self.current_session)
                self.collector_panel.update_stats(0, 0, 0)
                self.collector_panel.lbl_status.setText("Status: NEW SESSION READY")
                logger.info(f"Started fresh contest session {self.current_session.id[:8]}.")
            elif dlg.selected_session_ids:
                self._load_sessions_by_ids(dlg.selected_session_ids)

    def _load_sessions_by_ids(self, session_ids: list):
        if not session_ids:
            return
        sessions_by_id = {s.id: s for s in self.db.get_sessions()}
        first_valid = next((sessions_by_id[sid] for sid in session_ids if sid in sessions_by_id), None)
        if first_valid:
            self.current_session = first_valid

        combined_profiles = []
        for sid in session_ids:
            s_profs = self.db.get_all_profiles_for_session(sid)
            if s_profs:
                combined_profiles.extend(s_profs)
        self.results_panel.clear_results()
        self.results_panel.add_profiles_batch(combined_profiles)
        sync_rows = self.sync_profile_panel.sync_engine.build_sync_checklist(self.results_panel.profiles)
        enriched = self.sync_profile_panel.sync_engine.apply_synced_urls_to_profiles(sync_rows)
        if enriched > 0:
            self.results_panel.rebuild_from_profiles()
        else:
            self.results_panel.refresh_table()
        self.sync_profile_panel.rebuild_checklist()
        self.collector_panel.update_stats(len(self.results_panel.profiles), self.current_device_scroll_index, 0)
        if self.collector_panel.chk_auto_save.isChecked():
            self._do_auto_save()
        logger.info(
            f"Loaded & synced {len(self.results_panel.profiles)} unique raw records ({enriched} enriched with URLs) across {len(session_ids)} session(s)."
        )

    def _inspect_ui(self):
        driver = self._get_active_manager().get_driver()
        if not driver:
            QMessageBox.warning(self, "Warning", "Device is not connected.")
            return
            
        xml_source = UIInspector.get_page_source(driver)
        if xml_source:
            xml_path, json_path = UIInspector.save_inspection(xml_source)
            logger.info(f"UI Inspection saved to {xml_path}")
            QMessageBox.information(self, "Inspection Complete", f"Saved UI hierarchy to:\n{xml_path}")
        else:
            QMessageBox.critical(self, "Error", "Failed to retrieve page source.")

    def _scroll_to_top_on_device(self):
        driver = self._get_active_manager().get_driver()
        if not driver:
            QMessageBox.warning(self, "Warning", "Device is not connected.")
            return
            
        logger.info("Attempting to scroll to top on device.")
        controller = ScrollController(driver)
        if controller.scroll_to_top():
            self.current_device_scroll_index = 0
            logger.info("Successfully scrolled to top.")
        else:
            QMessageBox.warning(self, "Scroll Failed", "Could not scroll to the top of the list.")

    def _scroll_to_profile_on_device(self, name, scroll_index=0):
        if (self.engine and self.engine.isRunning()) or (self.search_worker and self.search_worker.isRunning()):
            logger.info("Device is currently busy scrolling/collecting; skipping Find on Device request.")
            return

        driver = self._get_active_manager().get_driver()
        if not driver:
            QMessageBox.warning(self, "Warning", "Device is not connected.")
            return
            
        logger.info(f"Attempting to find {name} in the list quickly (Target Scroll: {scroll_index}).")
        self.results_panel.btn_find_device.setEnabled(False)
        self.results_panel.search_input.setEnabled(False)
        
        if self.search_worker:
            self._retire_thread_safely(self.search_worker)
        self.search_worker = SearchWorker(driver, name, self.current_device_scroll_index, scroll_index)
        self.search_worker.finished.connect(self._on_search_finished)
        self.search_worker.start()

    def _on_search_finished(self, success, message, final_scroll_index):
        self.results_panel.btn_find_device.setEnabled(True)
        self.results_panel.search_input.setEnabled(True)
        self.current_device_scroll_index = final_scroll_index
        
        if success:
            logger.info(message)
        else:
            logger.error(message)
            QMessageBox.warning(self, "Not Found", message)

    def _start_collection(self, action_type: str = "share"):
        if self.engine:
            if self.engine.isRunning():
                self.engine.stop()
                self.engine.wait(5000)
            self._retire_thread_safely(self.engine)

        if not self.current_session:
            self.current_session = CollectionSession()
            self.db.create_session(self.current_session)
        
        logger.info(f"Starting collection for action: {action_type.upper()}")
        self.engine = CollectorEngine(
            self._get_active_manager(),
            self.current_session,
            self.settings._config,
            action_type=action_type
        )
        self.engine.status_updated.connect(self.collector_panel.update_status)
        self.engine.stats_updated.connect(self.collector_panel.update_stats)
        self.engine.stats_updated.connect(self._on_collection_stats_updated)
        self.engine.profile_found.connect(self._on_profile_found)
        self.engine.finished_collection.connect(self._on_collection_finished)
        self.engine.error_occurred.connect(self._on_error)
        self.engine.auto_save_requested.connect(self._do_auto_save)
        
        # Pass auto settings
        self.engine.auto_retry = self.collector_panel.chk_auto_retry.isChecked()
        self.engine.auto_save = self.collector_panel.chk_auto_save.isChecked()
        self.engine.scroll_top_on_start = self.collector_panel.chk_scroll_top.isChecked()
        
        self.engine.start()
        
    def _pause_collection(self):
        if self.engine:
            self.engine.pause()
            
    def _resume_collection(self):
        if self.engine:
            self.engine.resume()
            
    def _stop_collection(self):
        if self.engine:
            self.engine.stop()

    def _on_collection_stats_updated(self, total_profiles, total_scrolls, new_this_pass):
        self.current_device_scroll_index = total_scrolls

    def _flush_db_buffer(self):
        if self._db_write_buffer:
            self.db.save_profiles_batch(self._db_write_buffer)
            self._db_write_buffer.clear()

    def _on_profile_found(self, profile):
        self._db_write_buffer.append(profile)
        if len(self._db_write_buffer) >= 50:
            self._flush_db_buffer()
        self.results_panel.add_profile(profile)

    def _on_collection_finished(self):
        self._flush_db_buffer()
        sync_rows = self.sync_profile_panel.sync_engine.build_sync_checklist(self.results_panel.profiles)
        enriched = self.sync_profile_panel.sync_engine.apply_synced_urls_to_profiles(sync_rows)
        if enriched > 0:
            self.results_panel.rebuild_from_profiles()
            self.db.save_profiles_batch(self.results_panel.profiles)
        else:
            self.results_panel.refresh_table()
        if self.tabs.currentIndex() == 1:
            self.sync_profile_panel.rebuild_checklist()
        if self.collector_panel.chk_auto_save.isChecked():
            self._do_auto_save()
        if self.current_session:
            import datetime
            self.current_session.end_time = datetime.datetime.now().isoformat()
            self.current_session.status = "COMPLETED"
            self.db.update_session(self.current_session)
            logger.info(f"Session {self.current_session.id} step completed. Total raw profiles: {self.current_session.total_profiles}")

    def _on_error(self, message):
        self._flush_db_buffer()
        logger.warning(f"Collection notice: {message}")
        self.collector_panel.lbl_status.setText(f"Status: STOPPED ({message[:42]})")

    def _do_auto_save(self):
        try:
            self._flush_db_buffer()
            os.makedirs("data", exist_ok=True)
            path = os.path.join("data", "autosave.csv")
            contest_path = os.path.join("data", "autosave_contest.csv")
            if CSVExporter.export(self.results_panel.profiles, path):
                logger.info(f"Auto-saved raw profiles to {path}")
            if self.results_panel.participants and CSVExporter.export_contest(self.results_panel.participants, contest_path):
                logger.info(f"Auto-saved contest validation to {contest_path}")
        except Exception as e:
            logger.error(f"Auto-save failed: {e}")
        
    def closeEvent(self, event):
        if self.engine and self.engine.isRunning():
            self.engine.stop()
            self.engine.wait()
        self._flush_db_buffer()
        self.appium_manager.disconnect()
        self.adb_manager.disconnect()
        super().closeEvent(event)
