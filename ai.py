"""Copiloto de IA (OpenRouter) — resumo, rascunho, próxima ação e sentimento.

OpenRouter expõe API compatível com OpenAI (`/chat/completions`). Há modelos
gratuitos (sufixo `:free`) — veja https://openrouter.ai/models?q=free

Sem OPENROUTER_API_KEY, `available()` é False e o app usa só o motor de regras.
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

from paths import data_dir

load_dotenv(data_dir() / ".env")
from pydantic import BaseModel, ValidationError

log = logging.getLogger("cortex.ai")

_DEFAULT_MODEL = "openrouter/free"
# Modelos removidos do catálogo — redireciona para o roteador gratuito.
_DEPRECATED_MODELS = frozenset({
    "google/gemini-2.0-flash-exp:free",
    "google/gemini-2.0-flash-001:free",
})

_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000")
_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Cortex Lar Plasticos")

_HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=55.0, write=15.0, pool=8.0)
_http: Optional[httpx.AsyncClient] = None
if _API_KEY:
    _http = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)


def available() -> bool:
    return _http is not None and bool(_API_KEY)


def current_model() -> str:
    """Lê o modelo a cada chamada (respeita .env após reinício)."""
    raw = (os.getenv("CORTEX_AI_MODEL") or _DEFAULT_MODEL).strip()
    if raw in _DEPRECATED_MODELS:
        log.warning("CORTEX_AI_MODEL=%s indisponível — usando %s", raw, _DEFAULT_MODEL)
        return _DEFAULT_MODEL
    return raw or _DEFAULT_MODEL


def __getattr__(name: str) -> str:
    if name == "MODEL":
        return current_model()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": _SITE_URL,
        "X-Title": _APP_NAME,
    }


# ---------------------------------------------------------------------------
# Instruções base. pt-BR, com guard-rails de vendas.
# ---------------------------------------------------------------------------
_SYSTEM_BASE = (
    "Você é o copiloto de vendas da Lar Plásticos (indústria de plásticos: "
    "caixas, contentores, gaveteiros). Ajuda o vendedor a atender clientes pelo "
    "WhatsApp. Responda SEMPRE em português do Brasil, tom profissional e "
    "cordial, direto ao ponto.\n"
    "Regras invioláveis:\n"
    "- Use APENAS os dados do cliente fornecidos no contexto. NUNCA invente "
    "preço, prazo, desconto, crédito ou status de pedido que não esteja ali.\n"
    "- Se faltar um dado para responder com segurança, diga que vai confirmar "
    "(ex.: 'já confirmo com a logística').\n"
    "- Não prometa desconto sem aprovação; respeite o desconto máximo se "
    "informado.\n"
    "- Mensagens de WhatsApp devem ser curtas e naturais, como um vendedor "
    "humano escreveria. Sem markdown, sem listas longas, no máximo ~4 linhas.\n"
    "- Responda apenas o que foi pedido, sem preâmbulo nem comentários sobre "
    "seu processo.\n"
    "- LEIA o que o cliente já enviou antes de responder. Se ele JÁ informou "
    "itens e quantidades (ex.: '60 unid. Lixeira 20 litros azul'), NUNCA "
    "pergunte de novo o item nem a quantidade. Em vez disso: confirme que "
    "entendeu o pedido repetindo brevemente os itens e quantidades para "
    "conferência e avance (ex.: dizer que vai montar o orçamento na tabela "
    "dele e retornar com valores e prazo). Só pergunte o que realmente falta "
    "(ex.: CNPJ/endereço de entrega, forma de pagamento) — nada que já foi dito."
)


def _client_context_text(ctx: dict) -> str:
    """Monta o bloco de contexto do cliente."""
    p = ctx.get("profile") or {}
    lines: list[str] = ["# CONTEXTO DO CLIENTE"]
    if p:
        lines.append(
            f"Empresa: {p.get('name','—')} | Contato: {ctx.get('contact','—')} | "
            f"Status: {p.get('status','—')} | Segmento: {p.get('segment','—')}"
        )
        fin = []
        if p.get("days_without_purchase") is not None:
            fin.append(f"{p['days_without_purchase']} dias sem comprar")
        if p.get("last_quote_date"):
            fin.append(f"último orçamento {p['last_quote_date']}")
        if p.get("city"):
            fin.append(p["city"])
        if fin:
            lines.append(" · ".join(fin))
        for f in (p.get("fields") or [])[:4]:
            lines.append(f"- {f.get('label')}: {f.get('value')}")

    ins = ctx.get("insights") or {}
    if ins.get("orders_count"):
        lines.append(
            f"\n# COMPRAS (RFM)\nPedidos: {ins.get('orders_count')} · "
            f"ticket médio R$ {ins.get('ticket_fmt','—')} · total R$ "
            f"{ins.get('total_fmt','—')} · última compra {ins.get('last_purchase','—')}"
        )
        tops = ", ".join(f"{t.get('name')} ({t.get('qty')}x)"
                         for t in (ins.get("top_products") or [])[:5])
        if tops:
            lines.append(f"Mais comprados: {tops}")

    orders = ctx.get("orders") or []
    if orders:
        lines.append("\n# PEDIDOS EM ABERTO")
        for o in orders[:6]:
            flag = f" [ATRASADO {o.get('days_late')}d]" if o.get("late") else ""
            lines.append(
                f"- #{o.get('number')} {o.get('status','')}{flag} · "
                f"NF {o.get('nf') or '—'} · entrega {o.get('eta') or '—'} · "
                f"R$ {o.get('amount_fmt','')} · {o.get('payment') or ''}"
            )

    quotes = ctx.get("quotes") or []
    if quotes:
        lines.append("\n# COTAÇÕES")
        for q in quotes[:4]:
            lines.append(
                f"- #{q.get('number')} R$ {q.get('amount_fmt','')} · "
                f"aprovação: {q.get('needs_approval') or '—'}"
            )

    msgs = ctx.get("messages") or []
    if msgs:
        lines.append("\n# CONVERSA RECENTE (WhatsApp)")
        for m in msgs[-18:]:
            who = "Cliente" if m.get("f") == "in" else "Vendedor"
            if m.get("bot"):
                who = "Automático"
            txt = (m.get("t") or "").strip()
            if txt:
                lines.append(f"{who}: {txt}")
    return "\n".join(lines)


def _system_instruction(ctx: dict) -> str:
    return f"{_SYSTEM_BASE}\n\n{_client_context_text(ctx)}"


async def _request(body: dict[str, Any]) -> tuple[int, dict]:
    resp = await _http.post(  # type: ignore[union-attr]
        f"{_BASE_URL}/chat/completions",
        headers=_headers(),
        json=body,
    )
    if resp.status_code >= 400:
        return resp.status_code, {"error": resp.text[:500]}
    return resp.status_code, resp.json()


async def _chat(
    ctx: dict,
    prompt: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.35,
    json_mode: bool = False,
) -> str:
    if _http is None:
        return ""

    model = current_model()
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_instruction(ctx)},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    try:
        code, data = await _request(body)
        if code == 404 and model != _DEFAULT_MODEL:
            log.warning("modelo %s retornou 404 — tentando %s", model, _DEFAULT_MODEL)
            body["model"] = _DEFAULT_MODEL
            code, data = await _request(body)
        if code >= 400:
            log.error("OpenRouter HTTP %s (model=%s): %s", code, body["model"], data.get("error"))
            return ""
    except Exception as e:  # noqa: BLE001
        log.error("OpenRouter falhou: %s", e)
        return ""

    usage = data.get("usage") or {}
    log.info(
        "IA ok model=%s (in=%s, out=%s)",
        data.get("model") or body["model"],
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
    )

    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return (msg.get("content") or "").strip()


async def _ask(ctx: dict, prompt: str, *, max_tokens: int = 1024,
               temperature: float = 0.35) -> str:
    return await _chat(ctx, prompt, max_tokens=max_tokens, temperature=temperature)


# ---------------------------------------------------------------------------
# Funções públicas
# ---------------------------------------------------------------------------
async def summarize(ctx: dict) -> str:
    return await _ask(
        ctx,
        "Resuma a conversa de WhatsApp em até 3 marcadores curtos, depois uma "
        "linha 'Situação:' (onde parou) e uma linha 'Próximo passo:'. Seja objetivo.",
        max_tokens=380,
    )


async def draft_reply(ctx: dict, instruction: str = "") -> str:
    extra = f"\nOrientação do vendedor: {instruction}" if instruction.strip() else ""
    return await _ask(
        ctx,
        "Escreva a próxima mensagem de WhatsApp do vendedor para este cliente, "
        "respondendo à última mensagem dele com base no contexto. Se o cliente "
        "já listou itens e quantidades, trate como um pedido: confirme os itens "
        "entendidos e siga para o orçamento — não peça de novo item nem "
        "quantidade. Apenas o texto da mensagem, pronto para enviar." + extra,
        max_tokens=450,
    )


async def next_best_action(ctx: dict) -> str:
    return await _ask(
        ctx,
        "Qual é a ÚNICA próxima melhor ação do vendedor com este cliente agora? "
        "Responda em 1 frase objetiva começando com um verbo (ex.: 'Ligar hoje "
        "porque...'), citando o motivo concreto do contexto.",
        max_tokens=220,
        temperature=0.25,
    )


class Sentiment(BaseModel):
    sentiment: str       # positivo | neutro | negativo
    buying_signal: str   # alto | medio | baixo
    churn_risk: str      # alto | medio | baixo
    note: str            # justificativa curta (1 frase)


def _parse_json_text(text: str) -> Optional[dict]:
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        return Sentiment.model_validate_json(text).model_dump()
    except (ValidationError, json.JSONDecodeError):
        return None


async def sentiment(ctx: dict) -> Optional[dict]:
    if _http is None:
        return None
    prompt = (
        "Classifique o estado do cliente nesta conversa. "
        "Responda em JSON com exatamente as chaves: "
        "sentiment (positivo|neutro|negativo), "
        "buying_signal (alto|medio|baixo), "
        "churn_risk (alto|medio|baixo), note (string, 1 frase)."
    )
    raw = await _chat(ctx, prompt, max_tokens=400, temperature=0.2, json_mode=True)
    out = _parse_json_text(raw)
    if out:
        return out
    raw = await _ask(
        ctx,
        prompt + " Responda APENAS o objeto JSON, sem markdown.",
        max_tokens=400,
        temperature=0.2,
    )
    return _parse_json_text(raw)
