"""Testes dos motores puros (sem rede): score, intenção, parcelas, RFM, WhatsApp.

Roda:  .venv/Scripts/python.exe -m pytest -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scoring import build_score_real, score_of, score_level   # noqa: E402
from intents import (detect_intent, normalize, order_line_count,  # noqa: E402
                    parse_order)
from models import Conversation, Message                       # noqa: E402
from suggestion import build_suggestion                        # noqa: E402
from ploomes_mapper import (_parse_installments, strip_emoji,  # noqa: E402
                            client_insights_from_orders)
from neppo_client import clean_message_text, normalize_phone   # noqa: E402


class _C:
    def __init__(self, comps):
        self.score = comps


# ---------------------------------------------------------------- score
def test_score_lead_baixo():
    c = _C(build_score_real(open_value=0, stage="Oportunidades",
                            client_status="", days_no_purchase=None, buy_frequency=""))
    assert score_of(c) <= 15
    assert score_level(score_of(c)) == "Prioridade baixa"


def test_score_cliente_quente_alto():
    c = _C(build_score_real(open_value=25000, stage="Fechamento",
                            client_status="Ativo", days_no_purchase=8,
                            buy_frequency="Semanal"))
    assert score_of(c) >= 60
    assert score_level(score_of(c)) == "Prioridade alta"


def test_score_inativo_penaliza():
    ativo = score_of(_C(build_score_real(open_value=5000, stage="Negociação",
                        client_status="Ativo", days_no_purchase=10, buy_frequency="")))
    inativo = score_of(_C(build_score_real(open_value=5000, stage="Negociação",
                          client_status="Inativo", days_no_purchase=300, buy_frequency="")))
    assert inativo < ativo


def test_score_clamp_0_100():
    c = _C(build_score_real(open_value=999999, stage="Fechamento",
                            client_status="Ativo", days_no_purchase=1, buy_frequency="Semanal"))
    assert 0 <= score_of(c) <= 100


# ---------------------------------------------------------------- intenção
def test_normalize_remove_acento():
    assert normalize("Negociação ÀÉÍ") == "negociacao aei"


def test_detect_status_pedido():
    m = detect_intent("cadê meu pedido? já saiu pra entrega?")
    assert m and m.id == "status_pedido"


def test_detect_pos_venda_prioritario():
    m = detect_intent("chegou com defeito, quero trocar")
    assert m and m.id == "pos_venda"


def test_detect_sem_intencao():
    assert detect_intent("xpto blarg 123") is None


# -------------------------------------------------- pedido (itens + qtd)
def test_order_line_count_conta_quantidades():
    msg = ("60 unid. Lixeira 20 litros azul 60 unid. Lixeira 20 litros "
           "vermelha 60 unid. Lixeira 20 litros cinza")
    assert order_line_count(msg) == 3            # 3x "60 unid"


def test_order_line_count_ignora_litros():
    # "20 litros" é especificação do produto, não quantidade de pedido
    assert order_line_count("qual o valor da lixeira de 20 litros?") == 0


def test_order_line_count_unidades_variadas():
    assert order_line_count("preciso de 10 caixas e 3x palete") == 2


def test_parse_order_quebra_itens():
    msg = ("60 unid. Lixeira 20 litros azul 60 unid. Lixeira 20 litros "
           "vermelha 60 unid. Lixeira 20 litros cinza")
    itens = parse_order(msg)
    assert len(itens) == 3
    assert itens[0] == {"quantity": 60, "unit": "unid",
                        "description": "Lixeira 20 litros azul"}
    assert itens[2]["description"] == "Lixeira 20 litros cinza"


def test_parse_order_sem_pedido():
    assert parse_order("qual o valor da lixeira de 20 litros?") == []


def test_feedback_by_intent_acceptance():
    import db
    iid = "_test_intent_xyz"
    db.run("DELETE FROM feedback WHERE intent_id=?", (iid,))
    for action in ("used", "used", "edited", "ignored"):
        db.save_feedback(action, iid, "c1", 1, "2026-06-01T10:00:00")
    try:
        stats = db.feedback_by_intent()[iid]
        assert stats["used"] == 2 and stats["edited"] == 1 and stats["ignored"] == 1
        assert stats["total"] == 4
        assert stats["acceptance"] == round((2 + 0.5) / 4, 2)   # 0.62
    finally:
        db.run("DELETE FROM feedback WHERE intent_id=?", (iid,))


def test_suggestion_pedido_nao_pergunta_item_quantidade():
    c = Conversation(id="1", name="Lojas X", initials="LX", contact="Andréia",
                     phone="5511999990000")
    c.messages = [Message(sender="client", time="10:00",
                          text="60 unid. Lixeira 20 litros azul 60 unid. "
                               "Lixeira 20 litros vermelha")]
    s = build_suggestion(c)
    assert s and s.intent.id == "pedido_itens"
    # não pode PEDIR de novo o que já foi informado (mencionar p/ confirmar, ok)
    low = s.text.lower()
    assert "me diz o item" not in low
    assert "qual quantidade" not in low
    assert "para qual quantidade" not in low


# ---------------------------------------------------------------- parcelas
def test_parcelas_multiplas():
    raw = "<p>1  BOLETO - PRAZO  31  R$ 9.936,74</p>\n<p>2  BOLETO - PRAZO  60  R$ 9.936,74</p>"
    assert _parse_installments(raw) == "2x BOLETO (31/60d)"


def test_parcelas_vazio():
    assert _parse_installments("") == ""


# ---------------------------------------------------------------- RFM
def test_rfm_agrega_produtos_e_total():
    orders = [
        {"Amount": 1000, "Date": "2026-05-01T00:00:00-03:00",
         "Products": [{"ProductName": "Caixa", "Quantity": 2, "Total": 600},
                      {"ProductName": "Tampa", "Quantity": 2, "Total": 400}]},
        {"Amount": 500, "Date": "2026-05-20T00:00:00-03:00",
         "Products": [{"ProductName": "Caixa", "Quantity": 1, "Total": 500}]},
    ]
    ins = client_insights_from_orders(orders)
    assert ins["orders_count"] == 2
    assert ins["top_products"][0]["name"] == "Caixa"   # 1100 > 400
    assert ins["last_purchase"] == "20/05/2026"


# -------------------------------------------------- Neppo: sessão na timeline
def test_neppo_session_summary_na_timeline():
    from other_properties import catalog
    import ploomes_mapper as pm
    # registra nomes dos campos Neppo no catálogo (simula o ploomes_fields.json)
    catalog.replace({
        "ir_status": "Status da sessão (Neppo)",
        "ir_agente": "Agente da sessão (Neppo)",
        "ir_tempo": "Tempo médio de atendimento (s) (Neppo)",
    })
    try:
        rec = {
            "TypeId": 1, "Title": "Interação", "Content": "conversa",
            "Date": "2026-05-30T10:00:00-03:00",
            "OtherProperties": [
                {"FieldKey": "ir_status", "StringValue": "Encerrada"},
                {"FieldKey": "ir_agente", "StringValue": "João Vendas"},
                {"FieldKey": "ir_tempo", "IntegerValue": 142},
            ],
        }
        item = pm.timeline_item_from_interaction(rec)
        assert item.source == "neppo" and item.kind == "whatsapp"
        assert "Encerrada" in item.content
        assert "agente João Vendas" in item.content
        assert "142s atend." in item.content
    finally:
        catalog._load_from_disk()    # restaura nomes reais p/ não contaminar


def test_timeline_sem_neppo_continua_ploomes():
    import ploomes_mapper as pm
    rec = {"TypeId": 1, "Title": "Anotação", "Content": "ligou", "Date": "2026-05-30"}
    item = pm.timeline_item_from_interaction(rec)
    assert item.source == "ploomes"


# -------------------------------------------------- alertas proativos
def test_alerts_sla_reactivation_stale():
    import datetime as _dt
    import alerts
    now = _dt.datetime(2026, 6, 1, 12, 0, 0)
    convs = [
        Conversation(id="1", name="SLA", initials="S", contact="a", phone="1",
                     awaiting_reply=True, last_activity="2026-06-01T11:30:00"),
        Conversation(id="2", name="Reativar", initials="R", contact="b", phone="2",
                     days_without_purchase=80, buy_frequency_days=30),
        Conversation(id="3", name="Parado", initials="P", contact="c", phone="3",
                     stage="Proposta", days_in_stage=20),
        Conversation(id="4", name="OK", initials="O", contact="d", phone="4",
                     awaiting_reply=True, last_activity="2026-06-01T11:58:00"),
        Conversation(id="5", name="Soneca", initials="Z", contact="e", phone="5",
                     awaiting_reply=True, last_activity="2026-06-01T09:00:00",
                     snoozed=True),
    ]
    res = alerts.build_alerts(convs, sla_minutes=15, reactivation_factor=1.3,
                              stale_deal_days=7, now=now)
    assert res["count"] == 3
    assert res["by_kind"] == {"sla": 1, "reactivation": 1, "stale_deal": 1}
    kinds = {a["conv_id"]: a["kind"] for a in res["alerts"]}
    assert kinds == {"1": "sla", "2": "reactivation", "3": "stale_deal"}


def test_alerts_ignora_recente_e_soneca():
    import datetime as _dt
    import alerts
    now = _dt.datetime(2026, 6, 1, 12, 0, 0)
    convs = [
        Conversation(id="4", name="OK", initials="O", contact="d", phone="4",
                     awaiting_reply=True, last_activity="2026-06-01T11:58:00"),
    ]
    assert alerts.build_alerts(convs, sla_minutes=15, now=now)["count"] == 0


# ---------------------------------------------------------------- WhatsApp
def test_clean_message_botao_json():
    raw = '{"type":"button","body":{"text":"Olá, bem-vindo!"}}'
    assert clean_message_text(raw) == "Olá, bem-vindo!"


def test_clean_message_texto_normal():
    assert clean_message_text("oi tudo bem") == "oi tudo bem"


def test_normalize_phone_adiciona_ddi():
    assert normalize_phone("(11) 98221-7755") == "5511982217755"


def test_strip_emoji():
    assert strip_emoji("🟢 Ativo") == "Ativo"
    assert strip_emoji("📝  Orçamentos") == "Orçamentos"
