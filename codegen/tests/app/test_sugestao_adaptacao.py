from copy import deepcopy
from decimal import Decimal

import pytest

from app.sugestao_adaptacao import (
    MOTIVO_INCOERENTE,
    MOTIVO_NAO_SUPORTADA,
    MOTIVO_PROPOSTA,
    MOTIVO_SEM_MARGEM,
    TaxaSimulada,
    percentual_que_cabe,
    percentual_refinado,
    propor_alternativa,
)

NUCLEO = {
    "vigencia": {"inicio": "2025-08", "fim": "2025-12"},
    "loja": ["13"],
    "marca": ["10"],
    "cargo": ["100"],
    "percentual": Decimal("0.025"),
}


def _representacao(**sobrescritas: object) -> dict[str, object]:
    nucleo = {**NUCLEO, **sobrescritas.pop("nucleo", {})}  # type: ignore[dict-item]
    return {"nucleo": nucleo, "especificacoes": sobrescritas.pop("especificacoes", [])}


def test_candidata_respeita_orcamento_quando_ha_custo_fora_do_escopo() -> None:
    percentual = Decimal("0.10")
    custo_inalterado = Decimal("900")
    vendas_no_escopo = Decimal("3000")
    baseline = custo_inalterado + Decimal("100")
    orcamento = Decimal("1100")
    simulado = custo_inalterado + vendas_no_escopo * percentual

    candidato = percentual_que_cabe(percentual, simulado, orcamento, baseline=baseline)

    assert candidato is not None
    assert Decimal("0") < candidato < percentual
    assert custo_inalterado + vendas_no_escopo * candidato <= orcamento


def test_estima_sobre_o_incremento_do_exemplo_do_contrato() -> None:
    baseline = Decimal("480312")
    simulado = Decimal("492100")
    orcamento = Decimal("485000")
    percentual = Decimal("0.025")

    candidato = percentual_que_cabe(percentual, simulado, orcamento, baseline=baseline)

    assert candidato == Decimal("0.0099")
    # Caso conservador: nenhuma comissão prévia nas linhas afetadas pela nova taxa.
    assert baseline + (simulado - baseline) * candidato / percentual <= orcamento


def test_trunca_para_baixo_em_vez_de_arredondar() -> None:
    candidato = percentual_que_cabe(
        Decimal("0.02"), Decimal("1000"), Decimal("999.9"), baseline=Decimal("0")
    )

    assert candidato == Decimal("0.0199")


@pytest.mark.parametrize(
    "baseline,simulado,orcamento",
    [
        ("480312", "492100", "480312"),
        ("480312", "492100", "470000"),
        ("480312", "400000", "485000"),
        ("480312", "480312", "480000"),
        ("480312", "0", "485000"),
        ("-1", "1000", "900"),
    ],
)
def test_nao_estima_fora_do_intervalo_suportado(
    baseline: str, simulado: str, orcamento: str
) -> None:
    assert (
        percentual_que_cabe(
            Decimal("0.025"), Decimal(simulado), Decimal(orcamento), baseline=Decimal(baseline)
        )
        is None
    )


def test_nao_propoe_um_percentual_que_zera() -> None:
    assert (
        percentual_que_cabe(
            Decimal("0.0001"), Decimal("1000000"), Decimal("1"), baseline=Decimal("0")
        )
        is None
    )


def test_propoe_mexendo_so_no_percentual_sem_mutar_a_regra_original() -> None:
    representacao = _representacao()
    original = deepcopy(representacao)

    alternativa = propor_alternativa(
        representacao, Decimal("492100"), Decimal("485000"), baseline=Decimal("480312")
    )

    assert alternativa.motivo == MOTIVO_PROPOSTA
    assert alternativa.representacao == {
        "nucleo": {**NUCLEO, "percentual": Decimal("0.0099")},
        "especificacoes": [],
    }
    assert representacao == original


def test_nao_aplica_estimativa_proporcional_a_regra_com_bonus_fixo() -> None:
    especificacoes = [{"ref": "elem.1", "construto": "bonus_fixo", "valor": Decimal("250")}]

    alternativa = propor_alternativa(
        _representacao(especificacoes=especificacoes),
        Decimal("492100"),
        Decimal("485000"),
        baseline=Decimal("480312"),
    )

    assert alternativa.motivo == MOTIVO_NAO_SUPORTADA
    assert alternativa.representacao is None


def test_nao_propoe_quando_nao_ha_estimativa() -> None:
    alternativa = propor_alternativa(
        _representacao(), Decimal("400000"), Decimal("485000"), baseline=Decimal("480312")
    )

    assert alternativa.motivo == MOTIVO_SEM_MARGEM
    assert alternativa.representacao is None


def test_recusa_uma_proposta_que_ja_nasce_incoerente() -> None:
    alternativa = propor_alternativa(
        _representacao(nucleo={"vigencia": {"inicio": "2025-12", "fim": "2025-08"}}),
        Decimal("492100"),
        Decimal("485000"),
        baseline=Decimal("480312"),
    )

    assert alternativa.motivo == MOTIVO_INCOERENTE
    assert alternativa.representacao is None


def test_percentual_inteiro_do_json_tambem_pode_ser_adaptado() -> None:
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": 1}),
        Decimal("1000"),
        Decimal("500"),
        baseline=Decimal("0"),
    )
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["percentual"] == Decimal("0.5000")


