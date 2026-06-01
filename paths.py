"""Pastas do projeto — desenvolvimento local ou .exe (PyInstaller)."""
from __future__ import annotations
import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Código e assets embutidos no .exe."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """Pasta gravável (ao lado do .exe): .env, banco SQLite, caches."""
    raw = os.getenv("CORTEX_DATA_DIR", "").strip()
    if raw:
        return Path(raw)
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
