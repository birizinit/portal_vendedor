"""Templates de mensagem ativa — variáveis entre chaves duplas."""
from __future__ import annotations

import re
from typing import Any

_TEMPLATES = [
    {
        "id": "reativacao_7d",
        "title": "Reativação — sem comprar",
        "body": (
            "Olá {{nome}}! Aqui é {{vendedor}} da Lar Plásticos. "
            "Notei que faz um tempo que não conversamos — posso ajudar com "
            "caixas, contentores ou gaveteiros para a {{empresa}}?"
        ),
    },
    {
        "id": "orcamento_aberto",
        "title": "Orçamento em aberto",
        "body": (
            "Oi {{nome}}, tudo bem? Sou {{vendedor}} da Lar Plásticos. "
            "Vi que você tem orçamento conosco — quer que eu revise valores "
            "ou prazos para fechar?"
        ),
    },
    {
        "id": "checkin_curto",
        "title": "Check-in rápido",
        "body": (
            "Olá {{nome}}! Passando para saber se a {{empresa}} precisa de "
            "algum pedido de embalagens nesta semana. Abraço, {{vendedor}}."
        ),
    },
]


def list_templates() -> list[dict]:
    return [{"id": t["id"], "title": t["title"], "body": t["body"]} for t in _TEMPLATES]


def get_template(template_id: str) -> dict | None:
    for t in _TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def render_message(body: str, ctx: dict[str, Any]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1).lower()
        val = ctx.get(key) or ctx.get(key.replace("_", "")) or ""
        return str(val).strip() or m.group(0)

    return _VAR_RE.sub(repl, body)


def build_context(row: dict, seller_name: str) -> dict[str, str]:
    nome = (row.get("name") or row.get("company") or "Cliente").strip()
    empresa = (row.get("company") or row.get("name") or "").strip()
    dias = row.get("days_without_purchase")
    return {
        "nome": nome.split()[0] if nome else "Cliente",
        "nome_completo": nome,
        "empresa": empresa or nome,
        "vendedor": seller_name or "equipe comercial",
        "dias_sem_compra": str(dias) if dias is not None else "",
        "telefone": row.get("phone") or "",
        "segmento": row.get("segment") or "",
    }
