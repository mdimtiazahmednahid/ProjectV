import logging
import os
import sys

project_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "facebook_share_collector")
if os.path.isdir(project_dir):
    os.chdir(project_dir)
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

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
