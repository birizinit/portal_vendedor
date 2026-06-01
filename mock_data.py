"""Dados de exemplo — usados quando não há credencial do Ploomes.

Espelham o que o front-end protótipo traz embutido, para você subir o
servidor e ver tudo funcionando antes de integrar as APIs reais.
"""
from __future__ import annotations
from models import Conversation, Message, ScoreComponent, Order


def _c(**kw) -> Conversation:
    return Conversation(**kw)


MOCK_CONVERSATIONS: list[Conversation] = [
    _c(
        id="and", name="Metalúrgica Andrade", initials="MA",
        contact="Roberto Andrade", phone="(11) 98221-7755", cnpj="12.345.678/0001-90",
        since="3a 1m", condition="A prazo 3/3", nfs="9 NFs", freight="FOB", segment="Indústria",
        score=[ScoreComponent(label="Orçamento aberto R$ 22.400", points=34),
                ScoreComponent(label="Cliente recorrente", points=22),
                ScoreComponent(label="Estágio: fechamento", points=24),
                ScoreComponent(label="0 dias sem resposta", points=7)],
        order=Order(code="#4502", date="28/05", status="Em separação", status_kind="go",
                    eta="30/05", value="22.400,00", city="São Paulo",
                    product="Caixa bin PRPB84PTO", qty=120, unit="3,30"),
        orders=[{"c": "#4502", "s": "Em separação", "sc": "go", "v": "22.400,00"},
                {"c": "#4380", "s": "Faturado", "sc": "ok", "v": "18.900,00"}],
        messages=[Message(sender="seller", text="Fechamos a tabela com 5% no volume, Roberto. Posso emitir?", time="09:40"),
                  Message(sender="client", text="Fechado! Pode faturar e me manda o boleto, por favor.", time="09:46")],
    ),
    _c(
        id="sul", name="Distribuidora Sul Ltda", initials="DS",
        contact="João Mendes", phone="(41) 99812-3344", cnpj="23.456.789/0001-11",
        since="2a 3m", condition="A prazo 2/2", nfs="5 NFs", freight="CIF", segment="Distribuição",
        score=[ScoreComponent(label="Orçamento aberto R$ 8.450", points=30),
                ScoreComponent(label="Cliente recorrente", points=20),
                ScoreComponent(label="Estágio: negociação", points=15),
                ScoreComponent(label="0 dias sem resposta", points=7)],
        order=Order(code="#4471", date="28/05", status="Despachado", status_kind="ok",
                    eta="02/06", tracking="BR123456789", carrier="Transportadora XYZ",
                    value="8.450,00", city="Curitiba", product="Gaveteiro bin G3", qty=40, unit="14,04"),
        orders=[{"c": "#4471", "s": "Despachado", "sc": "ok", "v": "8.450,00"},
                {"c": "#4290", "s": "Faturado", "sc": "ok", "v": "6.120,00"}],
        messages=[Message(sender="client", text="Bom dia!", time="09:12"),
                  Message(sender="client", text="O pedido 4471 já saiu? Qual o prazo de entrega pra Curitiba?", time="09:14")],
    ),
    _c(
        id="moc", name="Indústria Mococa", initials="IM",
        contact="Carla Reis", phone="(19) 99654-2210", cnpj="34.567.890/0001-22",
        since="1a 0m", condition="A prazo 1/2", nfs="3 NFs", freight="CIF", segment="Indústria",
        score=[ScoreComponent(label="Orçamento aberto R$ 5.900", points=24),
                ScoreComponent(label="Cliente recorrente", points=20),
                ScoreComponent(label="Estágio: proposta", points=12),
                ScoreComponent(label="1 dia sem resposta", points=7)],
        order=Order(code="#4488", date="27/05", status="Pré-pedido", status_kind="go",
                    eta="—", value="5.900,00", city="Mococa",
                    product="Gaveteiro bin G2", qty=60, unit="7,98", stock=340),
        orders=[{"c": "#4488", "s": "Pré-pedido", "sc": "go", "v": "5.900,00"}],
        messages=[Message(sender="client", text="Boa tarde, vocês têm o gaveteiro bin G2 em estoque pra pronta entrega?", time="14:02")],
    ),
    _c(
        id="veg", name="Comercial Vega", initials="CV",
        contact="Pedro Lima", phone="(11) 98003-1190", cnpj="45.678.901/0001-33",
        since="7m", condition="A prazo 1/1", nfs="2 NFs", freight="FOB", segment="Revenda",
        score=[ScoreComponent(label="Orçamento aberto R$ 3.092", points=14),
                ScoreComponent(label="Cliente novo", points=8),
                ScoreComponent(label="Estágio: negociação", points=15),
                ScoreComponent(label="2 dias sem resposta", points=4)],
        order=Order(code="#4461", date="26/05", status="Pré-pedido", status_kind="go",
                    eta="—", value="3.092,52", city="Guarulhos",
                    product="Caixa PRPWE497S", qty=2, unit="1.546,26"),
        orders=[{"c": "#4461", "s": "Pré-pedido", "sc": "go", "v": "3.092,52"}],
        messages=[Message(sender="seller", text="Pedro, fechei a proposta com o valor que conversamos.", time="Ontem"),
                  Message(sender="client", text="Consegue um desconto melhor nesse valor? Vou ver com meu sócio.", time="Ontem")],
    ),
    _c(
        id="lim", name="Auto Peças Lima", initials="AL",
        contact="Sandra Lima", phone="(15) 98803-7920", cnpj="56.789.012/0001-44",
        since="2m", condition="À vista", nfs="0 NFs", freight="FOB", segment="Varejo",
        score=[ScoreComponent(label="Sem orçamento aberto", points=0),
                ScoreComponent(label="Cliente novo", points=8),
                ScoreComponent(label="Estágio: primeiro contato", points=6),
                ScoreComponent(label="3 dias sem resposta", points=4)],
        order=Order(product="PRPB84PTO", qty=1, unit="3,30", stock=1200),
        orders=[],
        messages=[Message(sender="client", text="Oi, só queria saber quanto custa a peça PRPB84PTO?", time="3h")],
    ),
    _c(
        id="ver", name="Verbum Distribuição", initials="VD",
        contact="Marcos Souza", phone="(15) 98800-1020", cnpj="67.890.123/0001-55",
        since="4m", condition="A prazo 1/1", nfs="1 NF", freight="CIF", segment="Distribuição",
        score=[ScoreComponent(label="Sem orçamento aberto", points=0),
                ScoreComponent(label="Cliente novo", points=8),
                ScoreComponent(label="Estágio: pós-venda", points=6),
                ScoreComponent(label="0 dias sem resposta", points=7)],
        order=Order(code="#4399", date="20/05", status="Faturado", status_kind="ok",
                    eta="22/05", tracking="BR998877665", carrier="Transportadora ZW",
                    value="4.076,80", city="Sorocaba", product="Caixa PRPWE408S", qty=2, unit="2.038,40"),
        orders=[{"c": "#4399", "s": "Faturado", "sc": "ok", "v": "4.076,80"}],
        messages=[Message(sender="client", text="O pedido chegou com uma caixa amassada, preciso resolver isso.", time="5h")],
    ),
]


# Decora o mock com vendedor + tags inteligentes (no live isso vem do Ploomes).
_MOCK_OWNERS = ["Ana Vendas", "Bruno Costa", "Carla Dias", "Diego Reis",
                "Ana Vendas", "Bruno Costa"]


def _mock_tags(c: Conversation) -> list[dict]:
    tags: list[dict] = []
    total = sum(s.points for s in c.score)
    tags.append({"l": "Ativo" if total >= 30 else "Lead",
                 "k": "ok" if total >= 30 else "info"})
    val = c.order.value or ""
    num = float(val.replace(".", "").replace(",", ".")) if val else 0
    if num >= 10000:
        tags.append({"l": "Alto valor", "k": "value"})
    elif num >= 3000:
        tags.append({"l": "Bom valor", "k": "value"})
    if c.segment:
        tags.append({"l": c.segment, "k": "stage"})
    return tags[:4]


for _i, _c in enumerate(MOCK_CONVERSATIONS):
    _c.owner = _MOCK_OWNERS[_i % len(_MOCK_OWNERS)]
    _c.stage = _c.condition
    _c.deal_value = _c.order.value or ""
    _c.tags = _mock_tags(_c)
