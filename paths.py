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


def ensure_static_assets() -> Path:
    """Garante static/ em data_dir (volume Fly) com todos os arquivos do bundle."""
    import shutil

    bundle = app_dir() / "static"
    dest = data_dir() / "static"
    dest.mkdir(parents=True, exist_ok=True)
    if bundle.is_dir() and bundle.resolve() != dest.resolve():
        for f in bundle.iterdir():
            if f.is_file():
                shutil.copy2(f, dest / f.name)
    # index.html canônico fica em static/ — não sobrescrever com cópia antiga na raiz
    idx_static = bundle / "index.html"
    idx_root = app_dir() / "index.html"
    idx_dest = dest / "index.html"
    if not idx_static.exists() and idx_root.exists():
        if idx_root.resolve() != idx_dest.resolve():
            shutil.copy2(idx_root, idx_dest)
    return dest


def static_file(name: str) -> Path:
    """Resolve arquivo estático (data_dir primeiro, depois bundle em /app)."""
    p = ensure_static_assets() / name
    if p.exists():
        return p
    fallback = app_dir() / "static" / name
    return fallback if fallback.exists() else p
