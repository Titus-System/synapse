from decimal import Decimal

import pytest

from app.numeros import NumeroCitado, extrair_numeros


def _valores(texto: str) -> list[tuple[Decimal, bool]]:
    return [(n.valor, n.percentual) for n in extrair_numeros(texto)]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("R$ 492.100,00", [(Decimal("492100"), False)]),
        ("R$ 492.100", [(Decimal("492100"), False)]),
        ("2,45%", [(Decimal("0.0245"), True)]),
        ("2,45 por cento", [(Decimal("0.0245"), True)]),
        ("2.45%", [(Decimal("0.0245"), True)]),
        ("40 mil reais", [(Decimal("40000"), False)]),
        ("2,5 milhões", [(Decimal("2500000"), False)]),
        ("queda de -2,45%", [(Decimal("0.0245"), True)]),
        ("2025-11", [(Decimal("2025"), False), (Decimal("11"), False)]),
        ("11/2025", [(Decimal("11"), False), (Decimal("2025"), False)]),
        ("loja 13 e loja 58", [(Decimal("13"), False), (Decimal("58"), False)]),
        ("sem número nenhum", []),
    ],
)
def test_extrai_digitos_como_valor_e_percentual_como_fracao(
    texto: str, esperado: list[tuple[Decimal, bool]]
) -> None:
    assert _valores(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("sessenta e oito lojas", [(Decimal("68"), False)]),
        ("treze e cinquenta e oito", [(Decimal("13"), False), (Decimal("58"), False)]),
        ("cinquenta mil reais", [(Decimal("50000"), False)]),
        ("mil reais", [(Decimal("1000"), False)]),
        ("dois milhões e quinhentos mil", [(Decimal("2500000"), False)]),
        ("dois mil e quinhentos e três", [(Decimal("2503"), False)]),
        ("dois por cento", [(Decimal("0.02"), True)]),
        ("um por cento", [(Decimal("0.01"), True)]),
        ("um real", [(Decimal("1"), False)]),
    ],
)
def test_extrai_numeros_por_extenso_com_grandezas(
    texto: str, esperado: list[tuple[Decimal, bool]]
) -> None:
    assert _valores(texto) == esperado


def test_artigo_um_e_uma_nao_e_o_numero_um() -> None:
    assert _valores("uma loja puxou um aumento") == []


def test_por_cento_nao_e_o_numero_cem() -> None:
    assert _valores("2,5 por cento") == [(Decimal("0.025"), True)]


def test_grandeza_depois_de_digitos_nao_e_lida_de_novo_por_extenso() -> None:
    assert _valores("40 mil") == [(Decimal("40000"), False)]


def test_os_digitos_podem_ser_lidos_sem_o_extenso() -> None:
    assert extrair_numeros("treze lojas e 13 marcas", por_extenso=False) == [
        NumeroCitado(Decimal("13"), False)
    ]
