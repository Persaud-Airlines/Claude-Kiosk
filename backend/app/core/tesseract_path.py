"""Locate the Tesseract OCR executable on macOS, Linux and Windows."""
from __future__ import annotations

import os
import shutil

from .config import get_settings

_WINDOWS_INSTALL_DIRS = (
    r"C:\Program Files\Tesseract-OCR",
    r"C:\Program Files (x86)\Tesseract-OCR",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR"),
)


def find_tesseract() -> str | None:
    configured = get_settings().tesseract_cmd
    if configured:
        return configured
    found = shutil.which("tesseract")
    if found:
        return found
    if os.name == "nt":
        for folder in _WINDOWS_INSTALL_DIRS:
            candidate = os.path.join(folder, "tesseract.exe")
            if folder and os.path.isfile(candidate):
                return candidate
    return None
