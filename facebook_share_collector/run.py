import sys
import logging
from PySide6.QtWidgets import QApplication
from app.gui.main_window import MainWindow
from app.utils.logger import setup_logger

def main():
    setup_logger()
    logger = logging.getLogger(__name__)
    logger.info("Starting Facebook Share Collector...")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
