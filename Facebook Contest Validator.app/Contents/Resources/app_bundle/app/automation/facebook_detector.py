import logging

logger = logging.getLogger(__name__)

class FacebookDetector:
    def __init__(self, expected_package="com.facebook.katana"):
        self.expected_package = expected_package
        
    def is_facebook_foreground(self, driver, xml_source: str = "") -> bool:
        if not driver:
            return False

        # Fast-path: if XML dump already contains a Facebook package attribute, Facebook is on screen
        if xml_source and (
            f'package="{self.expected_package}"' in xml_source
            or 'package="com.facebook.' in xml_source
        ):
            return True
            
        try:
            current_pkg = driver.current_package or ""
            if current_pkg == self.expected_package:
                return True
                
            # Allow fallback for basic facebook app etc if configured
            if "facebook" in current_pkg.lower():
                logger.warning(f"Foreground is {current_pkg}, which contains 'facebook' but is not exactly {self.expected_package}")
                return True

            # If current_package is empty (e.g. Android 13-15 modal window transition) and xml_source is non-empty, allow pass
            if not current_pkg and xml_source and "<hierarchy" in xml_source:
                return True
                
            logger.info(f"Current foreground app is {current_pkg}, expecting {self.expected_package}")
            return False
        except Exception as e:
            logger.error(f"Failed to detect foreground app: {e}")
            return bool(xml_source and "com.facebook" in xml_source)

    def get_current_activity(self, driver) -> str:
        if not driver:
            return ""
        try:
            return driver.current_activity
        except Exception:
            return ""
