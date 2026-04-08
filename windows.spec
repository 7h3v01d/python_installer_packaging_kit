# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec — Windows
# --------------------------
# Produces a single-file .exe that includes the tkinter runtime.
# Run from the repo root:
#
#   pyinstaller windows.spec
#
# Prerequisites:
#   pip install pyinstaller
#
# The output lands in dist\NativePythonInstaller\NativePythonInstaller.exe

import sys
from pathlib import Path

ROOT = Path(SPECPATH)          # directory containing this .spec
SCRIPT = ROOT / "native_python_installer_gui_v9.py"
ICON   = ROOT / "assets" / "icon.ico"   # optional — remove icon= line if missing

block_cipher = None

a = Analysis(
    [str(SCRIPT)],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        # tkinter sub-modules that PyInstaller sometimes misses
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        # standard library modules used at runtime
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
        # Keep the bundle lean — none of these are used
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="NativePythonInstaller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,              # set to False if UPX is not installed
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # no console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,      # None = same arch as build machine
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    # Request highest available execution level.
    # The installer itself will request UAC elevation when needed;
    # this launcher does NOT need to run elevated.
    uac_admin=False,
    version="version_info.txt" if (ROOT / "version_info.txt").exists() else None,
)
