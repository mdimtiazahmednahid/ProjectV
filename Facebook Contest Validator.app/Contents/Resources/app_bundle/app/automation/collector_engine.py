import logging
import time
from PySide6.QtCore import QThread, Signal
from app.models.collection_session import CollectionSession
from app.automation.appium_manager import AppiumManager
from app.automation.facebook_detector import FacebookDetector
from app.automation.share_list_detector import ShareListDetector
from app.automation.profile_extractor import ProfileExtractor
from app.automation.scroll_controller import ScrollController
from app.automation.ui_inspector import UIInspector
from app.utils.deduplicator import Deduplicator

logger = logging.getLogger(__name__)


class CollectorEngine(QThread):
    # Signals for GUI updates
    status_updated = Signal(str)
    profile_found = Signal(object)
    stats_updated = Signal(int, int, int)  # total_profiles, total_scrolls, new_this_pass
    finished_collection = Signal()
    error_occurred = Signal(str)
    auto_save_requested = Signal()

    def __init__(self, appium_manager: AppiumManager, session: CollectionSession, config: dict, action_type: str = "share"):
        super().__init__()
        self.appium = appium_manager
        self.session = session
        self.config = config
        self.action_type = action_type

        self.is_running = False
        self.is_paused = False

        self.deduplicator = Deduplicator()

        self.fb_detector = FacebookDetector(self.config.get("facebook.package", "com.facebook.katana"))
        self.share_detector = ShareListDetector()

        min_conf = self.config.get("extraction.minimum_confidence", 0.6)
        self.extractor = ProfileExtractor(min_confidence=min_conf)

        self.auto_retry = False
        self.auto_save = False
        self.profiles_since_last_save = 0

    def run(self):
        self.is_running = True
        had_error = False
        self.status_updated.emit(f"COLLECTING ({self.action_type.upper()})")

        driver = self.appium.get_driver()
        if not driver:
            had_error = True
            self.error_occurred.emit("Phone driver not available. Click 'Connect Device' first.")
            self.stop()
            return

        scroll_controller = ScrollController(driver)

        if getattr(self, 'scroll_top_on_start', False):
            self.status_updated.emit("SCROLLING TO TOP")
            if scroll_controller.scroll_to_top(container_bounds=self.extractor.last_active_bounds):
                logger.info("Scrolled to top before collection.")
            else:
                logger.error("Failed to scroll to top.")

        max_scrolls = self.config.get("collector.max_scrolls", 500)
        max_no_new_results = self.config.get("collector.max_no_new_results", 3)

        scrolls = 0
        empty_passes = 0
        auto_retries_used = 0

        last_xml_source = ""

        try:
            while self.is_running and scrolls < max_scrolls:
                if self.is_paused:
                    self.status_updated.emit("PAUSED")
                    time.sleep(1)
                    continue

                # 1. Get Source
                xml_source = UIInspector.get_page_source(driver) or ""

                # 2. Verify Facebook foreground (uses xml_source fast-path to avoid false ADB aborts)
                if not self.fb_detector.is_facebook_foreground(driver, xml_source=xml_source):
                    had_error = True
                    self.error_occurred.emit("Facebook is not in the foreground on the connected device.")
                    self.stop()
                    break

                if not xml_source or xml_source == last_xml_source:
                    # Before counting an empty pass on Comments, check if there's a 'View more comments' button to tap
                    if self.action_type == "comment" and xml_source and hasattr(driver, "tap"):
                        tap_xy = ProfileExtractor.find_expand_comments_tap_coords(xml_source)
                        if tap_xy:
                            logger.info(f"Tapping 'View more comments' at {tap_xy}...")
                            self.status_updated.emit("EXPANDING MORE COMMENTS...")
                            driver.tap(tap_xy[0], tap_xy[1])
                            time.sleep(2.0)
                            last_xml_source = ""
                            continue

                    logger.info("Page source has not changed after scroll.")
                    empty_passes += 1
                    if empty_passes >= max_no_new_results:
                        if self.auto_retry and auto_retries_used < 1:
                            auto_retries_used += 1
                            logger.info("End of list reached, waiting 4s for lazy load (Auto-Retry 1/1)...")
                            self.status_updated.emit("WAITING 4s (LAZY LOAD)")
                            time.sleep(4)
                            empty_passes = max_no_new_results - 1
                            self.status_updated.emit(f"COLLECTING ({self.action_type.upper()})")
                        else:
                            logger.info("End of list reached (source stable).")
                            break

                # 3. Extract
                new_this_pass = 0
                if xml_source and xml_source != last_xml_source:
                    if self.action_type == "comment" and hasattr(driver, "tap"):
                        see_orig_coords = ProfileExtractor.find_see_original_tap_coords(xml_source)
                        if see_orig_coords:
                            logger.info(f"Tapping {len(see_orig_coords)} 'See original' button(s) to restore original comment text...")
                            for ox, oy in see_orig_coords[:5]:
                                try:
                                    driver.tap(ox, oy)
                                    time.sleep(0.35)
                                except Exception:
                                    pass
                            time.sleep(0.55)
                            xml_source = UIInspector.get_page_source(driver) or xml_source

                    screenshot_png = None
                    if getattr(self, "enable_avatar_fingerprint", True):
                        try:
                            if hasattr(driver, "capture_screenshot_bytes"):
                                screenshot_png = driver.capture_screenshot_bytes()
                            elif hasattr(driver, "get_screenshot_as_png"):
                                screenshot_png = driver.get_screenshot_as_png()
                        except Exception as e:
                            logger.debug(f"Screenshot capture skipped: {e}")

                    candidates = self.extractor.extract(
                        xml_source,
                        self.session.id,
                        action_type=self.action_type,
                        screenshot_png=screenshot_png,
                    )

                    detected_win = self.extractor.last_detected_window_type
                    self.status_updated.emit(
                        f"COLLECTING ({self.action_type.upper()} — +{len(candidates)} on screen #{scrolls + 1})"
                    )

                    for candidate in candidates:
                        candidate.scroll_index = scrolls
                        self.profile_found.emit(candidate)
                        self.session.total_profiles += 1
                        new_this_pass += 1

                        if self.auto_save:
                            self.profiles_since_last_save += 1
                            if self.profiles_since_last_save >= 50:
                                self.auto_save_requested.emit()
                                self.profiles_since_last_save = 0

                    if new_this_pass > 0:
                        empty_passes = 0
                        auto_retries_used = 0
                    else:
                        empty_passes += 1

                self.stats_updated.emit(self.session.total_profiles, scrolls, new_this_pass)
                if xml_source:
                    last_xml_source = xml_source

                if empty_passes >= max_no_new_results:
                    logger.info("End of list reached (no new results).")
                    break

                # 4. Scroll strictly within the active container's safe vertical bounds
                self.status_updated.emit(f"SCROLLING ({self.action_type.upper()})")
                if not scroll_controller.scroll_forward(container_bounds=self.extractor.last_active_bounds):
                    logger.error("Failed to scroll.")
                    break

                scrolls += 1
                self.session.total_scrolls = scrolls
        except Exception as e:
            had_error = True
            logger.error(f"Unexpected error in CollectorEngine: {e}", exc_info=True)
            self.error_occurred.emit(f"Collection stopped due to device error: {e}")
        finally:
            self.stop()
            if not had_error:
                self.status_updated.emit("COMPLETED")
            self.finished_collection.emit()

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def stop(self):
        self.is_running = False
        self.is_paused = False
