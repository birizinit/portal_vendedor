"""Launcher do Cortex — inicia o servidor e abre o navegador (uso no .exe).

Duplo-clique no Cortex.exe: prepara a pasta de dados, sobe a API e abre
http://127.0.0.1:8000 — sem precisar instalar Python.
"""
from __future__ import annotations
import os
import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _bootstrap() -> Path:
    bundle = _bundle_dir()
    data = _data_dir()
    os.environ["CORTEX_DATA_DIR"] = str(data)
    os.chdir(data)
    if str(bundle) not in sys.path:
        sys.path.insert(0, str(bundle))
    return data


def _port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, PORT)) == 0


def _wait_server(timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    health = f"{URL}api/health"
    while time.monotonic() < deadline:
        try:
            with urlopen(health, timeout=2) as r:
                if r.status == 200:
                    return True
        except (URLError, OSError, TimeoutError):
            pass
        time.sleep(0.4)
    return False


def _setup_data(data: Path) -> None:
    """Primeira execução: .env, static e caches na pasta do .exe."""
    data.mkdir(parents=True, exist_ok=True)
    bundle = _bundle_dir()

    example_dst = data / ".env.example"
    example_src = bundle / ".env.example"
    if example_src.exists() and not example_dst.exists():
        shutil.copy2(example_src, example_dst)

    env = data / ".env"
    if not env.exists():
        if example_dst.exists():
            shutil.copy2(example_dst, env)
        else:
            env.write_text("# Cole sua PLOOMES_API_KEY abaixo\nPLOOMES_API_KEY=\n", encoding="utf-8")
        print("[Cortex] Arquivo .env criado — configure PLOOMES_API_KEY antes de usar.")

    for name in ("ploomes_fields.json", "templates_custom.json"):
        src, dst = bundle / name, data / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)

    static = data / "static"
    static.mkdir(exist_ok=True)
    for src_dir in (bundle / "static", bundle):
        if not src_dir.is_dir() and src_dir != bundle:
            continue
        if src_dir == bundle:
            idx = bundle / "index.html"
            if idx.exists():
                shutil.copy2(idx, static / "index.html")
            continue
        for f in src_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, static / f.name)


def _run_uvicorn() -> None:
    import uvicorn

    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
    )


def main() -> int:
    data = _bootstrap()
    print()
    print("  Cortex · Painel de Vendas")
    print("  " + "=" * 36)
    print(f"  Pasta de dados: {data}")
    print()

    _setup_data(data)

    from dotenv import load_dotenv
    load_dotenv(data / ".env", override=True)
    if not os.getenv("CORTEX_USE_MOCK", "").strip().lower() in ("1", "true", "yes"):
        if not os.getenv("PLOOMES_API_KEY", "").strip():
            print()
            print("  ERRO: PLOOMES_API_KEY não encontrada.")
            print(f"  Edite o arquivo: {data / '.env'}")
            print("  (modo demo só com CORTEX_USE_MOCK=1 no .env)")
            print()
            input("  Enter para fechar… ")
            return 1

    if _port_in_use():
        print(f"  Já há algo na porta {PORT} — abrindo o painel no navegador.")
        webbrowser.open(URL)
        print("  Feche esta janela quando terminar (o servidor continua rodando).")
        input("\n  Enter para sair desta janela… ")
        return 0

    print("  Iniciando servidor…")
    thread = threading.Thread(target=_run_uvicorn, daemon=True)
    thread.start()

    if not _wait_server():
        print("\n  ERRO: o servidor não respondeu a tempo.")
        print("  Verifique antivírus/firewall ou se a porta 8000 está livre.")
        input("\n  Enter para fechar… ")
        return 1

    print(f"  Servidor OK: {URL}")
    webbrowser.open(URL)
    print()
    print("  Navegador aberto. Mantenha ESTA janela aberta enquanto usa o Cortex.")
    print("  Para encerrar, feche esta janela ou pressione Ctrl+C.")
    print()

    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n  Encerrando…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
