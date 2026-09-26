from copy import deepcopy
from decimal import Decimal

import pytest

from app.sugestao_adaptacao import (
    MOTIVO_INCOERENTE,
    MOTIVO_NAO_SUPORTADA,
    MOTIVO_PROPOSTA,
    MOTIVO_SEM_MARGEM,
    percentual_que_cabe,
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
