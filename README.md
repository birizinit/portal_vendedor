# Cortex · Backend de Vendas

Backend em Python (FastAPI) para o painel de vendas: motor de **score**, motor de
**sugestão por regras** (sem IA), e integração com **Ploomes** (CRM) e **Neppo**
(WhatsApp API oficial).

Sem credenciais, roda em **modo mock** com dados de exemplo — você sobe e já vê
o front funcionando.

## Rodar

```bash
cd cortex-backend
python -m venv .venv && source .venv/bin/activate      # opcional
pip install -r requirements.txt

# coloca o front pra ser servido pelo próprio backend (opcional):
mkdir -p static && cp ../painel-vendas.html static/index.html

uvicorn app:app --reload
```

Abre http://localhost:8000/ (front) ou http://localhost:8000/docs (API).

## Gerar .exe para Windows (sem Python no PC do testador)

Na pasta do projeto, no PowerShell:

```powershell
.\build_exe.ps1
```

Isso cria `dist\Cortex\` com `Cortex.exe` + bibliotecas. **Compacte a pasta inteira
em ZIP** e envie. Quem recebe:

1. Descompacta
2. Dá duplo-clique em `Cortex.exe`
3. O navegador abre sozinho em http://127.0.0.1:8000

Na primeira execução é criado o `.env` ao lado do `.exe`. Sem `PLOOMES_API_KEY` roda
em modo demonstração. Veja `LEIA-ME-INSTALACAO.txt` dentro da pasta.

Para ligar as APIs reais, exporte as variáveis antes de subir:

```bash
export PLOOMES_API_KEY="sua-user-key"
export OPENROUTER_API_KEY="sk-or-v1-..."
```

(Com `PLOOMES_API_KEY` definido, sai do modo mock. Copiloto de IA usa
[OpenRouter](https://openrouter.ai/) — modelo gratuito padrão
`google/gemini-2.0-flash-exp:free`; altere com `CORTEX_AI_MODEL`.)

## Estrutura

```
config.py            variáveis de ambiente / flag de modo mock
models.py            modelos pydantic (Conversation, OrderSummary, QuoteSummary,
                     ClientProfile, TimelineItem) + serializador do front
intents.py           Camada 2A — catálogo de intenções + detecção por regras
templates.py         Camada 2B — textos preenchidos com dados do Ploomes/ERP
suggestion.py        Camada 2  — junta detecção + template
scoring.py           Camada 1  — score heurístico
ratelimit.py         token bucket (120 req/min) + cache TTL
other_properties.py  resolve campos customizados (Sankhya) FieldKey<->Nome
ploomes_fields.json  cache do mapa de campos (1173) — atualizável pela API
ploomes_client.py    cliente OData: deals, orders, quotes, contacts,
                     interactions, products, criação (gated)
ploomes_mapper.py    Ploomes -> OrderSummary/QuoteSummary/ClientProfile/Timeline
neppo_client.py      envio + histórico de WhatsApp + parser de webhook
documents.py         criação GATED de cotação/pedido (preview dry-run -> confirma)
mock_data.py         dados de exemplo (modo mock)
repository.py        abstrai mock vs Ploomes real + enriquecimento por cliente
app.py               FastAPI: API + webhooks + serve o front
```

## Endpoints novos (enriquecimento por cliente)

```
GET  /api/conversations/{id}/profile    Cliente 360 (status, dias sem compra,
                                        segmento, CNPJ, campos Sankhya...)
GET  /api/conversations/{id}/orders     pedidos: status workflow, NF, previsão
                                        de entrega, histórico, itens
GET  /api/conversations/{id}/quotes     cotações: valor, aprovação, itens
GET  /api/conversations/{id}/timeline   linha do tempo combinada CRM + WhatsApp
GET  /api/conversations/{id}/insights    RFM (ticket, total, recência, frequência)
                                        + produtos mais comprados
GET  /api/conversations/{id}/messages   histórico de WhatsApp (Neppo) p/ o thread
GET  /api/products?q=                   busca produto por código/nome
POST /api/documents                     criar cotação/pedido — dry_run=true só
                                        pré-visualiza; dry_run=false grava.
                                        origin_quote_id liga pedido->cotação
POST /api/interactions                  registra interação no CRM (anotação/
                                        WhatsApp/e-mail) — alimenta a timeline
GET  /api/ai/status                      IA disponível? (precisa OPENROUTER_API_KEY)
POST /api/conversations/{id}/ai/summary  resumo da conversa (OpenRouter)
POST /api/conversations/{id}/ai/reply    rascunho de resposta contextual
POST /api/conversations/{id}/ai/next-action  próxima melhor ação
GET  /api/conversations/{id}/ai/sentiment    sentimento / risco (structured)
GET  /api/templates                     lista templates de resposta (padrão+custom)
POST /api/templates                     salva override de um template (ou limpa)
POST /api/admin/refresh-fields          recarrega o mapa de campos do Ploomes
```

**Criação de pedidos/cotações é gated:** o front sempre faz primeiro um
`dry_run=true` (mostra exatamente o payload e o total, sem gravar nada) e só
grava no Ploomes/Sankhya após o vendedor confirmar. Documentos do Sankhya podem
exigir campos de cabeçalho (TOP, Natureza, Empresa...) — informe via
`extra_fields` (nome do campo -> valor) em `documents.py`.

## Onde plugar o real (procure por `>>>` no código)

- `repository.py` — montar as `Conversation` a partir de `ploomes.open_deals()` /
  `deal_context()`; criar/buscar negócio quando chega mensagem nova.
- `ploomes_client.py` — ajustar `$filter`/`$expand` e os IDs dos campos
  customizados (inclusive o campo onde você grava o score).
- `neppo_client.py` — confirmar endpoint de envio e o formato do payload do
  webhook na doc da sua conta.
- `app.py` `/api/feedback` — persistir o sinal Usar/Editar/Ignorar em banco
  (Camada 4) para afinar as regras.

## Como o front conversa com isso

O `painel-vendas.html` traz os dados embutidos no array `DATA`. Para usar o
backend, troque por:

```js
const DATA = await (await fetch("/api/conversations")).json();
```

O formato devolvido por `/api/conversations` é exatamente o que o front espera
(`models.front_conversation`), então é troca direta. A sugestão também pode vir
do servidor em `/api/conversations/{id}/suggestion` em vez de ser calculada no
JS — útil quando você quiser uma única fonte de verdade para o motor de regras.

## Notas

- O limite de **120 req/min** do Ploomes é respeitado pelo token bucket em
  `ratelimit.py`; o contexto do cliente fica em cache (`PLOOMES_CACHE_TTL`).
- A sugestão **nunca** é enviada sozinha: o `/api/send` só dispara o que o
  vendedor confirmou.
