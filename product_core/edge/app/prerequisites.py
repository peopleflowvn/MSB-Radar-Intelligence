# -*- coding: utf-8 -*-
"""Resolve bundled portable runtimes and report first-run readiness."""
import os
import platform
import shutil
import subprocess
import sys

from .state_paths import local_state_dir


def bundle_root():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def runtime_path(*parts):
    return os.path.join(bundle_root(), "runtime", *parts)


def bundled_webview2():
    folder = runtime_path("webview2")
    return folder if os.path.isfile(os.path.join(folder, "msedgewebview2.exe")) else ""


def installed_webview2():
    bases = (r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application",
             r"C:\Program Files\Microsoft\EdgeWebView\Application")
    return any(os.path.isdir(base) and _find_under(base, "msedgewebview2.exe") for base in bases)


def _find_under(root, filename):
    for folder, _dirs, files in os.walk(root):
        if filename in files:
            return os.path.join(folder, filename)
    return ""


def configure_webview2():
    folder = bundled_webview2()
    if folder:
        # Fixed Runtime >=120 needs AppContainer read/execute ACL on Windows 10.
        # The extracted folder belongs to the current user, so this does not need
        # elevation and keeps first-run fully automatic.
        if platform.system() == "Windows" and platform.release() == "10":
            for sid in ("*S-1-15-2-2", "*S-1-15-2-1"):
                try:
                    subprocess.run(
                        ["icacls.exe", folder, "/grant", f"{sid}:(OI)(CI)(RX)"],
                        capture_output=True, timeout=30,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except (OSError, subprocess.SubprocessError):
                    pass
    return folder


def tesseract_runtime():
    bundled = runtime_path("tesseract", "tesseract.exe")
    if os.path.isfile(bundled):
        return bundled, runtime_path("tesseract", "tessdata")
    installed = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    local_data = os.path.join(local_state_dir(), "tessdata")
    return (installed if os.path.isfile(installed) else shutil.which("tesseract") or "",
            local_data if os.path.isdir(local_data) else "")


def libreoffice_runtime():
    candidates = (
        runtime_path("libreoffice", "program", "soffice.exe"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    )
    return next((path for path in candidates if os.path.isfile(path)), "")


def chrome_path():
    candidates = (
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    )
    return next((path for path in candidates if os.path.isfile(path)), "")


def supported_windows():
    if platform.system() != "Windows" or not platform.machine().endswith("64"):
        return False
    try:
        return int(platform.version().split(".")[-1]) >= 19045
    except (TypeError, ValueError):
        return False


def runtime_readiness():
    tesseract, tessdata = tesseract_runtime()
    languages = []
    if tesseract:
        env = os.environ.copy()
        if tessdata:
            env["TESSDATA_PREFIX"] = tessdata
        try:
            result = subprocess.run([tesseract, "--list-langs"], capture_output=True, text=True,
                                    timeout=15, env=env,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            languages = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
        except Exception:
            pass
    frozen = bool(getattr(sys, "frozen", False))
    is_64bit = platform.machine().endswith("64")
    checks = {
        "windows": {"ok": supported_windows(), "required": True,
                    "label": "Windows 10 22H2/Windows 11"},
        "architecture": {"ok": is_64bit, "required": True, "label": "Windows 64-bit"},
        "chrome": {"ok": bool(chrome_path()), "required": True, "label": "Google Chrome"},
        "webview2": {"ok": bool(bundled_webview2()) if frozen
                     else installed_webview2(), "required": True, "label": "Giao diện WebView2"},
        "ocr": {"ok": bool(tesseract) and "eng" in languages and "vie" in languages,
                "required": frozen, "label": "OCR tiếng Việt/Anh đóng kèm"},
        "legacy_office": {"ok": bool(libreoffice_runtime()), "required": frozen,
                          "label": "Đọc DOC/XLS/PPT đời cũ"},
    }
    return {"ok": all(row["ok"] for row in checks.values() if row["required"]),
            "frozen": frozen, "checks": checks,
            "ocr_languages": languages,
            "support": "Windows 10 22H2 hoặc Windows 11, 64-bit"}
