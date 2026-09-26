from decimal import Decimal

from app.sugestao_adaptacao import (
    MOTIVO_INCOERENTE,
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


def test_escala_o_percentual_pela_razao_entre_orcamento_e_total() -> None:
    """2,5% custando 492.100 com teto de 485.000 cabe em 2,46%."""
    candidato = percentual_que_cabe(Decimal("0.025"), Decimal("492100"), Decimal("485000"))

    assert candidato == Decimal("0.0246")


def test_trunca_para_baixo_em_vez_de_arredondar() -> None:
    """Arredondar para cima devolveria uma proposta que continua furando o orçamento."""
    candidato = percentual_que_cabe(Decimal("0.02"), Decimal("1000"), Decimal("999.9"))

    assert candidato == Decimal("0.0199")


def test_nao_propoe_quando_a_regra_ja_caberia() -> None:
    assert percentual_que_cabe(Decimal("0.025"), Decimal("400000"), Decimal("485000")) is None


def test_nao_propoe_um_percentual_que_zera() -> None:
    """Regra de 0% não é alternativa: é deixar de comissionar."""
    assert percentual_que_cabe(Decimal("0.0001"), Decimal("1000000"), Decimal("1")) is None


def test_nao_propoe_sem_total_apurado() -> None:
    assert percentual_que_cabe(Decimal("0.025"), Decimal("0"), Decimal("485000")) is None


def test_propoe_mexendo_so_no_percentual_do_nucleo() -> None:
    especificacoes = [{"ref": "elem.1", "construto": "bonus_fixo", "valor": Decimal("250")}]
    alternativa = propor_alternativa(
        _representacao(especificacoes=especificacoes), Decimal("492100"), Decimal("485000")
    )

    assert alternativa.motivo == MOTIVO_PROPOSTA
    assert alternativa.representacao is not None
    nucleo = alternativa.representacao["nucleo"]
    assert nucleo == {**NUCLEO, "percentual": Decimal("0.0246")}
    assert alternativa.representacao["especificacoes"] == especificacoes


def test_nao_propoe_quando_nao_ha_margem() -> None:
    alternativa = propor_alternativa(_representacao(), Decimal("400000"), Decimal("485000"))

    assert alternativa.motivo == MOTIVO_SEM_MARGEM
    assert alternativa.representacao is None


def test_recusa_uma_proposta_que_ja_nasce_incoerente() -> None:
    """Propor uma regra inválida custaria um ciclo de simulação para terminar no mesmo lugar."""
    exclusao = {"ref": "elem.1", "construto": "exclusao", "dimensao": "loja", "valores": ["13"]}
    alternativa = propor_alternativa(
        _representacao(especificacoes=[exclusao]), Decimal("492100"), Decimal("485000")
    )

    assert alternativa.motivo == MOTIVO_INCOERENTE
    assert alternativa.representacao is None