# Uma regra só de núcleo custa uma parte fixa mais a taxa vezes as vendas no escopo. Nas taxas
# abaixo, a parte fixa é 1000 e as vendas no escopo, 40000: a comissão é 1000 + 40000 * taxa.
ORIGINAL = TaxaSimulada(Decimal("0.025"), Decimal("2000"))
PRIMEIRA = TaxaSimulada(Decimal("0.02"), Decimal("1800"))


def test_refina_pela_reta_dos_pares_ja_simulados() -> None:
    candidato = percentual_refinado([ORIGINAL, PRIMEIRA], Decimal("1700"))

    assert candidato == Decimal("0.0175")
    assert Decimal("1000") + Decimal("40000") * candidato <= Decimal("1700")


def test_refinamento_trunca_para_baixo() -> None:
    candidato = percentual_refinado([ORIGINAL, PRIMEIRA], Decimal("1701"))

    assert candidato == Decimal("0.0175")
    assert candidato.as_tuple().exponent == -4


def test_refina_pelos_dois_pares_mais_proximos_do_orcamento() -> None:
    distante = TaxaSimulada(Decimal("0.03"), Decimal("3000"))

    candidato = percentual_refinado([distante, ORIGINAL, PRIMEIRA], Decimal("1700"))

    assert candidato == Decimal("0.0175")


def test_refinamento_preserva_a_precisao_decimal() -> None:
    anteriores = [
        TaxaSimulada(Decimal("0.0250"), Decimal("2000.000000000000000001")),
        TaxaSimulada(Decimal("0.0200"), Decimal("1800.000000000000000001")),
    ]

    candidato = percentual_refinado(anteriores, Decimal("1700.000000000000000001"))

    assert candidato == Decimal("0.0175")


@pytest.mark.parametrize(
    "anteriores,orcamento",
    [
        pytest.param([ORIGINAL], "1700", id="um-par-so"),
        pytest.param([ORIGINAL, ORIGINAL], "1700", id="o-mesmo-percentual-duas-vezes"),
        # Com orçamento acima de uma das comissões, só a inclinação barra a reta que sobe.
        pytest.param(
            [ORIGINAL, TaxaSimulada(Decimal("0.02"), Decimal("2100"))],
            "2200",
            id="inclinacao-negativa",
        ),
        pytest.param(
            [ORIGINAL, TaxaSimulada(Decimal("0.02"), Decimal("2000"))], "1700", id="inclinacao-nula"
        ),
        pytest.param([ORIGINAL, PRIMEIRA], "900", id="parte-fixa-acima-do-orcamento"),
        pytest.param([ORIGINAL, PRIMEIRA], "1800", id="nao-reduz-a-menor-taxa"),
    ],
)
def test_nao_refina_sem_uma_reta_que_desca_ate_o_orcamento(
    anteriores: list[TaxaSimulada], orcamento: str
) -> None:
    assert percentual_refinado(anteriores, Decimal(orcamento)) is None


def test_a_partir_da_segunda_tentativa_propoe_pelos_pares_e_nao_pelo_baseline() -> None:
    """Com baseline 1200, a estimativa inicial daria 0,0166; os pares dão a taxa que cabe."""
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0.02")}),
        Decimal("1800"),
        Decimal("1700"),
        baseline=Decimal("1200"),
        anteriores=[ORIGINAL, PRIMEIRA],
    )

    assert alternativa.motivo == MOTIVO_PROPOSTA
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["percentual"] == Decimal("0.0175")


@pytest.mark.parametrize(
    "anteriores",
    [
        pytest.param([PRIMEIRA], id="so-a-regra-simulada"),
        pytest.param([PRIMEIRA, PRIMEIRA], id="a-mesma-taxa-duas-vezes"),
        pytest.param([], id="cadeia-vazia"),
    ],
)
def test_com_menos_de_duas_taxas_simuladas_estima_pelos_totais(
    anteriores: list[TaxaSimulada],
) -> None:
    """Sem reta a traçar, é a primeira taxa desta regra, mesmo que o job já tenha tentado outras."""
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0.02")}),
        Decimal("1800"),
        Decimal("1700"),
        baseline=Decimal("1200"),
        anteriores=anteriores,
    )

    assert alternativa.motivo == MOTIVO_PROPOSTA
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["percentual"] == Decimal("0.0166")


def test_com_duas_taxas_e_sem_reta_ate_o_orcamento_nao_propoe() -> None:
    """Com duas taxas a estimativa é a da reta, e sem ela não se volta à dos totais."""
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0.02")}),
        Decimal("1800"),
        Decimal("900"),
        baseline=Decimal("0"),
        anteriores=[ORIGINAL, PRIMEIRA],
    )

    assert alternativa.motivo == MOTIVO_SEM_MARGEM
    assert alternativa.representacao is None


def test_nao_propoe_taxa_refinada_que_nao_reduz_a_regra_simulada() -> None:
    """A api só aceita a proposta abaixo da taxa da versão de origem."""
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0.015")}),
        Decimal("1600"),
        Decimal("1700"),
        baseline=Decimal("1200"),
        anteriores=[ORIGINAL, PRIMEIRA],
    )

    assert alternativa.motivo == MOTIVO_SEM_MARGEM
