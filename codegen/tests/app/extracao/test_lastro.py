from decimal import Decimal

import pytest

from app.extracao.lastro import (
    conferir_data,
    conferir_numero,
    conferir_periodo,
    resolver_datas,
    resolver_periodo,
)
from app.extracao.vocabulario import resolver_codigo


@pytest.mark.parametrize(
    ("trecho", "valor", "percentual", "valido"),
    [
        ("2,5%", Decimal("0.025"), True, True),
        ("2,5%", Decimal("0.03"), True, False),
        ("2,5 por cento", Decimal("0.025"), True, True),
        ("2,5 por cento", Decimal("2.5"), True, False),
        ("2,5 por cento", Decimal("0.03"), True, False),
        ("2,5 POR CENTO", Decimal("0.025"), True, True),
        ("2,5 \npor\tcento", Decimal("0.025"), True, True),
        ("-10 por cento", Decimal("-0.1"), True, True),
        ("2,5 por centopeia", Decimal("0.025"), True, False),
        ("0,025", Decimal("0.025"), True, True),
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


ANO_UNICO = ["2025-10", "2025-11"]


@pytest.mark.parametrize(
    ("trecho", "publicadas", "esperado"),
    [
        ("até o dia 10/10", ANO_UNICO, ["2025-10-10"]),
        ("de 24/11 a 30/11", ANO_UNICO, ["2025-11-24", "2025-11-30"]),
        ("até 10/10/2024", ANO_UNICO, ["2024-10-10"]),
        ("até 10/10/2024", ["2025-12", "2026-01"], ["2024-10-10"]),
        ("até 2024-10-10", ["2025-12", "2026-01"], ["2024-10-10"]),
        ("até 10 de outubro", ANO_UNICO, ["2025-10-10"]),
        ("até 1 de março de 2024", ["2025-12", "2026-01"], ["2024-03-01"]),
        ("até 10/10", ["2025-12", "2026-01"], None),
        ("até 10/10", [], None),
        ("até 10/10 ou 11 de outubro", ANO_UNICO, None),
        ("até 31/02", ANO_UNICO, []),
        ("competência 10/2025", ANO_UNICO, []),
        ("sem data alguma", ANO_UNICO, []),
    ],
)
def test_resolve_datas_com_o_ano_do_texto_ou_o_ano_comum_das_competencias(
    trecho: str, publicadas: list[str], esperado: list[str] | None
) -> None:
    assert resolver_datas(trecho, publicadas) == esperado


@pytest.mark.parametrize(
    "trecho",
    [
        "de 24/11 a 31/11",
        "de 2025-11-31 a 2025-11-24",
        "de 24 de novembro a 31 de novembro",
    ],
)
def test_data_invalida_impede_resolucao_parcial_do_trecho(trecho: str) -> None:
    assert resolver_datas(trecho, ANO_UNICO) == []


@pytest.mark.parametrize(
    ("trecho", "valor", "publicadas", "esperado"),
    [
        ("até 10/10", "2025-10-10", ANO_UNICO, (True, True)),
        ("até 10/10", "2025-10-11", ANO_UNICO, (False, True)),
        ("de 24/11 a 30/11", "2025-11-24", ANO_UNICO, (False, True)),
        ("até 10/10", "2025-10-10", ["2025-12", "2026-01"], (False, False)),
    ],
)
def test_data_confere_quando_e_a_unica_que_o_trecho_resolve(
    trecho: str, valor: str, publicadas: list[str], esperado: tuple[bool, bool]
) -> None:
    assert conferir_data(trecho, trecho, valor, publicadas) == esperado


def test_data_fora_do_texto_nao_confere() -> None:
    assert conferir_data("pague até 10/10", "até 11/10", "2025-10-11", ANO_UNICO) == (False, True)
