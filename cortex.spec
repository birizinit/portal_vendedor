# PyInstaller — gera dist/Cortex/Cortex.exe
# Uso: pyinstaller cortex.spec --noconfirm

import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH)

datas = [
    (str(root / "index.html"), "."),
    (str(root / "static"), "static"),
    (str(root / ".env.example"), "."),
]
for extra in ("ploomes_fields.json", "templates_custom.json", "mock_data.py"):
    p = root / extra
    if p.exists():
        datas.append((str(p), "."))

hiddenimports = [
    "app",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.main",
    "uvicorn.config",
    "uvicorn.importer",
    "uvicorn.server",
    "uvicorn.workers",
    "uvicorn._subprocess",
    "httptools",
    "websockets",
    "watchfiles",
    "h11",
    "wsproto",
    "anyio",
    "anyio._backends",
    "anyio._backends._asyncio",
    "sniffio",
    "email.mime.multipart",
    "multipart",
    "starlette.routing",
    "starlette.responses",
    "starlette.staticfiles",
    "starlette.middleware",
    "starlette.middleware.cors",
    "fastapi",
    "pydantic",
    "pydantic_core",
    "dotenv",
    "httpx",
    "httpx._transports",
    "httpx._transports.default",
    "httpcore",
    "certifi",
    "config",
    "paths",
    "db",
    "auth",
    "repository",
    "models",
    "ai",
    "inbox",
    "scoring",
    "suggestion",
    "intents",
    "templates",
    "ploomes_client",
    "ploomes_mapper",
    "neppo_client",
    "other_properties",
    "ratelimit",
    "documents",
    "mock_data",
]

a = Analysis(
    ["launcher.py"],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Cortex",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Cortex",
)
