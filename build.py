#!/usr/bin/env python3
"""
build.py — KeystoneAI Native Python Installer packaging script
==============================================================
Run this from the project root (same folder as the .spec files):

    python build.py              # auto-detects platform
    python build.py --platform windows
    python build.py --platform macos
    python build.py --dmg        # macOS: also wrap the .app in a .dmg

What this does
--------------
1. Checks prerequisites (PyInstaller, Tcl/Tk, create-dmg on macOS).
2. Cleans stale build/ and dist/ artefacts.
3. Runs PyInstaller with the correct .spec for the current platform.
4. On macOS: optionally calls create-dmg to produce a distributable .dmg.
5. On Windows: optionally calls signtool.exe if a signing cert is configured.
6. Prints the final output path.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration — edit these to match your setup
# ---------------------------------------------------------------------------

APP_NAME = "NativePythonInstaller"
VERSION  = "9.0.0"

# macOS code-signing (optional).
# Set to your "Developer ID Application: …" string, or leave as None.
MACOS_CODESIGN_IDENTITY: str | None = None

# Windows code-signing (optional).
# Set to the path of signtool.exe and your certificate thumbprint, or None.
WINDOWS_SIGNTOOL_PATH: str | None = None          # e.g. r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe"
WINDOWS_CERT_THUMBPRINT: str | None = None        # SHA-1 thumbprint of your code-signing cert

# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.resolve()


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print(f"\n» {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd or ROOT, check=check)


def detect_platform() -> str:
    s = platform.system().lower()
    if s == "windows":
        return "windows"
    if s == "darwin":
        return "macos"
    sys.exit(f"Unsupported build platform: {platform.system()}.  Run this on Windows or macOS.")


def check_prerequisites(target: str) -> None:
    print("\n── Checking prerequisites ──")

    # PyInstaller
    try:
        import PyInstaller  # noqa: F401
        import importlib.metadata
        ver = importlib.metadata.version("pyinstaller")
        print(f"  ✓ PyInstaller {ver}")
    except ImportError:
        sys.exit(
            "PyInstaller is not installed.\n"
            "Install it with:  pip install pyinstaller"
        )

    # tkinter
    try:
        import tkinter  # noqa: F401
        print("  ✓ tkinter available")
    except ImportError:
        sys.exit(
            "tkinter is not available in this Python installation.\n"
            "  Windows: reinstall Python from python.org with the tcl/tk option ticked.\n"
            "  macOS:   install python.org's macOS package (includes tkinter), or:\n"
            "           brew install python-tk"
        )

    # macOS extras
    if target == "macos":
        if not shutil.which("create-dmg"):
            print(
                "  ⚠ create-dmg not found — DMG creation will be skipped.\n"
                "    Install with:  brew install create-dmg"
            )
        else:
            print("  ✓ create-dmg available")

    # Windows extras
    if target == "windows":
        if WINDOWS_SIGNTOOL_PATH and not Path(WINDOWS_SIGNTOOL_PATH).exists():
            print(f"  ⚠ signtool.exe not found at {WINDOWS_SIGNTOOL_PATH} — signing will be skipped.")
        elif WINDOWS_SIGNTOOL_PATH:
            print(f"  ✓ signtool.exe found")
        else:
            print("  ℹ  No signing cert configured — exe will be unsigned.")

    print()


def clean() -> None:
    print("── Cleaning previous build artefacts ──")
    for d in ["build", "dist", "__pycache__"]:
        target_dir = ROOT / d
        if target_dir.exists():
            shutil.rmtree(target_dir)
            print(f"  removed {target_dir}")


def build_windows() -> Path:
    print("\n── Building Windows .exe ──")
    spec = ROOT / "windows.spec"
    if not spec.exists():
        sys.exit(f"windows.spec not found at {spec}")

    run(["pyinstaller", "--clean", str(spec)])

    exe = ROOT / "dist" / f"{APP_NAME}.exe"
    if not exe.exists():
        sys.exit(f"Build succeeded but expected output not found: {exe}")

    print(f"\n  Output: {exe}  ({exe.stat().st_size / 1_048_576:.1f} MB)")
    return exe


def sign_windows(exe: Path) -> None:
    if not WINDOWS_SIGNTOOL_PATH or not WINDOWS_CERT_THUMBPRINT:
        print("  ℹ  Skipping Windows code signing (not configured).")
        return
    if not Path(WINDOWS_SIGNTOOL_PATH).exists():
        print(f"  ⚠ signtool.exe not found, skipping signing.")
        return

    print("\n── Signing Windows .exe ──")
    run([
        WINDOWS_SIGNTOOL_PATH,
        "sign",
        "/sha1", WINDOWS_CERT_THUMBPRINT,
        "/fd", "sha256",
        "/tr", "http://timestamp.digicert.com",
        "/td", "sha256",
        "/v",
        str(exe),
    ])
    print("  ✓ Signed")


def build_macos() -> Path:
    print("\n── Building macOS .app ──")
    spec = ROOT / "macos.spec"
    if not spec.exists():
        sys.exit(f"macos.spec not found at {spec}")

    run(["pyinstaller", "--clean", str(spec)])

    app = ROOT / "dist" / f"{APP_NAME}.app"
    if not app.exists():
        sys.exit(f"Build succeeded but expected output not found: {app}")

    size_mb = sum(f.stat().st_size for f in app.rglob("*") if f.is_file()) / 1_048_576
    print(f"\n  Output: {app}  ({size_mb:.1f} MB)")
    return app


def sign_macos(app: Path) -> None:
    if not MACOS_CODESIGN_IDENTITY:
        print(
            "\n  ℹ  No code-signing identity configured.\n"
            "     Users on Gatekeeper-enabled Macs will need to right-click → Open\n"
            "     on first launch, or run:\n"
            f"     xattr -dr com.apple.quarantine \"{app}\""
        )
        return

    print(f"\n── Code-signing .app with '{MACOS_CODESIGN_IDENTITY}' ──")
    run([
        "codesign",
        "--force",
        "--deep",
        "--options", "runtime",
        "--sign", MACOS_CODESIGN_IDENTITY,
        "--timestamp",
        str(app),
    ])
    print("  ✓ Signed")

    # Verify
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], check=False)


def build_dmg(app: Path) -> Path:
    if not shutil.which("create-dmg"):
        print("  ℹ  create-dmg not available — skipping DMG creation.")
        return app

    print("\n── Creating distributable .dmg ──")
    dmg = ROOT / "dist" / f"{APP_NAME}-{VERSION}.dmg"
    if dmg.exists():
        dmg.unlink()

    run([
        "create-dmg",
        "--volname",          f"{APP_NAME} {VERSION}",
        "--volicon",          str(ROOT / "assets" / "icon.icns") if (ROOT / "assets" / "icon.icns").exists() else str(app),
        "--window-pos",       "200", "120",
        "--window-size",      "600", "400",
        "--icon-size",        "128",
        "--icon",             f"{APP_NAME}.app", "175", "190",
        "--hide-extension",   f"{APP_NAME}.app",
        "--app-drop-link",    "425", "190",
        "--no-internet-enable",
        str(dmg),
        str(app.parent),
    ])

    if dmg.exists():
        print(f"\n  Output: {dmg}  ({dmg.stat().st_size / 1_048_576:.1f} MB)")
        return dmg
    else:
        print("  ⚠ create-dmg did not produce a .dmg — check output above.")
        return app


def notarize_macos(dmg: Path) -> None:
    """
    Apple notarization — only possible with a paid Apple Developer account.
    Set APPLE_ID, APPLE_TEAM_ID, and APPLE_APP_PASSWORD env vars to enable.
    """
    apple_id  = os.environ.get("APPLE_ID")
    team_id   = os.environ.get("APPLE_TEAM_ID")
    app_pw    = os.environ.get("APPLE_APP_PASSWORD")

    if not all([apple_id, team_id, app_pw, MACOS_CODESIGN_IDENTITY]):
        print(
            "\n  ℹ  Skipping notarization (APPLE_ID / APPLE_TEAM_ID / "
            "APPLE_APP_PASSWORD not set, or no signing identity configured)."
        )
        return

    print("\n── Submitting for Apple notarization ──")
    run([
        "xcrun", "notarytool", "submit", str(dmg),
        "--apple-id",    apple_id,
        "--team-id",     team_id,
        "--password",    app_pw,
        "--wait",
    ])
    run(["xcrun", "stapler", "staple", str(dmg)])
    print("  ✓ Notarized and stapled")


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build NativePythonInstaller")
    parser.add_argument(
        "--platform",
        choices=["windows", "macos"],
        default=None,
        help="Target platform (default: auto-detect)",
    )
    parser.add_argument(
        "--dmg",
        action="store_true",
        help="macOS only: wrap the .app in a distributable .dmg",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip cleaning previous build artefacts",
    )
    args = parser.parse_args()

    target = args.platform or detect_platform()
    print(f"\n{'='*60}")
    print(f"  {APP_NAME}  v{VERSION}  —  {target.capitalize()} build")
    print(f"{'='*60}")

    check_prerequisites(target)

    if not args.no_clean:
        clean()

    if target == "windows":
        exe = build_windows()
        sign_windows(exe)
        print(f"\n✓ Windows build complete:\n  {exe}")

    elif target == "macos":
        app = build_macos()
        sign_macos(app)

        if args.dmg:
            dmg = build_dmg(app)
            notarize_macos(dmg)
            print(f"\n✓ macOS build complete:\n  {dmg}")
        else:
            print(f"\n✓ macOS build complete:\n  {app}")
            print(
                "\n  Tip: run with --dmg to also produce a distributable .dmg\n"
                "       (requires: brew install create-dmg)"
            )


if __name__ == "__main__":
    main()
