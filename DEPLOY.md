# Deploy — Cortex (Painel de Vendas)

Guia de produção. O app sobe com `uvicorn app:app` e serve o front em `/`.

## 1. Variáveis de ambiente (`.env` ao lado do app)

### Obrigatórias
```ini
PLOOMES_API_KEY=...                      # sai do modo demonstração
WEBHOOK_VALIDATION_KEY=<chave-aleatoria> # SEM ela o webhook é recusado
CORTEX_ADMIN_PWD=<senha-forte>           # troca o default 'cortex@admin'
```

### HTTPS / rede (produção exposta)
```ini
SECURE_COOKIES=1                         # cookies de sessão só por HTTPS
CORS_ORIGINS=https://painel.suaempresa.com.br
```

### Neppo (WhatsApp) — para captura/envio real
```ini
NEPPO_CLIENT_KEY=...
NEPPO_CLIENT_SECRET=...
NEPPO_USERNAME=...
NEPPO_PASSWORD=...
```

### IA (opcional, copiloto)
```ini
OPENROUTER_API_KEY=sk-or-...
# CORTEX_AI_MODEL=openrouter/free
```

### Ajustes finos (têm default)
```ini
# CORTEX_SLA_MINUTES=15            # alerta de "aguardando resposta"
# CORTEX_REACTIVATION_FACTOR=1.3   # alerta de cliente esfriando (RFM)
# CORTEX_STALE_DEAL_DAYS=7         # alerta de negócio parado no estágio
# CORTEX_INTAKE_PIPELINE=Entradas e Prospecção   # funil do lead órfão
# CORTEX_INTAKE_STAGE=             # vazio = 1º estágio do funil
```

> **NUNCA** versione o `.env` (já está no `.gitignore`).

## 2. Subir
```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```
Coloque um reverse proxy (Nginx/Caddy) na frente para **HTTPS** e aponte o
webhook do Neppo para `https://SEU_DOMINIO/webhooks/neppo?key=<WEBHOOK_VALIDATION_KEY>`.

## 3. Validações pós-deploy
- `GET /api/health` → deve trazer `mode:"live"`, `ploomes:"ok"`, `neppo:"ok"`.
- Login como admin → criar um vendedor de teste e atribuir o `owner_id` do Ploomes.
- `GET /api/admin/neppo-agents` → `linked > 0` (atribuição de dono por agente OK).
- `GET /api/alerts` → fila de SLA/reativação/negócio parado.
- **Escritas em `dry_run=true` primeiro** (criar cotação a partir de pedido e
  criar negócio do lead órfão), conferir o payload, e só então gravar.

## 4. Backfill do histórico de WhatsApp (admin)
```
POST /api/admin/backfill?pages=200      # cada página ≈ 100 msgs globais
GET  /api/admin/backfill/status
```
Rode **aos poucos** e acompanhe a contagem. As mensagens novas entram sozinhas
pelo webhook — backfill é só para o histórico antigo / tapar buracos.

## 5. Backup
O `cortex.db` (SQLite) guarda **login, sessões e todo o histórico de WhatsApp**.
Faça backup periódico:
```bash
cp cortex.db cortex.db.backup      # ou agende um snapshot diário
```

## Status validado (01/06/2026, ambiente real)
- Ploomes, Neppo e OpenRouter respondendo.
- Vínculo agente↔vendedor: **43 vendedores** mapeados.
- Funil de entrada **"Entradas e Prospecção"** resolvido (estágio "Oportunidades").
- Banco com ~173 mil mensagens; backfill e dedup OK.
