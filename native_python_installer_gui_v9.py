#!/usr/bin/env python3
"""
Native Python Installer GUI  —  v9
====================================
Downloads the **official CPython installer** directly from python.org and
launches the native OS installer.  Explicitly avoids Microsoft Store and
Apple-sandboxed Python distributions.

Changes in v9
-------------
* Sandboxed-Python detection: flags Microsoft Store stubs (Windows) and
  Apple Xcode shims (macOS) in the "Detected Python" row.
* Improved macOS .pkg URL resolution: scrapes the actual filenames from the
  FTP index page instead of guessing suffix patterns.
* Elevation warning before silent all-users installs on Windows (they fail
  silently without admin rights).
* Post-install verification button: re-checks PATH after install completes
  and tells the user whether the python.org binary is now active.
* Minor UX tweaks: monospace log font, clearer button labels.

Packaging note
--------------
If the target machine has no Python at all, package this script as a
standalone executable with PyInstaller:
    pyinstaller --onefile --windowed native_python_installer_gui_v9.py
"""

from __future__ import annotations

import ctypes
import hashlib
import html as html_lib
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    TOP,
    VERTICAL,
    W,
    X,
    Y,
    BooleanVar,
    DoubleVar,
    StringVar,
    Text,
    Tk,
    filedialog,
    messagebox,
)
from tkinter import ttk

APP_TITLE = "Official CPython Native Installer  (python.org only)"
PYTHON_DOWNLOADS_PAGE = "https://www.python.org/downloads/"
PYTHON_FTP_PREFIX = "https://www.python.org/ftp/python/"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)

# Paths / exe names that indicate a Microsoft Store redirect stub on Windows.
_WINDOWS_STORE_MARKERS = (
    "\\windowsapps\\",
    "microsoft.python",
    "python_",           # Store app folder pattern: Python_3.11.2288.0_x64__...
)

# The Apple shim lives here and is NOT a real CPython build.
_MACOS_SHIM_PATH = "/usr/bin/python3"


@dataclass
class InstallerSelection:
    version: str
    url: str
    filename: str
    platform_name: str
    architecture: str
    fallback_urls: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sandboxed / stub detection helpers
# ---------------------------------------------------------------------------

def _is_windows_store_python(exe_path: str) -> bool:
    """Return True if the resolved path looks like the MS Store stub."""
    lower = exe_path.lower()
    return any(marker in lower for marker in _WINDOWS_STORE_MARKERS)


def _is_apple_shim_python(exe_path: str) -> bool:
    """Return True if exe_path is the Xcode CLI tools shim."""
    try:
        resolved = str(Path(exe_path).resolve())
    except Exception:
        resolved = exe_path
    return resolved == _MACOS_SHIM_PATH


def _annotate_python_detection(version_string: str, exe_path: str) -> str:
    """
    Decorate the version string with a warning if the Python binary is a
    known sandboxed / stub distribution rather than a real CPython install.
    """
    system = platform.system().lower()
    if system == "windows" and _is_windows_store_python(exe_path):
        return f"{version_string}  ⚠ Microsoft Store stub — NOT a real CPython install"
    if system == "darwin" and _is_apple_shim_python(exe_path):
        return f"{version_string}  ⚠ Apple Xcode shim — NOT a real CPython install"
    return version_string


