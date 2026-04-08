# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec — macOS
# ------------------------
# Produces a macOS .app bundle (and optionally a .dmg via build.py).
# Run from the repo root:
#
#   pyinstaller macos.spec
#
# Prerequisites:
#   pip install pyinstaller
#   brew install create-dmg   # optional, only needed for DMG creation
#
# Output: dist/NativePythonInstaller.app
#
# Code-signing (optional but recommended for Gatekeeper):
#   Set CODESIGN_IDENTITY below to your Developer ID certificate name, e.g.
#   "Developer ID Application: Your Name (TEAMID)"
#   Leave as None to skip signing (users will need to right-click → Open).

import sys
from pathlib import Path

ROOT   = Path(SPECPATH)
SCRIPT = ROOT / "native_python_installer_gui_v9.py"
ICON   = ROOT / "assets" / "icon.icns"      # macOS icon — optional

# Set to your Apple Developer ID string, or None to skip signing.
CODESIGN_IDENTITY = None

block_cipher = None

a = Analysis(
    [str(SCRIPT)],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "ctypes",
        "ctypes.util",
        "hashlib",
        "urllib.request",
        "urllib.error",
        "urllib.parse",
        "threading",
        "queue",
        "shutil",
        "subprocess",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy",
        "pandas",
        "matplotlib",
        "PIL",
        "setuptools",
        "email",
        "xml",
        "test",
        "unittest",
        "pydoc",
        "doctest",
        "lib2to3",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NativePythonInstaller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # UPX is unreliable on macOS — keep False
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,   # required for macOS .app bundles
    target_arch=None,      # None = current arch; use "universal2" for fat binary
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NativePythonInstaller",
)

app = BUNDLE(
    coll,
    name="NativePythonInstaller.app",
    icon=str(ICON) if ICON.exists() else None,
    bundle_identifier="com.keystoneai.native-python-installer",
    version="9.0.0",
    info_plist={
        "CFBundleName": "NativePythonInstaller",
        "CFBundleDisplayName": "Native Python Installer",
        "CFBundleVersion": "9.0.0",
        "CFBundleShortVersionString": "9.0",
        "CFBundleIdentifier": "com.keystoneai.native-python-installer",
        "NSHumanReadableCopyright": "KeystoneAI",
        "NSHighResolutionCapable": True,
        # Required for macOS 10.14+ — allows opening downloaded .pkg files
        "com.apple.security.files.downloads.read-write": True,
        # Suppress the "App is damaged" quarantine nag on unsigned builds
        "LSEnvironment": {},
        # Hide the dock icon while the tkinter window is the only UI
        "LSUIElement": False,
    },
)
