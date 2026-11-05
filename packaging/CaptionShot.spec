# PyInstaller spec for CaptionShot (one-folder build: starts fast, fewer antivirus false alarms
# than one-file). Build:  pyinstaller --noconfirm --clean packaging/CaptionShot.spec
# Windows gives dist/CaptionShot/CaptionShot.exe; macOS also gives dist/CaptionShot.app.
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

with open(os.path.join(ROOT, "captionshot.py"), encoding="utf-8") as _f:
    VERSION = re.search(r'^APP_VERSION = "([^"]+)"', _f.read(), re.M).group(1)

a = Analysis(
    [os.path.join(ROOT, "captionshot.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "fonts"), "fonts")],          # Mukta (Hindi) + its OFL licence
    hiddenimports=["PySide6.QtSvg", "PySide6.QtNetwork"],     # imported at top level; listed to be safe
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf",
              "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CaptionShot",
    console=False,                                            # tray app: no console window
    icon=os.path.join(SPECPATH, "captionshot.ico") if IS_WIN else None,
    version=os.path.join(SPECPATH, "version_info.txt") if IS_WIN else None,
    upx=False,                                                # UPX triggers antivirus false alarms
)
coll = COLLECT(exe, a.binaries, a.datas, name="CaptionShot", upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="CaptionShot.app",
        icon=os.path.join(SPECPATH, "captionshot.icns"),
        bundle_identifier="com.captionshot.app",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "CaptionShot",
            "CFBundleShortVersionString": VERSION,
            "LSUIElement": True,                              # menu bar app: no Dock icon
            "NSHighResolutionCapable": True,
            "NSScreenCaptureUsageDescription": "CaptionShot captures your screen to make screenshots.",
        },
    )
