import logging
import os
import sys


def setup_logger():
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "app.log")

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%H:%M:%S")

    # File handler (always UTF-8)
    fh = logging.FileHandler(log_file, encoding="utf-8", errors="replace")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler (safe under Windows pythonw.exe where sys.stdout may be None or cp1252)
    if sys.stdout is not None and hasattr(sys.stdout, "write"):
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
