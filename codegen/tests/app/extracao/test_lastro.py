from decimal import Decimal

import pytest

from app.extracao.lastro import conferir_numero, conferir_periodo, resolver_periodo
from app.extracao.vocabulario import resolver_codigo


@pytest.mark.parametrize(
    ("trecho", "valor", "percentual", "valido"),
    [
        ("2,5%", Decimal("0.025"), True, True),
        ("2,5%", Decimal("0.03"), True, False),
        ("-10%", Decimal("-0.1"), True, True),
        ("R$ 1,5 milhão", Decimal("1500000"), False, True),
        ("12 milhões", Decimal("12000000"), False, True),
        ("1.000,50", Decimal("1000.50"), False, True),
        ("12 milhões", Decimal("1200000"), False, False),
        ("dois e meio por cento", Decimal("0.025"), True, True),
        ("texto sem número", Decimal("10"), False, False),
    ],
)
def test_numero_com_lastro_literal_e_conversao_brasileira(
    trecho: str, valor: Decimal, percentual: bool, valido: bool
) -> None:
    assert conferir_numero(trecho, trecho, valor, percentual=percentual) is valido


def test_evidencia_fora_do_texto_nao_confere() -> None:
    assert not conferir_numero("pague 2%", "3%", Decimal("0.03"), percentual=True)


@pytest.mark.parametrize(
    ("campo", "termo", "trecho", "codigo", "motivo"),
    [
        ("marca", "PRETO", "PRETO", "10", None),
        ("cargo", "ASSISTENTE DE VENDAS", "ASSISTENTE DE VENDAS", "300", None),
        ("cargo", "gerentes", "gerentes", "150", None),
        ("cargo", "vendedor", "vendedor", None, "termo_ambiguo"),
        ("loja", "13", "loja 14", None, "valor_sem_lastro"),
        ("cargo", "999", "999", None, "codigo_fora_do_vocabulario"),
    ],
)
def test_vocabulario_nunca_resolve_sem_evidencia(
    campo: str, termo: str, trecho: str, codigo: str | None, motivo: str | None
) -> None:
    assert resolver_codigo(campo, termo, trecho, trecho) == (codigo, motivo)


def test_resolucao_do_ano_unico_e_diferente() -> None:
    trecho = "entre setembro e novembro"
    periodo = ["2025-09", "2025-10", "2025-11"]

    assert resolver_periodo(trecho, ["2025-08", "2025-12"]) == periodo
    assert resolver_periodo(trecho, ["2024-12", "2025-01"]) is None
    assert conferir_periodo(trecho, trecho, periodo, ["2025-08"], vigencia=False) == (True, True)
    assert conferir_periodo(trecho, trecho, periodo, ["2024-12", "2025-01"], vigencia=False) == (
        False,
        False,
    )


def test_periodo_numerico_brasileiro_e_resolvido() -> None:
    assert resolver_periodo("de 09/2025 a 11/2025", []) == ["2025-09", "2025-10", "2025-11"]


def test_vigencia_invertida_permanece_para_validacao_de_dominio() -> None:
    assert resolver_periodo("de dezembro a agosto de 2025", ["2025-08"], vigencia=True) == [
        "2025-12",
        "2025-08",
    ]
