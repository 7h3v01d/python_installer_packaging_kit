# Native Python Installer — Packaging Kit

Packages `native_python_installer_gui_v9.py` into a standalone distributable
that runs **without Python pre-installed** on the target machine.

---

<img width="902" height="772" alt="Screenshot" src="https://github.com/user-attachments/assets/7d204053-bf5f-4e76-8c4b-edfda580d7d5" />


## Project layout

```
project-root/
├── native_python_installer_gui_v9.py   ← the app
├── windows.spec                         ← PyInstaller spec, Windows
├── macos.spec                           ← PyInstaller spec, macOS
├── version_info.txt                     ← Windows .exe version resource
├── build.py                             ← build + sign + dmg automation
├── assets/                              ← optional icons (see below)
│   ├── icon.ico                         ← Windows icon
│   └── icon.icns                        ← macOS icon
└── dist/                                ← output (created by build)
    ├── NativePythonInstaller.exe        ← Windows output
    └── NativePythonInstaller.app/       ← macOS output
```

---

## Prerequisites

### Both platforms

```bash
pip install pyinstaller
```

PyInstaller 6.x is recommended (6.3+ for Python 3.12 compatibility).

### Windows

- Python **from python.org** (not the Microsoft Store) with the
  **tcl/tk** component ticked during install.
- UPX (optional, reduces .exe size by ~30%):
  download from https://upx.github.io and put `upx.exe` on PATH.
- Windows SDK signtool (optional, for code signing).

### macOS

- Python **from python.org** (the .pkg installer), which bundles tkinter.
  The system Python (`/usr/bin/python3`) does **not** include tkinter.
- `create-dmg` for DMG creation (optional):
  ```bash
  brew install create-dmg
  ```
- Xcode Command Line Tools (for codesign / notarytool):
  ```bash
  xcode-select --install
  ```

---

## Building

### Quick start (auto-detects platform)

```bash
python build.py
```

### Explicit platform

```bash
python build.py --platform windows
python build.py --platform macos
```

### macOS: also produce a .dmg

```bash
python build.py --platform macos --dmg
```

---

## Output locations

| Platform | Output |
|----------|--------|
| Windows  | `dist/NativePythonInstaller.exe` |
| macOS    | `dist/NativePythonInstaller.app` |
| macOS + --dmg | `dist/NativePythonInstaller-9.0.0.dmg` |

---

## Code signing (optional but recommended)

### Windows

Edit `build.py` and set:
```python
WINDOWS_SIGNTOOL_PATH   = r"C:\path\to\signtool.exe"
WINDOWS_CERT_THUMBPRINT = "YOUR_CERT_SHA1_THUMBPRINT"
```

### macOS

Edit `build.py` and set:
```python
MACOS_CODESIGN_IDENTITY = "Developer ID Application: Your Name (TEAMID)"
```

For full notarization (Apple Developer account required), set these
environment variables before running `build.py --dmg`:
```bash
export APPLE_ID="you@example.com"
export APPLE_TEAM_ID="YOURTEAMID"
export APPLE_APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"   # App-specific password
```

Without notarization, macOS users will need to right-click → Open on
first launch, or clear the quarantine flag:
```bash
xattr -dr com.apple.quarantine /path/to/NativePythonInstaller.app
```

---

## Icons

Place your icons in `assets/`:

- `assets/icon.ico` — Windows (multi-size .ico recommended; 256×256 minimum)
- `assets/icon.icns` — macOS (.icns bundle; generate with `iconutil`)

If the `assets/` folder or icons are absent the build will succeed without
icons and the default PyInstaller icon will be used.

### Generating a macOS .icns from a PNG

```bash
mkdir icon.iconset
sips -z 16 16     icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 icon.png --out icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset -o assets/icon.icns
```

### Generating a Windows .ico from a PNG (requires Pillow)

```python
from PIL import Image
img = Image.open("icon.png")
img.save("assets/icon.ico", format="ICO", sizes=[(16,16),(32,32),(48,48),(256,256)])
```

---

## Troubleshooting

### "No module named tkinter" at runtime
The Python used to build did not include tkinter. Use python.org's installer
(not the Microsoft Store version on Windows, not the Apple shim on macOS).

### macOS: "App is damaged and can't be opened"
The app was downloaded without being notarized/signed and macOS quarantined it.
```bash
xattr -dr com.apple.quarantine /path/to/NativePythonInstaller.app
```

### Windows: "Windows protected your PC" SmartScreen warning
The .exe is unsigned. Either sign it with a trusted certificate, or users
can click "More info → Run anyway". Signing eliminates this completely.

### Build succeeds but app crashes immediately on target machine
Run from a terminal to see the traceback:
- Windows: `NativePythonInstaller.exe` (drag to cmd/PowerShell)
- macOS: open Terminal, run `/path/to/NativePythonInstaller.app/Contents/MacOS/NativePythonInstaller`

### UPX errors on Windows
Set `upx=False` in `windows.spec` or remove UPX from PATH.
