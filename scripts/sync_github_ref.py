"""Baixa um commit do GitHub quando git pull falha por 403."""
from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.request
from pathlib import Path

REF = "22b0582d4aa76cc7fb306b32dbfe72f784f4feb9"
REPO = "birizinit/portal_vendedor"
ROOT = Path(__file__).resolve().parents[1]
PRESERVE = {".env", ".venv", "cortex.db", "cortex.db-wal", "cortex.db-shm", "dist", "build", ".git"}


def api_json(url: str) -> dict:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "cortex-sync"})
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=120) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last_err = e
            if attempt < 4:
                time.sleep(1.5 * (attempt + 1))
    raise last_err  # type: ignore[misc]


def download_blob(sha: str, dest: Path) -> None:
    url = f"https://api.github.com/repos/{REPO}/git/blobs/{sha}"
    data = api_json(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(base64.b64decode(data["content"]))


def main() -> None:
    tree_url = f"https://api.github.com/repos/{REPO}/git/trees/{REF}?recursive=1"
    data = api_json(tree_url)
    blobs = [t for t in data.get("tree", []) if t["type"] == "blob"]
    print(f"Baixando {len(blobs)} arquivos de {REF[:7]}…")
    for i, entry in enumerate(blobs, 1):
        p = entry["path"]
        dest = ROOT / p
        if dest.name in PRESERVE or any(part in PRESERVE for part in dest.parts):
            continue
        download_blob(entry["sha"], dest)
        if i % 5 == 0 or i == len(blobs):
            print(f"  {i}/{len(blobs)} {p}")
    print("Concluído:", ROOT)


if __name__ == "__main__":
    main()
