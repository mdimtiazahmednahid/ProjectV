import logging
from appium import webdriver
from appium.options.android import UiAutomator2Options

logger = logging.getLogger(__name__)

class AppiumManager:
    def __init__(self, host="127.0.0.1", port=4723):
        self.host = host
        self.port = port
        self.driver = None

    def connect(self, device_serial: str) -> bool:
        if self.driver:
            return True
            
        try:
            logger.info(f"Connecting to Appium at http://{self.host}:{self.port} for device {device_serial}")
            options = UiAutomator2Options()
            options.platform_name = "Android"
            options.automation_name = "UiAutomator2"
            options.udid = device_serial
            options.no_reset = True
            options.new_command_timeout = 3600
            
            self.driver = webdriver.Remote(
                command_executor=f"http://{self.host}:{self.port}",
                options=options
            )
            logger.info("Successfully connected to Appium session.")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Appium: {e}")
            self.driver = None
            return False

    def get_driver(self):
        return self.driver

    def disconnect(self):
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Appium session disconnected gracefully.")
            except Exception as e:
                logger.error(f"Error disconnecting Appium: {e}")
            self.driver = None

    def is_connected(self) -> bool:
        if not self.driver:
            return False
        try:
            # simple ping command
            self.driver.current_package
            return True
        except Exception:
            self.driver = None
            return False
