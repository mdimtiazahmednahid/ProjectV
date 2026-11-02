import logging
import random
import time
from typing import Optional, Tuple
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction

logger = logging.getLogger(__name__)


class ScrollController:
    def __init__(self, driver):
        self.driver = driver

    def _compute_safe_vertical_zone(
        self,
        container_bounds: Optional[Tuple[int, int, int, int]] = None
    ) -> Tuple[int, int, int]:
        """
        Returns `(center_x, bottom_safe_y, top_safe_y)` strictly inside the active list container's bounds
        so swipes NEVER touch the Android bottom-sheet top drag handle (which would pull down/close the popup)
        and NEVER swipe too far in a single pass.
        """
        window_size = self.driver.get_window_size()
        screen_w = window_size["width"]
        screen_h = window_size["height"]

        if container_bounds:
            x, y, w, h = container_bounds
            if w >= 200 and h >= 280:
                center_x = x + int(w * 0.5) + random.randint(-14, 14)
                # Stay safely inside 32%..68% of the active container (36% overlap-safe human step)
                bottom_safe_y = y + int(h * 0.68) + random.randint(-12, 12)
                top_safe_y = y + int(h * 0.32) + random.randint(-12, 12)
                bottom_safe_y = max(y + 60, min(screen_h - 80, bottom_safe_y))
                top_safe_y = max(y + 60, min(bottom_safe_y - 120, top_safe_y))
                return center_x, bottom_safe_y, top_safe_y

        center_x = int(screen_w * 0.5) + random.randint(-14, 14)
        # Default safe middle zone (70% -> 35% of screen height = 35% human step)
        bottom_safe_y = int(screen_h * 0.70) + random.randint(-15, 15)
        top_safe_y = int(screen_h * 0.35) + random.randint(-15, 15)
        return center_x, bottom_safe_y, top_safe_y

    def scroll_forward(
        self,
        container_bounds: Optional[Tuple[int, int, int, int]] = None
    ) -> bool:
        if not self.driver:
            return False

        try:
            center_x, start_y, end_y = self._compute_safe_vertical_zone(container_bounds)
            self._do_w3c_swipe(center_x, start_y, center_x, end_y, duration_ms=random.randint(720, 880))
            time.sleep(random.uniform(1.6, 2.2))
            return True
        except Exception as e:
            logger.error(f"Failed to perform scroll_forward: {e}")
            return False

    def scroll_backward(
        self,
        container_bounds: Optional[Tuple[int, int, int, int]] = None
    ) -> bool:
        if not self.driver:
            return False

        try:
            center_x, bottom_y, top_y = self._compute_safe_vertical_zone(container_bounds)
            # Start safely below the bottom-sheet header handle so it scrolls list content up without closing sheet
            safe_start_y = top_y + int((bottom_y - top_y) * 0.25)
            self._do_w3c_swipe(center_x, safe_start_y, center_x, bottom_y, duration_ms=random.randint(700, 850))
            time.sleep(random.uniform(1.4, 1.9))
            return True
        except Exception as e:
            logger.error(f"Failed to perform scroll_backward: {e}")
            return False

    def scroll_by_steps(
        self,
        direction: int,
        steps: int,
        container_bounds: Optional[Tuple[int, int, int, int]] = None
    ) -> bool:
        if not self.driver or steps <= 0:
            return False

        try:
            center_x, bottom_y, top_y = self._compute_safe_vertical_zone(container_bounds)
            if direction == 1:
                start_y, end_y = bottom_y, top_y
            else:
                start_y, end_y = top_y + int((bottom_y - top_y) * 0.25), bottom_y

            if getattr(self.driver, "is_direct_adb", False):
                for _ in range(steps):
                    self.driver.swipe(center_x, start_y, center_x, end_y, duration_ms=650)
                    time.sleep(0.35)
                time.sleep(1.0)
                return True

            CHUNK_SIZE = 50
            remaining = steps

            while remaining > 0:
                current_steps = min(remaining, CHUNK_SIZE)
                remaining -= current_steps

                actions = ActionChains(self.driver)
                pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
                actions.w3c_actions = ActionBuilder(self.driver, mouse=pointer)

                for _ in range(current_steps):
                    actions.w3c_actions.pointer_action.move_to_location(center_x, start_y)
                    actions.w3c_actions.pointer_action.pointer_down()
                    actions.w3c_actions.pointer_action.pause(0.08)
                    actions.w3c_actions.pointer_action.move_to_location(center_x, end_y)
                    actions.w3c_actions.pointer_action.pause(0.35)
                    actions.w3c_actions.pointer_action.pointer_up()
                    actions.w3c_actions.pointer_action.pause(0.15)

                actions.perform()

                if remaining > 0:
                    time.sleep(0.5)

            time.sleep(1.0)
            return True
        except Exception as e:
            logger.error(f"Failed to perform batch scroll_by_steps: {e}")
            return False

    def scroll_to_top(
        self,
        container_bounds: Optional[Tuple[int, int, int, int]] = None
    ) -> bool:
        if not self.driver:
            return False

        try:
            center_x, bottom_y, top_y = self._compute_safe_vertical_zone(container_bounds)
            safe_start_y = top_y + int((bottom_y - top_y) * 0.25)

            last_source = ""
            for _ in range(30):
                self._do_w3c_swipe(center_x, safe_start_y, center_x, bottom_y, duration_ms=700)
                time.sleep(1.5)
                source = self.driver.page_source
                if source == last_source:
                    break
                last_source = source

            return True
        except Exception as e:
            logger.error(f"Failed to scroll to top: {e}")
            return False

    def scroll_to_text(self, text: str, max_scrolls: int = 50) -> bool:
        if not self.driver:
            return False

        from appium.webdriver.common.appiumby import AppiumBy
        import re

        try:
            center_x, start_y, end_y = self._compute_safe_vertical_zone()
            safe_name = re.escape(text)

            last_source = ""
            for _ in range(max_scrolls):
                if getattr(self.driver, "is_direct_adb", False):
                    source = self.driver.page_source or ""
                    if text.lower() in source.lower():
                        return True
                else:
                    try:
                        el = self.driver.find_element(
                            AppiumBy.ANDROID_UIAUTOMATOR,
                            f'new UiSelector().textMatches("(?i).*{safe_name}.*")'
                        )
                        if el and el.is_displayed():
                            return True
                    except Exception:
                        pass

                    try:
                        el = self.driver.find_element(
                            AppiumBy.ANDROID_UIAUTOMATOR,
                            f'new UiSelector().descriptionMatches("(?i).*{safe_name}.*")'
                        )
                        if el and el.is_displayed():
                            return True
                    except Exception:
                        pass
                    source = self.driver.page_source or ""

                if source == last_source:
                    break
                last_source = source

                self._do_w3c_swipe(center_x, start_y, center_x, end_y, duration_ms=750)
                time.sleep(1.4)

            return False
        except Exception as e:
            logger.error(f"Failed to scroll to text '{text}': {e}")
            return False

    def _do_w3c_swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 750):
        if getattr(self.driver, "is_direct_adb", False):
            self.driver.swipe(start_x, start_y, end_x, end_y, duration_ms=duration_ms)
            return

        actions = ActionChains(self.driver)
        pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
        actions.w3c_actions = ActionBuilder(self.driver, mouse=pointer)

        actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
        actions.w3c_actions.pointer_action.pointer_down()
        actions.w3c_actions.pointer_action.pause(0.12)
        actions.w3c_actions.pointer_action.move_to_location(end_x, end_y)
        actions.w3c_actions.pointer_action.pause(0.45)  # Kill fling/inertia so scroll distance is exact
        actions.w3c_actions.pointer_action.pointer_up()
        actions.perform()
