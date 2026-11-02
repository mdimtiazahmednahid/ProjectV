from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit
from PySide6.QtCore import Qt, QObject, Signal
import logging


class _LogSignalBridge(QObject):
    log_emitted = Signal(str)


class QTextEditLogger(logging.Handler):
    """
    Thread-safe Qt log handler: worker QThreads emit log strings through a queued
    Qt Signal so `QTextEdit.append` is ALWAYS executed on the Main GUI Thread,
    preventing C++ QTextDocumentLayout / Cocoa segmentation faults.
    """
    def __init__(self, parent):
        super().__init__()
        self.widget = QTextEdit(parent)
        self.widget.setReadOnly(True)
        self.widget.document().setMaximumBlockCount(1500)
        self.widget.setStyleSheet(
            "QTextEdit { background-color: #0f172a; color: #e2e8f0; font-family: Courier, monospace; font-size: 11px; }"
        )
        self._bridge = _LogSignalBridge(parent)
        self._bridge.log_emitted.connect(self._append_safe, Qt.QueuedConnection)

    def _append_safe(self, msg: str):
        try:
            if self.widget:
                self.widget.append(msg)
        except RuntimeError:
            pass

    def emit(self, record):
        try:
            msg = self.format(record)
            self._bridge.log_emitted.emit(msg)
        except Exception:
            pass


class LogsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.log_handler = QTextEditLogger(self)

        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt="%H:%M:%S")
        self.log_handler.setFormatter(formatter)

        logging.getLogger().addHandler(self.log_handler)

        self.layout.addWidget(self.log_handler.widget)

    def append_log(self, text):
        self.log_handler._bridge.log_emitted.emit(str(text))
