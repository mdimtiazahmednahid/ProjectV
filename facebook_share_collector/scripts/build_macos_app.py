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
    Renders a crisp macOS .icns icon set of the Sentra orbital signal logo
    using PySide6 QImage/QPainter and /usr/bin/iconutil.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if PROJECT_DIR not in sys.path:
        sys.path.insert(0, PROJECT_DIR)
    from PySide6.QtCore import Qt
    from app.utils.sentra_brand import render_sentra_logo_qimage

    base_img = render_sentra_logo_qimage(size=1024, with_badge_bg=True)

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

    # 2. Build or update self-contained macOS Intel (x86_64) .app bundle
    app_bundle = os.path.join(WORKSPACE_ROOT, "Facebook Contest Validator.app")
    sentra_app_bundle = os.path.join(WORKSPACE_ROOT, "Sentra.app")
    existing_payload = os.path.join(app_bundle, "Contents", "Resources", "app_bundle")
    existing_bin = os.path.join(app_bundle, "Contents", "MacOS", "FacebookContestValidator")

    # Sync any newer live data from existing .app bundles back to PROJECT_DIR/data first
    for cand_bundle in (sentra_app_bundle, app_bundle):
        cand_data = os.path.join(cand_bundle, "Contents", "Resources", "app_bundle", "data")
        if os.path.isdir(cand_data):
            os.makedirs(os.path.join(PROJECT_DIR, "data", "avatars"), exist_ok=True)
            for item in os.listdir(cand_data):
                s_path = os.path.join(cand_data, item)
                d_path = os.path.join(PROJECT_DIR, "data", item)
                if os.path.isfile(s_path):
                    if not os.path.exists(d_path) or os.path.getmtime(s_path) >= os.path.getmtime(d_path):
                        shutil.copyfile(s_path, d_path)
            cand_avatars = os.path.join(cand_data, "avatars")
            if os.path.isdir(cand_avatars):
                for av_file in os.listdir(cand_avatars):
                    s_av = os.path.join(cand_avatars, av_file)
                    d_av = os.path.join(PROJECT_DIR, "data", "avatars", av_file)
                    if os.path.isfile(s_av) and not os.path.exists(d_av):
                        shutil.copyfile(s_av, d_av)

    existing_app_data = os.path.join(existing_payload, "data")

    # Fast in-place code sync when .app bundle already exists (preserves live CWD inode for running app!)
    if "--skip-dmg" in sys.argv and os.path.isdir(existing_payload) and os.path.isfile(existing_bin):
        try:
            icns_in_place = os.path.join(app_bundle, "Contents", "Resources", "AppIcon.icns")
            _generate_app_icns(icns_in_place)
            plist_in_place = os.path.join(app_bundle, "Contents", "Info.plist")
            if os.path.isfile(plist_in_place):
                with open(plist_in_place, "rb") as pf:
                    pl_data = plistlib.load(pf)
                pl_data["CFBundleName"] = "Sentra"
                pl_data["CFBundleDisplayName"] = "Sentra"
                with open(plist_in_place, "wb") as pf:
                    plistlib.dump(pl_data, pf)
            for root_file in ("main.py", "run.py", "config.yaml"):
                src_rf = os.path.join(PROJECT_DIR, root_file)
                if os.path.isfile(src_rf):
                    shutil.copyfile(src_rf, os.path.join(existing_payload, root_file))
            for folder in ("app", "config", "browser_extension", "bin"):
                src_f = os.path.join(PROJECT_DIR, folder)
                if os.path.isdir(src_f):
                    _copytree_no_xattr(
                        src_f,
                        os.path.join(existing_payload, folder),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
            os.makedirs(existing_app_data, exist_ok=True)
            if os.path.isdir(os.path.join(PROJECT_DIR, "data")):
                for item in os.listdir(os.path.join(PROJECT_DIR, "data")):
                    src_df = os.path.join(PROJECT_DIR, "data", item)
                    if os.path.isfile(src_df) and item.endswith((".sqlite", ".csv", ".html", ".json", ".xlsx")):
                        shutil.copyfile(src_df, os.path.join(existing_app_data, item))

            # Also maintain Sentra.app bundle in workspace root
            if not os.path.exists(sentra_app_bundle):
                _copytree_no_xattr(app_bundle, sentra_app_bundle)
            else:
                sentra_payload = os.path.join(sentra_app_bundle, "Contents", "Resources", "app_bundle")
                if os.path.isdir(sentra_payload):
                    shutil.copyfile(icns_in_place, os.path.join(sentra_app_bundle, "Contents", "Resources", "AppIcon.icns"))
                    shutil.copyfile(plist_in_place, os.path.join(sentra_app_bundle, "Contents", "Info.plist"))
                    for root_file in ("main.py", "run.py", "config.yaml"):
                        src_rf = os.path.join(PROJECT_DIR, root_file)
                        if os.path.isfile(src_rf):
                            shutil.copyfile(src_rf, os.path.join(sentra_payload, root_file))
                    for folder in ("app", "config", "browser_extension", "bin"):
                        src_f = os.path.join(PROJECT_DIR, folder)
                        if os.path.isdir(src_f):
                            _copytree_no_xattr(
                                src_f,
                                os.path.join(sentra_payload, folder),
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                            )
                    sentra_data = os.path.join(sentra_payload, "data")
                    os.makedirs(sentra_data, exist_ok=True)
                    if os.path.isdir(os.path.join(PROJECT_DIR, "data")):
                        for item in os.listdir(os.path.join(PROJECT_DIR, "data")):
                            src_df = os.path.join(PROJECT_DIR, "data", item)
                            if os.path.isfile(src_df) and item.endswith((".sqlite", ".csv", ".html", ".json", ".xlsx")):
                                shutil.copyfile(src_df, os.path.join(sentra_data, item))
            # Re-sign both .app bundles so macOS Gatekeeper / LaunchServices validates Info.plist & Resources
            for bundle_to_sign in (app_bundle, sentra_app_bundle):
                subprocess.run(
                    ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", bundle_to_sign],
                    check=False,
                )
            print(f"Updated & re-signed Sentra macOS App Bundles in-place: {sentra_app_bundle} & {app_bundle}")
            return
        except OSError:
            pass

    staging_bundle = os.path.join(WORKSPACE_ROOT, "_Facebook_Contest_Validator_stage")
    if os.path.exists(staging_bundle):
        shutil.rmtree(staging_bundle, ignore_errors=True)

    contents_dir = os.path.join(staging_bundle, "Contents")
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
        "CFBundleName": "Sentra",
        "CFBundleDisplayName": "Sentra",
        "CFBundleIdentifier": "com.sentra.intelligence",
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

    # Copy SQLite DB, avatars, and auto-saved CSVs (preserving any newer live data inside existing .app bundle)
    existing_app_data = os.path.join(app_bundle, "Contents", "Resources", "app_bundle", "data")
    if os.path.isdir(existing_app_data):
        os.makedirs(os.path.join(PROJECT_DIR, "data", "avatars"), exist_ok=True)
        for item in os.listdir(existing_app_data):
            s_path = os.path.join(existing_app_data, item)
            d_path = os.path.join(PROJECT_DIR, "data", item)
            if os.path.isfile(s_path):
                if not os.path.exists(d_path) or os.path.getmtime(s_path) >= os.path.getmtime(d_path):
                    shutil.copyfile(s_path, d_path)
        existing_avatars = os.path.join(existing_app_data, "avatars")
        if os.path.isdir(existing_avatars):
            for av_file in os.listdir(existing_avatars):
                s_av = os.path.join(existing_avatars, av_file)
                d_av = os.path.join(PROJECT_DIR, "data", "avatars", av_file)
                if os.path.isfile(s_av) and not os.path.exists(d_av):
                    shutil.copyfile(s_av, d_av)

    data_dst = os.path.join(app_payload_dir, "data")
    os.makedirs(os.path.join(data_dst, "avatars"), exist_ok=True)
    os.makedirs(os.path.join(app_payload_dir, "logs"), exist_ok=True)
    if os.path.isdir(os.path.join(PROJECT_DIR, "data")):
        for item in os.listdir(os.path.join(PROJECT_DIR, "data")):
            src_df = os.path.join(PROJECT_DIR, "data", item)
            if os.path.isfile(src_df) and item.endswith((".sqlite", ".csv", ".html", ".json", ".xlsx")):
                shutil.copyfile(src_df, os.path.join(data_dst, item))
    avatars_src = os.path.join(PROJECT_DIR, "data", "avatars")
    if os.path.isdir(avatars_src):
        _copytree_no_xattr(avatars_src, os.path.join(data_dst, "avatars"))

    # Bundle slim site-packages
    _bundle_slim_site_packages(site_pkg_dir)

    if os.path.exists(app_bundle):
        try:
            shutil.rmtree(app_bundle)
        except OSError:
            old_trash = os.path.join(WORKSPACE_ROOT, "_old_app_bundle")
            shutil.rmtree(old_trash, ignore_errors=True)
            os.rename(app_bundle, old_trash)
            shutil.rmtree(old_trash, ignore_errors=True)
    os.rename(staging_bundle, app_bundle)

    # Also sync Sentra.app in full rebuild path so both .app bundles are always identical
    if not os.path.exists(sentra_app_bundle):
        _copytree_no_xattr(app_bundle, sentra_app_bundle)
    else:
        _copytree_no_xattr(app_bundle, sentra_app_bundle)

    # Ad-hoc code sign both x86_64 .app bundles for macOS Gatekeeper / LaunchServices
    for bundle_to_sign in (app_bundle, sentra_app_bundle):
        subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", bundle_to_sign], check=False)

    print(f"Created macOS Intel App Bundles: {sentra_app_bundle} & {app_bundle}")

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
