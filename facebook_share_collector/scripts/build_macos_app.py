import os
import sys
import stat
import shutil
import plistlib
import tempfile
import subprocess

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROJECT_DIR = os.path.join(WORKSPACE_ROOT, "facebook_share_collector")
VENV_PYTHON = os.path.realpath(os.path.join(PROJECT_DIR, ".venv", "bin", "python"))
SITE_PACKAGES_SRC = os.path.join(PROJECT_DIR, ".venv", "lib", "python3.14", "site-packages")


def _generate_app_icns(output_icns_path: str):
    """
    Renders a crisp macOS .icns icon set using PySide6 QImage/QPainter and /usr/bin/iconutil.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor, QFont, QLinearGradient, QPen
    from PySide6.QtCore import Qt, QRect

    _app = QGuiApplication.instance() or QGuiApplication([])

    base_img = QImage(1024, 1024, QImage.Format_ARGB32)
    base_img.fill(Qt.transparent)

    painter = QPainter(base_img)
    painter.setRenderHint(QPainter.Antialiasing, True)

    grad = QLinearGradient(0, 0, 1024, 1024)
    grad.setColorAt(0.0, QColor(15, 23, 42))
    grad.setColorAt(0.5, QColor(30, 58, 138))
    grad.setColorAt(1.0, QColor(6, 78, 59))

    painter.setBrush(grad)
    painter.setPen(QPen(QColor(56, 189, 248), 18))
    painter.drawRoundedRect(QRect(48, 48, 928, 928), 210, 210)

    font = QFont("Helvetica", 280, QFont.Bold)
    painter.setFont(font)
    painter.setPen(QColor(74, 222, 128))
    painter.drawText(QRect(0, 140, 1024, 460), Qt.AlignCenter, "3/3")

    sub_font = QFont("Helvetica", 120, QFont.Bold)
    painter.setFont(sub_font)
    painter.setPen(QColor(248, 250, 252))
    painter.drawText(QRect(0, 540, 1024, 260), Qt.AlignCenter, "CONTEST")
    painter.end()

    with tempfile.TemporaryDirectory() as tmpdir:
        iconset_dir = os.path.join(tmpdir, "AppIcon.iconset")
        os.makedirs(iconset_dir, exist_ok=True)
        sizes = [16, 32, 128, 256, 512]
        for sz in sizes:
            img1 = base_img.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img1.save(os.path.join(iconset_dir, f"icon_{sz}x{sz}.png"))
            img2 = base_img.scaled(sz * 2, sz * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img2.save(os.path.join(iconset_dir, f"icon_{sz}x{sz}@2x.png"))

        subprocess.run(["/usr/bin/iconutil", "-c", "icns", iconset_dir, "-o", output_icns_path], check=True)


def _compile_native_x86_64_launcher(output_bin_path: str, fallback_workspace_venv_py: str, real_python_bin: str):
    """
    Compiles a native macOS Intel (x86_64) Mach-O binary launcher for CFBundleExecutable.
    Resolves its own bundle Contents/Resources path dynamically via _NSGetExecutablePath,
    sets PYTHONPATH to the bundled site-packages & app_bundle, and execs Python on main.py.
    """
    c_code = f"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <limits.h>

int main(int argc, char *argv[]) {{
    char exe_path[PATH_MAX];
    uint32_t size = sizeof(exe_path);
    if (_NSGetExecutablePath(exe_path, &size) != 0) {{
        return 1;
    }}
    char real_exe[PATH_MAX];
    if (!realpath(exe_path, real_exe)) {{
        strncpy(real_exe, exe_path, PATH_MAX - 1);
    }}

    char macos_dir[PATH_MAX];
    strncpy(macos_dir, real_exe, PATH_MAX - 1);
    char *contents_dir = dirname(dirname(macos_dir));

    char resources_dir[PATH_MAX];
    snprintf(resources_dir, sizeof(resources_dir), "%s/Resources", contents_dir);

    char app_bundle_dir[PATH_MAX];
    snprintf(app_bundle_dir, sizeof(app_bundle_dir), "%s/app_bundle", resources_dir);

    char site_packages_dir[PATH_MAX];
    snprintf(site_packages_dir, sizeof(site_packages_dir), "%s/site-packages", resources_dir);

    char main_py[PATH_MAX];
    snprintf(main_py, sizeof(main_py), "%s/main.py", app_bundle_dir);

    char pypath[PATH_MAX * 2];
    snprintf(pypath, sizeof(pypath), "%s:%s", app_bundle_dir, site_packages_dir);
    setenv("PYTHONPATH", pypath, 1);

    const char *old_path = getenv("PATH");
    char new_path[PATH_MAX * 2];
    snprintf(
        new_path,
        sizeof(new_path),
        "%s/bin:/usr/local/bin:/opt/homebrew/bin:%s",
        app_bundle_dir,
        old_path ? old_path : "/usr/bin:/bin:/usr/sbin:/sbin"
    );
    setenv("PATH", new_path, 1);

    const char *candidates[] = {{
        "{fallback_workspace_venv_py}",
        "{real_python_bin}",
        "/usr/local/opt/python@3.14/bin/python3.14",
        "/usr/local/bin/python3.14",
        "/usr/local/bin/python3",
        "/opt/homebrew/bin/python3",
        NULL
    }};

    const char *chosen_py = NULL;
    for (int i = 0; candidates[i] != NULL; i++) {{
        if (access(candidates[i], X_OK) == 0) {{
            chosen_py = candidates[i];
            break;
        }}
    }}
    if (!chosen_py) {{
        chosen_py = "/usr/bin/python3";
    }}

    char *exec_args[] = {{ (char *)chosen_py, main_py, NULL }};
    execv(chosen_py, exec_args);
    return 1;
}}
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        c_file = os.path.join(tmpdir, "launcher.c")
        with open(c_file, "w", encoding="utf-8") as f:
            f.write(c_code)
        subprocess.run(
            ["/usr/bin/clang", "-arch", "x86_64", "-O2", c_file, "-o", output_bin_path],
            check=True,
        )
    os.chmod(output_bin_path, os.stat(output_bin_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _copytree_no_xattr(src: str, dst: str, ignore=None):
    os.makedirs(dst, exist_ok=True)
    names = os.listdir(src)
    ignored = set(ignore(src, names)) if ignore is not None else set()
    for name in names:
        if name in ignored:
            continue
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.islink(s):
            linkto = os.readlink(s)
            if os.path.lexists(d):
                os.unlink(d)
            os.symlink(linkto, d)
        elif os.path.isdir(s):
            _copytree_no_xattr(s, d, ignore=ignore)
        else:
            shutil.copyfile(s, d)
            try:
                if os.access(s, os.X_OK):
                    os.chmod(d, 0o755)
            except OSError:
                pass


def _bundle_slim_site_packages(dst_site_packages: str):
    """
    Copies only the essential runtime packages needed by Facebook Contest Validator
    (PySide6 core/gui/widgets/svg/network/dbus, shiboken6, openpyxl, et_xmlfile, appium, selenium, urllib3, certifi, idna, websocket)
    into the .app bundle so the app is self-contained without 1.1GB of unused QtWebEngine/3D frameworks.
    """
    os.makedirs(dst_site_packages, exist_ok=True)
    essential_pkgs = [
        "shiboken6",
        "openpyxl",
        "et_xmlfile",
        "appium",
        "selenium",
        "urllib3",
        "certifi",
        "idna",
        "websocket",
        "yaml",
        "_yaml",
        "trio",
        "trio_websocket",
        "wsproto",
        "h11",
        "outcome",
        "sortedcontainers",
        "sniffio",
        "attrs",
        "attr",
        "packaging",
        "socks.py",
        "typing_extensions.py",
    ]
    for item in essential_pkgs:
        src = os.path.join(SITE_PACKAGES_SRC, item)
        dst = os.path.join(dst_site_packages, item)
        if os.path.isdir(src):
            _copytree_no_xattr(
                src,
                dst,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        elif os.path.isfile(src):
            shutil.copyfile(src, dst)

    # Copy slimmed PySide6 (Core, Gui, Widgets, Network, Svg, DBus)
    pyside_src = os.path.join(SITE_PACKAGES_SRC, "PySide6")
    pyside_dst = os.path.join(dst_site_packages, "PySide6")
    os.makedirs(pyside_dst, exist_ok=True)

    for fname in (
        "__init__.py",
        "_config.py",
        "_git_pyside_version.py",
        "QtCore.abi3.so",
        "QtGui.abi3.so",
        "QtWidgets.abi3.so",
        "QtNetwork.abi3.so",
        "QtSvg.abi3.so",
        "QtDBus.abi3.so",
        "libpyside6.abi3.6.12.dylib",
        "libpyside6qml.abi3.6.12.dylib",
    ):
        s_file = os.path.join(pyside_src, fname)
        if os.path.exists(s_file):
            shutil.copyfile(s_file, os.path.join(pyside_dst, fname), follow_symlinks=False)

    # Copy required Qt frameworks
    qt_lib_src = os.path.join(pyside_src, "Qt", "lib")
    qt_lib_dst = os.path.join(pyside_dst, "Qt", "lib")
    os.makedirs(qt_lib_dst, exist_ok=True)
    for fw in (
        "QtCore.framework",
        "QtGui.framework",
        "QtWidgets.framework",
        "QtDBus.framework",
        "QtSvg.framework",
        "QtNetwork.framework",
    ):
        s_fw = os.path.join(qt_lib_src, fw)
        if os.path.isdir(s_fw):
            _copytree_no_xattr(s_fw, os.path.join(qt_lib_dst, fw))

    # Copy required Qt plugins (platforms, styles, imageformats, iconengines)
    qt_plugins_src = os.path.join(pyside_src, "Qt", "plugins")
    qt_plugins_dst = os.path.join(pyside_dst, "Qt", "plugins")
    for plug in ("platforms", "styles", "imageformats", "iconengines"):
        s_pl = os.path.join(qt_plugins_src, plug)
        if os.path.isdir(s_pl):
            _copytree_no_xattr(s_pl, os.path.join(qt_plugins_dst, plug))


def build_macos_bundle_and_dmg():
    venv_py_link = os.path.join(PROJECT_DIR, ".venv", "bin", "python")
    main_script = os.path.join(PROJECT_DIR, "main.py")

    # 1. Create double-clickable .command launcher
    cmd_path = os.path.join(WORKSPACE_ROOT, "Launch_Contest_Validator.command")
    cmd_content = f"""#!/bin/zsh
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/Library/Android/sdk/platform-tools:$PATH"
cd "{PROJECT_DIR}"
exec "{venv_py_link}" "{main_script}"
"""
    with open(cmd_path, "w", encoding="utf-8") as f:
        f.write(cmd_content)
    os.chmod(cmd_path, os.stat(cmd_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # 2. Build self-contained macOS Intel (x86_64) .app bundle
    app_bundle = os.path.join(WORKSPACE_ROOT, "Facebook Contest Validator.app")
    if os.path.exists(app_bundle):
        shutil.rmtree(app_bundle)

    contents_dir = os.path.join(app_bundle, "Contents")
    macos_dir = os.path.join(contents_dir, "MacOS")
    resources_dir = os.path.join(contents_dir, "Resources")
    app_payload_dir = os.path.join(resources_dir, "app_bundle")
    site_pkg_dir = os.path.join(resources_dir, "site-packages")

    os.makedirs(macos_dir, exist_ok=True)
    os.makedirs(app_payload_dir, exist_ok=True)

    # Generate AppIcon.icns
    icns_path = os.path.join(resources_dir, "AppIcon.icns")
    _generate_app_icns(icns_path)

    info_plist = {
        "CFBundleName": "Facebook Contest Validator",
        "CFBundleDisplayName": "Facebook Contest Validator",
        "CFBundleIdentifier": "com.contestvalidator.facebook",
        "CFBundleVersion": "2.0.0",
        "CFBundleShortVersionString": "2.0.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "FacebookContestValidator",
        "CFBundleIconFile": "AppIcon",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }
    with open(os.path.join(contents_dir, "Info.plist"), "wb") as pf:
        plistlib.dump(info_plist, pf)

    # Compile native x86_64 Mach-O launcher binary
    exec_path = os.path.join(macos_dir, "FacebookContestValidator")
    _compile_native_x86_64_launcher(exec_path, venv_py_link, VENV_PYTHON)

    # Copy application code, config, browser_extension, and seed data into app_bundle
    for root_file in ("main.py", "run.py", "config.yaml"):
        src_rf = os.path.join(PROJECT_DIR, root_file)
        if os.path.isfile(src_rf):
            shutil.copyfile(src_rf, os.path.join(app_payload_dir, root_file))
    for folder in ("app", "config", "browser_extension", "bin"):
        src_f = os.path.join(PROJECT_DIR, folder)
        if os.path.isdir(src_f):
            _copytree_no_xattr(
                src_f,
                os.path.join(app_payload_dir, folder),
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )

    # Copy SQLite DB, avatars, and auto-saved CSVs (excluding 328MB browser_profile cache)
    data_dst = os.path.join(app_payload_dir, "data")
    os.makedirs(os.path.join(data_dst, "avatars"), exist_ok=True)
    os.makedirs(os.path.join(app_payload_dir, "logs"), exist_ok=True)
    for data_file in ("facebook_shares.sqlite", "autosave.csv", "autosave_contest.csv"):
        src_df = os.path.join(PROJECT_DIR, "data", data_file)
        if os.path.isfile(src_df):
            shutil.copyfile(src_df, os.path.join(data_dst, data_file))
    avatars_src = os.path.join(PROJECT_DIR, "data", "avatars")
    if os.path.isdir(avatars_src):
        _copytree_no_xattr(avatars_src, os.path.join(data_dst, "avatars"))

    # Bundle slim site-packages
    _bundle_slim_site_packages(site_pkg_dir)

    # Ad-hoc code sign the x86_64 .app bundle for macOS Gatekeeper / LaunchServices
    subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", app_bundle], check=False)

    print(f"Created macOS Intel App Bundle: {app_bundle}")

    if "--skip-dmg" in sys.argv:
        return

    # 3. Package into macOS Intel .dmg ("Facebook_Contest_Validator_macOS_Intel.dmg")
    dmg_path = os.path.join(WORKSPACE_ROOT, "Facebook_Contest_Validator_macOS_Intel.dmg")
    with tempfile.TemporaryDirectory() as dmg_staging:
        staged_app = os.path.join(dmg_staging, "Facebook Contest Validator.app")
        shutil.copytree(app_bundle, staged_app, symlinks=True)
        os.symlink("/Applications", os.path.join(dmg_staging, "Applications"))
        shutil.copytree(
            os.path.join(PROJECT_DIR, "browser_extension"),
            os.path.join(dmg_staging, "Chrome_Browser_Extension"),
            dirs_exist_ok=True,
        )

        res = subprocess.run(
            [
                "/usr/bin/hdiutil",
                "create",
                "-volname",
                "Facebook Contest Validator",
                "-srcfolder",
                dmg_staging,
                "-ov",
                "-format",
                "UDZO",
                dmg_path,
            ],
            check=False,
        )
        if res.returncode == 0 and os.path.exists(dmg_path):
            dmg_size_mb = os.path.getsize(dmg_path) / (1024 * 1024)
            print(f"Created macOS Intel DMG ({dmg_size_mb:.1f} MB): {dmg_path}")


if __name__ == "__main__":
    build_macos_bundle_and_dmg()