def _running_as_admin() -> bool:
    """Return True when the current process has administrator / root rights."""
    try:
        if platform.system().lower() == "windows":
            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        return os.getuid() == 0  # type: ignore[attr-defined]
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class PythonInstallerApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x740")
        self.root.minsize(800, 640)

        self.message_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.download_thread: threading.Thread | None = None
        self.current_download_path: Path | None = None
        self.current_selection: InstallerSelection | None = None

        detected_str, detected_path = self._detect_existing_python_full()
        self._detected_python_path = detected_path

        self.platform_var = StringVar(value=self._detect_platform())
        self.arch_var = StringVar(value=self._detect_architecture())
        self.version_var = StringVar(value="")
        self.download_dir_var = StringVar(
            value=str(Path.home() / "Downloads" / "python_native_installer")
        )
        self.status_var = StringVar(value="Ready.")
        self.progress_var = DoubleVar(value=0.0)
        self.sha256_var = StringVar(value="Not downloaded yet")
        self.detected_python_var = StringVar(value=detected_str)
        self.latest_var = StringVar(value="Unknown")
        self.silent_install_var = BooleanVar(value=False)
        self.all_users_var = BooleanVar(value=False)
        self.add_to_path_var = BooleanVar(value=True)
        self.include_launcher_var = BooleanVar(value=True)
        self.open_folder_after_download_var = BooleanVar(value=True)

        self._build_ui()
        self._set_platform_defaults()
        self.root.after(125, self._process_queue)
        self.root.after(300, self.refresh_latest_version)

    # ------------------------------------------------------------------ UI --

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill=BOTH, expand=True)

        # Header
        header = ttk.Frame(outer)
        header.pack(fill=X, pady=(0, 10))
        ttk.Label(header, text="Official CPython Native Installer", font=("Segoe UI", 16, "bold")).pack(anchor=W)
        ttk.Label(
            header,
            text=(
                "Downloads the official python.org installer — "
                "explicitly avoids Microsoft Store and Apple Xcode distributions."
            ),
        ).pack(anchor=W, pady=(4, 0))

        # System info
        info = ttk.LabelFrame(outer, text="System")
        info.pack(fill=X, pady=(0, 10))
        grid = ttk.Frame(info, padding=10)
        grid.pack(fill=X)
        self._grid_lv(grid, 0, "Detected platform", self.platform_var)
        self._grid_lv(grid, 1, "Detected architecture", self.arch_var)
        self._grid_lv(grid, 2, "Detected Python (on PATH)", self.detected_python_var)
        self._grid_lv(grid, 3, "Latest official stable (python.org)", self.latest_var)

        # Config
        config = ttk.LabelFrame(outer, text="Installer configuration")
        config.pack(fill=X, pady=(0, 10))
        cfg = ttk.Frame(config, padding=10)
        cfg.pack(fill=X)

        ttk.Label(cfg, text="Target platform").grid(row=0, column=0, sticky=W, padx=(0, 10), pady=4)
        self.platform_combo = ttk.Combobox(
            cfg, textvariable=self.platform_var,
            values=["Windows", "macOS"], state="readonly", width=20,
        )
        self.platform_combo.grid(row=0, column=1, sticky=W, pady=4)
        self.platform_combo.bind("<<ComboboxSelected>>", lambda _e: self._set_platform_defaults())

        ttk.Label(cfg, text="Architecture").grid(row=0, column=2, sticky=W, padx=(20, 10), pady=4)
        self.arch_combo = ttk.Combobox(
            cfg, textvariable=self.arch_var,
            values=["x86_64", "ARM64", "x86"], state="readonly", width=16,
        )
        self.arch_combo.grid(row=0, column=3, sticky=W, pady=4)

        ttk.Label(cfg, text="Version").grid(row=1, column=0, sticky=W, padx=(0, 10), pady=4)
        ttk.Entry(cfg, textvariable=self.version_var, width=22).grid(row=1, column=1, sticky=W, pady=4)
        ttk.Label(cfg, text="Leave blank for latest stable.").grid(row=1, column=2, columnspan=2, sticky=W, padx=(20, 0), pady=4)

        ttk.Label(cfg, text="Download folder").grid(row=2, column=0, sticky=W, padx=(0, 10), pady=4)
        ttk.Entry(cfg, textvariable=self.download_dir_var, width=54).grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Button(cfg, text="Browse…", command=self.choose_download_folder).grid(row=2, column=3, sticky=W, pady=4)

        self.silent_check = ttk.Checkbutton(cfg, text="Silent install (Windows)", variable=self.silent_install_var)
        self.silent_check.grid(row=3, column=0, columnspan=2, sticky=W, pady=(10, 2))

        self.all_users_check = ttk.Checkbutton(cfg, text="Install for all users (requires admin)", variable=self.all_users_var)
        self.all_users_check.grid(row=3, column=2, columnspan=2, sticky=W, pady=(10, 2))

        self.path_check = ttk.Checkbutton(cfg, text="Add Python to PATH (Windows)", variable=self.add_to_path_var)
        self.path_check.grid(row=4, column=0, columnspan=2, sticky=W, pady=2)

        self.launcher_check = ttk.Checkbutton(cfg, text="Install py launcher (Windows)", variable=self.include_launcher_var)
        self.launcher_check.grid(row=4, column=2, columnspan=2, sticky=W, pady=2)

        ttk.Checkbutton(
            cfg, text="Open folder after download",
            variable=self.open_folder_after_download_var,
        ).grid(row=5, column=0, columnspan=2, sticky=W, pady=2)

        # Actions
        actions = ttk.LabelFrame(outer, text="Actions")
        actions.pack(fill=X, pady=(0, 10))
        bar = ttk.Frame(actions, padding=10)
        bar.pack(fill=X)

        ttk.Button(bar, text="↺ Check latest",         command=self.refresh_latest_version).pack(side=LEFT)
        ttk.Button(bar, text="🔍 Preview URL",          command=self.preview_selection).pack(side=LEFT, padx=(8, 0))
        ttk.Button(bar, text="⬇ Download installer",   command=self.start_download).pack(side=LEFT, padx=(8, 0))
        ttk.Button(bar, text="▶ Run installer",         command=self.run_installer).pack(side=LEFT, padx=(8, 0))
        ttk.Button(bar, text="📂 Open folder",          command=self.open_download_folder).pack(side=LEFT, padx=(8, 0))
        ttk.Button(bar, text="✓ Verify install",        command=self.verify_install).pack(side=LEFT, padx=(8, 0))

        # Progress
        prog_frame = ttk.LabelFrame(outer, text="Download")
        prog_frame.pack(fill=X, pady=(0, 10))
        pi = ttk.Frame(prog_frame, padding=10)
        pi.pack(fill=X)
        self.progress = ttk.Progressbar(pi, variable=self.progress_var, maximum=100)
        self.progress.pack(fill=X)
        ttk.Label(pi, textvariable=self.status_var).pack(anchor=W, pady=(6, 2))
        ttk.Label(pi, text="SHA256:").pack(anchor=W)
        ttk.Label(pi, textvariable=self.sha256_var, wraplength=840).pack(anchor=W)

        # Log
        log_frame = ttk.LabelFrame(outer, text="Activity log")
        log_frame.pack(fill=BOTH, expand=True)
        li = ttk.Frame(log_frame, padding=10)
        li.pack(fill=BOTH, expand=True)
        scroll = ttk.Scrollbar(li, orient=VERTICAL)
        scroll.pack(side=RIGHT, fill=Y)
        self.log_text = Text(
            li, height=16, wrap="word",
            yscrollcommand=scroll.set,
            font=("Consolas", 9) if platform.system().lower() == "windows" else ("Menlo", 10),
        )
        self.log_text.pack(fill=BOTH, expand=True)
        scroll.config(command=self.log_text.yview)
        self.log_text.configure(state="disabled")

        ttk.Label(
            outer,
            text="All downloads are sourced exclusively from python.org/ftp/python/. "
                 "For machines without Python, package this script with PyInstaller.",
            wraplength=860,
        ).pack(anchor=W, pady=(8, 0))

    def _grid_lv(self, parent: ttk.Frame, row: int, label: str, variable: StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=W, padx=(0, 12), pady=3)
        ttk.Label(parent, textvariable=variable).grid(row=row, column=1, sticky=W, pady=3)

    # ------------------------------------------------------------ Detection --

    @staticmethod
    def _detect_platform() -> str:
        s = platform.system().lower()
        if s == "darwin":
            return "macOS"
        return "Windows"

    @staticmethod
    def _detect_architecture() -> str:
        m = platform.machine().lower()
        if m in {"amd64", "x86_64"}:
            return "x86_64"
        if m in {"arm64", "aarch64"}:
            return "ARM64"
        if m in {"x86", "i386", "i686"}:
            return "x86"
        return "x86_64"

    @staticmethod
    def _detect_existing_python_full() -> tuple[str, str]:
        """
        Return (display_string, exe_path).  Annotates the display string if a
        sandboxed / stub Python is found.
        """
        candidates = [
            ["python", "--version"],
            ["python3", "--version"],
            ["py", "-V"],
        ]
        for cmd in candidates:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
            except Exception:
                continue
            text = (result.stdout or result.stderr or "").strip()
            if result.returncode == 0 and text:
                # Resolve the actual executable path
                exe = shutil.which(cmd[0]) or ""
                annotated = _annotate_python_detection(text, exe)
                return annotated, exe
        return "No Python interpreter found on PATH", ""

    def _set_platform_defaults(self) -> None:
        target = self.platform_var.get()
        if target == "macOS":
            self.arch_var.set("ARM64" if self._detect_architecture() == "ARM64" else "x86_64")
            self.silent_install_var.set(False)
            for w in (self.silent_check, self.all_users_check, self.path_check, self.launcher_check):
                w.state(["disabled"])
        else:
            for w in (self.silent_check, self.all_users_check, self.path_check, self.launcher_check):
                w.state(["!disabled"])

    # ----------------------------------------------------------- Networking --

    def _make_request(
        self,
        url: str,
        *,
        method: str | None = None,
        accept: str = "*/*",
        referer: str | None = None,
    ) -> urllib.request.Request:
        headers = {
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "close",
        }
        if referer:
            headers["Referer"] = referer
        return urllib.request.Request(url, headers=headers, method=method)

    def http_get_text(self, url: str, timeout: int = 20) -> str:
        req = self._make_request(
            url,
            accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            referer="https://www.python.org/",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    def url_reachable(self, url: str, timeout: int = 20) -> bool:
        req = self._make_request(url, referer="https://www.python.org/")
        req.add_header("Range", "bytes=0-0")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return 200 <= resp.status < 400
        except urllib.error.HTTPError as exc:
            return exc.code == 416  # Range Not Satisfiable still means file exists
        except Exception:
            return False

    # ------------------------------------------------------- Version logic --

    def _version_tuple(self, version: str) -> tuple[int, int, int]:
        parts = version.split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])

    def _html_to_text(self, html: str) -> str:
        text = re.sub(r"(?is)<script\b.*?</script>", " ", html)
        text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
        text = re.sub(r"(?is)<!--.*?-->", " ", text)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</(p|div|li|h[1-4]|section|article|tr|td|th|ul|ol)>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html_lib.unescape(text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"[\t\r\f\v ]+", " ", text)
        text = re.sub(r"\n\s+", "\n", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()

    def _extract_stable_versions_from_source_page(self, html: str) -> list[str]:
        text = self._html_to_text(html)
        stable_section = text
        if "Stable Releases" in text:
            stable_section = text.split("Stable Releases", 1)[1]
            if "Pre-releases" in stable_section:
                stable_section = stable_section.split("Pre-releases", 1)[0]

        versions = re.findall(r"\bPython\s+(\d+\.\d+\.\d+)\b", stable_section, flags=re.IGNORECASE)
        deduped: list[str] = []
        seen: set[str] = set()
        for v in versions:
            if v not in seen:
                seen.add(v)
                deduped.append(v)
        return deduped

    def fetch_all_stable_versions(self) -> list[str]:
        candidates: set[str] = set()
        pages = [
            "https://www.python.org/",
            "https://www.python.org/downloads/",
            "https://www.python.org/downloads/source/",
        ]
        page_html: dict[str, str] = {}
        page_text: dict[str, str] = {}
        for page in pages:
            try:
                html = self.http_get_text(page)
                page_html[page] = html
                page_text[page] = self._html_to_text(html)
            except Exception:
                pass

        for pat in [r"Latest:\s*Python\s+(\d+\.\d+\.\d+)", r"Download\s+Python\s+(\d+\.\d+\.\d+)"]:
            m = re.search(pat, page_text.get("https://www.python.org/", "") +
                          page_text.get("https://www.python.org/downloads/", ""), re.IGNORECASE)
            if m:
                candidates.add(m.group(1))

        for v in self._extract_stable_versions_from_source_page(
            page_html.get("https://www.python.org/downloads/source/", "")
        ):
            candidates.add(v)

        stable = [v for v in candidates if re.fullmatch(r"\d+\.\d+\.\d+", v)]
        if not stable:
            raise RuntimeError("Could not locate a stable release on python.org.")
        return sorted(stable, key=self._version_tuple, reverse=True)

    def fetch_latest_stable_version(self) -> str:
        return self.fetch_all_stable_versions()[0]

    def refresh_latest_version(self) -> None:
        self.status_var.set("Checking python.org for the latest stable release…")
        self.log("Querying python.org for the latest official stable version…")

        def worker() -> None:
            try:
                v = self.fetch_latest_stable_version()
                self.message_queue.put(("latest_version", v))
            except Exception as exc:
                self.message_queue.put(("error", f"Failed to fetch latest version: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------- URL resolution --

    def _release_page_url(self, version: str) -> str:
        slug = version.replace(".", "")
        return f"https://www.python.org/downloads/release/python-{slug}/"

    def _normalize_python_org_url(self, url: str) -> str:
        normalized = urllib.parse.urljoin("https://www.python.org", url)
        parsed = urllib.parse.urlparse(normalized)
        if parsed.scheme != "https" or parsed.netloc.lower() not in {"www.python.org", "python.org"}:
            raise RuntimeError(f"Refusing non-python.org URL: {normalized}")
        return normalized

    def _extract_anchor_pairs(self, html: str) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for href, inner in re.findall(
            r"""<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""",
            html, flags=re.IGNORECASE | re.DOTALL,
        ):
            text = " ".join(re.sub(r"<[^>]+>", "", inner).split())
            if text:
                pairs.append((text, href))
        return pairs

    def _release_page_candidates(self, version: str, target: str, arch: str) -> list[str]:
        try:
            html = self.http_get_text(self._release_page_url(version))
        except Exception:
            return []

        urls: list[str] = []
        for link_text, href in self._extract_anchor_pairs(html):
            try:
                full = self._normalize_python_org_url(href)
            except Exception:
                continue
            if target == "Windows":
                desired = {
                    "x86_64": "Windows installer (64-bit)",
                    "ARM64":  "Windows installer (ARM64)",
                    "x86":    "Windows installer (32-bit)",
                }[arch]
                if link_text == desired:
                    urls.append(full)
            elif target == "macOS":
                if link_text in {"Download macOS installer", "macOS installer"}:
                    urls.append(full)

        # Also regex-scan the raw HTML for any missed links
        escaped = re.escape(version)
        if target == "Windows":
            suffix_map = {"x86_64": r"-amd64\.exe", "ARM64": r"-arm64\.exe", "x86": r"\.exe"}
            suffix = suffix_map[arch]
            for m in re.findall(
                rf"https://www\.python\.org/ftp/python/{escaped}/python-{escaped}{suffix}",
                html, re.IGNORECASE,
            ):
                urls.append(m)
        else:
            for m in re.findall(
                rf"https://www\.python\.org/ftp/python/{escaped}/python-{escaped}[^\"'\s,]+\.pkg",
                html, re.IGNORECASE,
            ):
                urls.append(m)

        return list(dict.fromkeys(urls))

    def _ftp_index_macos_pkgs(self, version: str) -> list[str]:
        """
        Scrape the actual FTP directory listing for the version and return
        all .pkg filenames in preference order (macos11 first).
        """
        index_url = f"{PYTHON_FTP_PREFIX}{version}/"
        try:
            html = self.http_get_text(index_url, timeout=15)
        except Exception:
            return []
        filenames = re.findall(
            rf'href="(python-{re.escape(version)}[^"]+\.pkg)"',
            html, re.IGNORECASE,
        )
        # Prefer macos11, then anything else
        preferred = [f for f in filenames if "macos11" in f.lower()]
        rest = [f for f in filenames if "macos11" not in f.lower()]
        return [f"{index_url}{fn}" for fn in preferred + rest]

    def _windows_manifest_candidates(self, version: str, arch: str) -> list[str]:
        manifest_url = f"{PYTHON_FTP_PREFIX}{version}/windows-{version}.json"
        try:
            text = self.http_get_text(manifest_url)
        except Exception:
            return []
        escaped = re.escape(version)
        exe_urls = [
            u for u in re.findall(
                rf"https://(?:www\.)?python\.org/ftp/python/{escaped}/[^\"\'\s,]+",
                text, re.IGNORECASE,
            )
            if u.lower().endswith(".exe")
        ]
        if arch == "x86_64":
            preferred = [u for u in exe_urls if u.lower().endswith("-amd64.exe")]
        elif arch == "ARM64":
            preferred = [u for u in exe_urls if u.lower().endswith("-arm64.exe")]
        else:
            preferred = [
                u for u in exe_urls
                if re.search(rf"/python-{re.escape(version)}\.exe$", u, re.IGNORECASE)
            ]
        rest = [u for u in exe_urls if u not in preferred]
        return list(dict.fromkeys(preferred + rest))

    def _direct_ftp_candidates(self, version: str, target: str, arch: str) -> list[str]:
        base = f"{PYTHON_FTP_PREFIX}{version}/"
        vp = f"python-{version}"
        if target == "Windows":
            if arch == "x86_64":
                return [f"{base}{vp}-amd64.exe"]
            if arch == "ARM64":
                return [f"{base}{vp}-arm64.exe"]
            return [f"{base}{vp}.exe"]
        if target == "macOS":
            # v9: derive actual filenames from the FTP index first
            scraped = self._ftp_index_macos_pkgs(version)
            if scraped:
                return scraped
            # Fallback: hardcoded guesses (Python ≥ 3.9)
            return [
                f"{base}{vp}-macos11.pkg",
                f"{base}{vp}-macosx10.9.pkg",
            ]
        raise ValueError(f"Unsupported target: {target}")

    def _candidate_urls(self, version: str, target: str, arch: str) -> list[str]:
        urls: list[str] = []
        if target == "Windows":
            urls.extend(self._windows_manifest_candidates(version, arch))
        urls.extend(self._release_page_candidates(version, target, arch))
        urls.extend(self._direct_ftp_candidates(version, target, arch))
        return list(dict.fromkeys(urls))

    def resolve_version(self) -> str:
        typed = self.version_var.get().strip()
        if typed:
            if not re.fullmatch(r"\d+\.\d+\.\d+", typed):
                raise ValueError("Version must be in the form 3.14.4")
            return typed
        latest = self.latest_var.get().strip()
        if latest and latest != "Unknown":
            return latest
        latest = self.fetch_latest_stable_version()
        self.latest_var.set(latest)
        return latest

    def build_selection(self) -> InstallerSelection:
        requested = self.resolve_version()
        target = self.platform_var.get()
        arch = self.arch_var.get()

        if self.version_var.get().strip():
            versions_to_try = [requested]
        else:
            all_v = self.fetch_all_stable_versions()
            versions_to_try = [requested] + [v for v in all_v if v != requested]

        tried_versions: list[str] = []
        tried_urls: list[str] = []

        for version in versions_to_try:
            tried_versions.append(version)
            candidates = self._candidate_urls(version, target, arch)
            for url in candidates:
                tried_urls.append(url)
                if self.url_reachable(url):
                    filename = Path(urllib.parse.urlparse(url).path).name
                    if version != requested and not self.version_var.get().strip():
                        self.message_queue.put(("status", f"Latest {requested} not available yet; using {version}."))
                    return InstallerSelection(
                        version=version,
                        url=url,
                        filename=filename,
                        platform_name=target,
                        architecture=arch,
                        fallback_urls=[u for u in candidates if u != url],
                    )

        raise FileNotFoundError(
            "Could not find a downloadable official installer on python.org.\n\n"
            f"Versions checked: {', '.join(tried_versions[:12])}"
            f"{'…' if len(tried_versions) > 12 else ''}\n\n"
            "URLs tried:\n" + "\n".join(tried_urls[:40]) +
            ("\n…" if len(tried_urls) > 40 else "")
        )

    def preview_selection(self) -> None:
        try:
            sel = self.build_selection()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            self.log(f"Preview failed: {exc}")
            return
        self.current_selection = sel
        self.log(f"Resolved installer URL: {sel.url}")
        messagebox.showinfo(
            APP_TITLE,
            f"Version: {sel.version}\n"
            f"Platform: {sel.platform_name}\n"
            f"Architecture: {sel.architecture}\n\n"
            f"Official URL:\n{sel.url}",
        )

    # ------------------------------------------------------------ Download --

    def choose_download_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.download_dir_var.get())
        if folder:
            self.download_dir_var.set(folder)

    def start_download(self) -> None:
        if self.download_thread and self.download_thread.is_alive():
            messagebox.showwarning(APP_TITLE, "A download is already in progress.")
            return
        try:
            selection = self.build_selection()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            self.log(f"Download preparation failed: {exc}")
            return

        self.current_selection = selection
        self.progress_var.set(0)
        self.sha256_var.set("Calculating after download…")
        self.status_var.set(f"Downloading {selection.filename}…")
        self.log(f"Downloading official installer: {selection.url}")

        self.download_thread = threading.Thread(
            target=self._download_worker, args=(selection,), daemon=True
        )
        self.download_thread.start()

    def _download_worker(self, selection: InstallerSelection) -> None:
        try:
            download_dir = Path(self.download_dir_var.get()).expanduser().resolve()
            download_dir.mkdir(parents=True, exist_ok=True)

            attempted_urls = list(dict.fromkeys([selection.url, *selection.fallback_urls]))
            last_error: Exception | None = None

            for idx, candidate_url in enumerate(attempted_urls, start=1):
                cand_filename = Path(urllib.parse.urlparse(candidate_url).path).name
                destination = download_dir / cand_filename
                tmp = destination.with_suffix(destination.suffix + ".part")

                try:
                    self.message_queue.put(("status", f"Connecting… ({idx}/{len(attempted_urls)})"))
                    req = self._make_request(
                        candidate_url,
                        referer=self._release_page_url(selection.version),
                    )
                    with urllib.request.urlopen(req, timeout=90) as resp, open(tmp, "wb") as fh:
                        total_raw = resp.headers.get("Content-Length")
                        total_bytes = int(total_raw) if total_raw and total_raw.isdigit() else None
                        downloaded = 0
                        hasher = hashlib.sha256()

                        while True:
                            chunk = resp.read(1024 * 256)
                            if not chunk:
                                break
                            fh.write(chunk)
                            hasher.update(chunk)
                            downloaded += len(chunk)

                            if total_bytes:
                                pct = (downloaded / total_bytes) * 100
                                self.message_queue.put(("progress", pct))
                                self.message_queue.put(("status", f"{cand_filename}  {pct:.1f}%"))
                            else:
                                self.message_queue.put(("status", f"{cand_filename}  {downloaded / 1048576:.1f} MB"))

                    tmp.replace(destination)
                    selection.url = candidate_url
                    selection.filename = cand_filename
                    sha = hasher.hexdigest()
                    self.message_queue.put(("download_complete", (selection, destination, sha)))
                    return
                except Exception as exc:
                    last_error = exc
                    try:
                        if tmp.exists():
                            tmp.unlink()
                    except Exception:
                        pass

            raise RuntimeError(
                f"{last_error}\n\nURLs tried:\n" + "\n".join(attempted_urls)
            )
        except Exception as exc:
            self.message_queue.put(("error", f"Download failed: {exc}"))

    # -------------------------------------------------------------- Install --

    def run_installer(self) -> None:
        if not self.current_download_path or not self.current_download_path.exists():
            messagebox.showwarning(APP_TITLE, "Download the installer first.")
            return
        if not self.current_selection:
            messagebox.showwarning(APP_TITLE, "Installer selection is missing.")
            return

        # Elevation check for all-users silent install on Windows
        if (
            self.current_selection.platform_name == "Windows"
            and self.silent_install_var.get()
            and self.all_users_var.get()
            and not _running_as_admin()
        ):
            if not messagebox.askyesno(
                APP_TITLE,
                "You selected 'Install for all users' with silent mode, but this process "
                "is NOT running as Administrator.\n\n"
                "The installer will likely fail silently.\n\n"
                "Continue anyway?",
            ):
                return

        try:
            self._launch_native_installer(self.current_selection, self.current_download_path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Failed to launch installer:\n{exc}")
            self.log(f"Installer launch failed: {exc}")
            return

        self.log(f"Launched native installer: {self.current_download_path}")
        self.status_var.set("Native installer launched — follow OS prompts.")

    def _launch_native_installer(self, selection: InstallerSelection, path: Path) -> None:
        if selection.platform_name == "Windows":
            args = [str(path)]
            if self.silent_install_var.get():
                args.extend([
                    "/quiet",
                    f"InstallAllUsers={1 if self.all_users_var.get() else 0}",
                    f"PrependPath={1 if self.add_to_path_var.get() else 0}",
                    f"Include_launcher={1 if self.include_launcher_var.get() else 0}",
                    "Include_test=0",
                    "AssociateFiles=1",
                ])
            subprocess.Popen(args, shell=False)
            return

        if selection.platform_name == "macOS":
            subprocess.Popen(["open", str(path)])
            return

        raise RuntimeError(f"Unsupported install target: {selection.platform_name}")

    # ------------------------------------------------------- Post-install verification --

    def verify_install(self) -> None:
        """
        Re-check PATH for Python, flag sandboxed distributions, and report
        the result to the user.
        """
        display, exe_path = self._detect_existing_python_full()
        self.detected_python_var.set(display)

        if "⚠" in display:
            self.log(f"Verification: sandboxed Python detected — {exe_path}")
            messagebox.showwarning(
                APP_TITLE,
                f"The Python currently on PATH is a sandboxed / stub distribution:\n\n"
                f"  {display}\n\n"
                "The python.org installer may not have completed yet, or PATH needs "
                "a shell restart.  Try closing and reopening your terminal/shell, "
                "then click 'Verify install' again.",
            )
        elif "No Python" in display:
            self.log("Verification: no Python found on PATH.")
            messagebox.showwarning(
                APP_TITLE,
                "No Python interpreter was found on PATH.\n\n"
                "If the installer just ran, you may need to restart your shell / "
                "log out and back in for PATH changes to take effect.",
            )
        else:
            self.log(f"Verification OK: {display}  [{exe_path}]")
            messagebox.showinfo(
                APP_TITLE,
                f"Python detected on PATH:\n\n"
                f"  {display}\n\n"
                f"  Executable: {exe_path}\n\n"
                "No sandboxed distribution markers found — looks like a real CPython install.",
            )

    # ---------------------------------------------------------------- Misc --

    def open_download_folder(self) -> None:
        folder = Path(self.download_dir_var.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if platform.system().lower() == "windows":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif platform.system().lower() == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not open folder:\n{exc}")

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(END, message + "\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def _process_queue(self) -> None:
        try:
            while True:
                event, payload = self.message_queue.get_nowait()
                if event == "progress":
                    self.progress_var.set(float(payload))
                elif event == "status":
                    self.status_var.set(str(payload))
                elif event == "latest_version":
                    v = str(payload)
                    self.latest_var.set(v)
                    if not self.version_var.get().strip():
                        self.version_var.set(v)
                    self.status_var.set(f"Latest official stable: {v}")
                    self.log(f"Latest stable detected: {v}")
                elif event == "download_complete":
                    selection, path, sha = payload  # type: ignore[misc]
                    self.current_selection = selection
                    self.current_download_path = path
                    self.progress_var.set(100.0)
                    self.sha256_var.set(sha)
                    self.status_var.set(f"Download complete: {path.name}")
                    self.log(f"Download complete: {path}")
                    self.log(f"SHA256: {sha}")
                    self.log("Verify this SHA256 against the checksum listed on python.org/downloads/")
                    if self.open_folder_after_download_var.get():
                        self.open_download_folder()
                elif event == "error":
                    self.status_var.set("Operation failed.")
                    self.log(str(payload))
                    messagebox.showerror(APP_TITLE, str(payload))
        except queue.Empty:
            pass
        finally:
            self.root.after(125, self._process_queue)


# ---------------------------------------------------------------------------

def main() -> int:
    root = Tk()
    try:
        root.iconname(APP_TITLE)
    except Exception:
        pass
    PythonInstallerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
