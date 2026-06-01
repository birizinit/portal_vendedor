"""Testes dos motores puros (sem rede): score, intenção, parcelas, RFM, WhatsApp.

Roda:  .venv/Scripts/python.exe -m pytest -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scoring import build_score_real, score_of, score_level   # noqa: E402
from intents import detect_intent, normalize                  # noqa: E402
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
