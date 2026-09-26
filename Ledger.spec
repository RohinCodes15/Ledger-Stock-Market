# -*- mode: python ; coding: utf-8 -*-
import sys
# Build with ./build_app.sh (Mac) or: pyinstaller Ledger.spec (Windows)
import os
import re

VERSION = re.search(r'^VERSION = "([^"]+)"', open("ledger_game.py", encoding="utf-8").read(), re.M).group(1)
BUNDLE_ID = "com.rohinpidathala.ledger"

# Google sign-in needs its OAuth client file inside the app. Without it the app still works,
# but the Google buttons report that sign-in isn't set up.
datas = [("google_config.json", ".")] if os.path.exists("google_config.json") else []

a = Analysis(
    ['ledger_game.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["ledger_safety", "google_auth"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Ledger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=os.environ.get("LEDGER_SIGN_ID") or None,
    entitlements_file=None,
    icon="assets/icon.png",
    version=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Ledger',
)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name='Ledger.app',
        icon="assets/icon.png",
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.educational-games",
            "NSHumanReadableCopyright": "Ledger. Pretend money for learning.",
        },
    )
