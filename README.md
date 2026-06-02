# Cortex · Painel de Vendas B2B

Backend **FastAPI** + front estático (`static/`) para operação com **Ploomes** (CRM),
**Neppo** (WhatsApp) e copiloto **OpenRouter** (opcional).

## Requisitos

- Python 3.11+
- `PLOOMES_API_KEY` no `.env` (dados reais)
- Modo demonstração **somente** com `CORTEX_USE_MOCK=1`

## Rodar em desenvolvimento

```powershell
cd portal
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Abra http://127.0.0.1:8000 — login padrão na primeira execução é exibido no console
(`CORTEX_ADMIN_PWD` ou `cortex@admin`).

## Estrutura

```
app.py              montagem FastAPI + rotas principais
deps.py             middleware de auth e SSE
access_cache.py     cache de carteira (vendedor)
routers/            auth, admin, webhooks
repository.py       Ploomes + inbox + cache de lista
static/
  index.html        shell HTML
  app.css           estilos
  app.js            painel
alerts.py           fila proativa (SLA, reativação, funil)
```

## API (destaques)

| Endpoint | Descrição |
|----------|-----------|
| `GET /api/conversations?offset=&limit=` | Lista paginada (`items`, `total`, `has_more`) |
| `GET /api/alerts` | Alertas (usa cache da lista, sem 2ª carga Ploomes) |
| `GET /api/search?q=` | Busca em conversas + mensagens WhatsApp locais |
| `GET/POST /api/goals` | Meta mensal do vendedor |
| `GET /api/reports/weekly?format=csv` | Relatório semanal |
| `POST /api/admin/agent/pilot/{conv_id}` | Liga/desliga piloto noturno (admin) |
| `GET /api/admin/agent/tower` | Torre de monitoramento em tempo real |
| `POST /api/conversations/{id}/assume` | Vendedor ou admin para a IA |

## Testes e CI

```powershell
$env:CORTEX_USE_MOCK="1"
.\.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions (`.github/workflows/ci.yml`): `ruff` + `pytest`.

## Deploy

Veja `DEPLOY.md` (Fly.io, variáveis, webhooks).

## .exe Windows

```powershell
.\build_exe.ps1
```

Copie `.env` para `dist\Cortex\` junto do executável.
