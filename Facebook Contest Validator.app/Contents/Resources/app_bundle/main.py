import logging
import os
import shutil
import sys
import traceback

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

if getattr(sys, "frozen", False):
    APP_ROOT = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_RESOURCE_ROOT = getattr(sys, "_MEIPASS", APP_ROOT)
else:
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_RESOURCE_ROOT = APP_ROOT

if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)
if BUNDLE_RESOURCE_ROOT not in sys.path:
    sys.path.insert(0, BUNDLE_RESOURCE_ROOT)


def _prepare_writable_runtime_dir() -> str:
    """
    Ensures the working directory (for `data/`, `logs/`, `browser_extension/`, `config.yaml`)
    is always writable, even if the user runs the app from a read-only mounted `.dmg`
    (`/Volumes/...`) on macOS or a protected `C:\\Program Files\\...` folder on Windows.
    """
    is_read_only = (
        APP_ROOT.startswith("/Volumes/")
        or not os.access(APP_ROOT, os.W_OK)
    )
    if not is_read_only:
        os.chdir(APP_ROOT)
        return APP_ROOT

    if sys.platform == "win32":
        base_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        user_data_dir = os.path.join(base_appdata, "FacebookContestValidator")
    else:
        user_data_dir = os.path.expanduser("~/Library/Application Support/FacebookContestValidator")

    os.makedirs(os.path.join(user_data_dir, "data", "avatars"), exist_ok=True)
    os.makedirs(os.path.join(user_data_dir, "logs"), exist_ok=True)

    # Seed config.yaml and browser_extension from the bundle if not present
    for subdir in ("config", "browser_extension"):
        src_sub = os.path.join(BUNDLE_RESOURCE_ROOT, subdir)
        if not os.path.isdir(src_sub):
            src_sub = os.path.join(APP_ROOT, subdir)
        dst_sub = os.path.join(user_data_dir, subdir)
        if os.path.isdir(src_sub) and not os.path.exists(dst_sub):
            shutil.copytree(src_sub, dst_sub, dirs_exist_ok=True)

    for cfg_file in ("config.yaml",):
        src_cfg = os.path.join(BUNDLE_RESOURCE_ROOT, cfg_file)
        if not os.path.isfile(src_cfg):
            src_cfg = os.path.join(APP_ROOT, cfg_file)
        dst_cfg = os.path.join(user_data_dir, cfg_file)
        if os.path.isfile(src_cfg) and not os.path.exists(dst_cfg):
            shutil.copy2(src_cfg, dst_cfg)

    src_db = os.path.join(BUNDLE_RESOURCE_ROOT, "data", "facebook_shares.sqlite")
    if not os.path.isfile(src_db):
        src_db = os.path.join(APP_ROOT, "data", "facebook_shares.sqlite")
    dst_db = os.path.join(user_data_dir, "data", "facebook_shares.sqlite")
    if os.path.isfile(src_db) and not os.path.exists(dst_db):
        shutil.copy2(src_db, dst_db)

    src_avatars = os.path.join(BUNDLE_RESOURCE_ROOT, "data", "avatars")
    if not os.path.isdir(src_avatars):
        src_avatars = os.path.join(APP_ROOT, "data", "avatars")
    dst_avatars = os.path.join(user_data_dir, "data", "avatars")
    if os.path.isdir(src_avatars):
        for fname in os.listdir(src_avatars):
            s_file = os.path.join(src_avatars, fname)
            d_file = os.path.join(dst_avatars, fname)
            if os.path.isfile(s_file) and not os.path.exists(d_file):
                shutil.copy2(s_file, d_file)

    os.chdir(user_data_dir)
    return user_data_dir


_prepare_writable_runtime_dir()

# Ensure bundled bin, Homebrew, and Android SDK platform-tools are in PATH on macOS & Windows (x64, ARM64, x86)
if sys.platform == "win32":
    local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
    extra_paths = [
        os.path.join(APP_ROOT, "bin"),
        os.path.join(BUNDLE_RESOURCE_ROOT, "bin"),
        os.path.join(local_app_data, "Android", "Sdk", "platform-tools"),
        r"C:\Android\platform-tools",
        r"C:\platform-tools",
    ]
else:
    extra_paths = [
        os.path.join(APP_ROOT, "bin"),
        os.path.join(BUNDLE_RESOURCE_ROOT, "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
        os.path.expanduser("~/Library/Android/sdk/platform-tools"),
    ]
current_path = os.environ.get("PATH", "")
for p in extra_paths:
    if os.path.isdir(p) and p not in current_path:
        current_path = f"{p}{os.pathsep}{current_path}"
os.environ["PATH"] = current_path

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication
from app.gui.main_window import MainWindow
from app.utils.logger import setup_logger


def _install_global_exception_guard(logger: logging.Logger):
    def _handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error(f"Unhandled exception caught by global guard:\n{tb_str}")

    sys.excepthook = _handle_exception


def main():
    setup_logger()
    logger = logging.getLogger(__name__)
    _install_global_exception_guard(logger)
    logger.info("Starting Sentra — Public Data Intelligence & Contest Validator...")

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "com.sentra.intelligence"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Sentra")
    app.setApplicationDisplayName("Sentra")
    app.setStyle("Fusion")

    # Set native system font to avoid Qt "Sans Serif" font family lookup overhead
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))
    elif sys.platform == "darwin":
        app.setFont(QFont("Helvetica Neue", 12))

    icon_loaded = False
    icon_candidates = [
        os.path.join(BUNDLE_RESOURCE_ROOT, "app", "resources", "AppIcon.png"),
        os.path.join(APP_ROOT, "app", "resources", "AppIcon.png"),
        os.path.join(BUNDLE_RESOURCE_ROOT, "app", "resources", "AppIcon.ico"),
        os.path.join(APP_ROOT, "app", "resources", "AppIcon.ico"),
    ]
    for icon_path in icon_candidates:
        if os.path.isfile(icon_path):
            app_icon = QIcon(icon_path)
            app.setWindowIcon(app_icon)
            icon_loaded = True
            break

    if not icon_loaded:
        try:
            from PySide6.QtGui import QPixmap
            from app.utils.sentra_brand import render_sentra_logo_qimage
            app.setWindowIcon(QIcon(QPixmap.fromImage(render_sentra_logo_qimage(256, with_badge_bg=True))))
        except Exception:
            pass

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
