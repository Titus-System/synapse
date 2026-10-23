from copy import deepcopy
from decimal import Decimal

import pytest

from app.sugestao_adaptacao import (
    METODO_ESTIMATIVA,
    METODO_REFINAMENTO,
    METODO_SONDAGEM,
    MOTIVO_INCOERENTE,
    MOTIVO_NAO_SUPORTADA,
    MOTIVO_PROPOSTA,
    MOTIVO_SEM_MARGEM,
    QUANTUM,
    TaxaSimulada,
    percentual_de_sondagem,
    percentual_que_cabe,
    percentual_refinado,
    propor_alternativa,
    taxa_de_referencia,
    taxas,
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


def _so_taxas_por_cargo(*taxas: dict[str, object]) -> dict[str, object]:
    nucleo = {chave: valor for chave, valor in NUCLEO.items() if chave != "percentual"}
    cargos = [taxa["cargo"] for taxa in taxas]
    return {
        "nucleo": {**nucleo, "cargo": cargos, "taxas_por_cargo": list(taxas)},
        "especificacoes": [],
    }


# Elementos sem taxa: valores em reais, limiares, exclusões e texto ficam como estão.
BONUS = {
    "ref": "elem.4",
    "construto": "bonus_fixo",
    "alvo": {"tipo": "filtro", "valor": {"cargo": "100"}},
    "valor": Decimal("350"),
}
FAIXA_EM_REAIS = {
    "ref": "elem.3",
    "construto": "faixa_valor",
    "limite_inferior": Decimal("100000"),
    "limite_superior": Decimal("200000"),
    "efeito": {"tipo": "bonus_fixo", "valor": Decimal("500")},
}
LIMIAR = {
    "ref": "elem.5",
    "construto": "condicao_limiar",
    "metrica": "vendas",
    "escopo_agregacao": "individual",
    "operador": ">=",
    "limiar": Decimal("40000"),
}
EXCLUSAO = {"ref": "elem.6", "construto": "exclusao", "dimensao": "loja", "valores": ["58"]}
GENERICO = {
    "ref": "elem.7",
    "construto": "generico",
    "descricao": "Bônus de 1% sobre o que passar de R$ 40.000 em vendas.",
}


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


def test_reduz_o_percentual_e_preserva_o_bonus_fixo() -> None:
    especificacoes = [BONUS]

    alternativa = propor_alternativa(
        _representacao(especificacoes=especificacoes),
        Decimal("492100"),
        Decimal("485000"),
        baseline=Decimal("480312"),
    )

    assert alternativa.motivo == MOTIVO_PROPOSTA
    assert alternativa.representacao == {
        "nucleo": {**NUCLEO, "percentual": Decimal("0.0099")},
        "especificacoes": [BONUS],
    }


def test_reduz_cada_taxa_por_cargo_pelo_mesmo_fator() -> None:
    representacao = _so_taxas_por_cargo(
        {"cargo": "100", "percentual": Decimal("0.03")},
        {"cargo": "150", "percentual": Decimal("0.05")},
    )

    alternativa = propor_alternativa(
        representacao, Decimal("492100"), Decimal("485000"), baseline=Decimal("480312")
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_ESTIMATIVA)
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["taxas_por_cargo"] == [
        {"cargo": "100", "percentual": Decimal("0.0119")},
        {"cargo": "150", "percentual": Decimal("0.0198")},
    ]
    assert "percentual" not in alternativa.representacao["nucleo"]


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


# ---- sondagem: orçamento que não fica acima do baseline (T-283) ----

# Um job real: 10% para o cargo 100 em setembro e outubro, simulado na meta de R$ 100 milhões,
# com orçamento de R$ 5 milhões abaixo do baseline na meta.
TAXA_DO_JOB = Decimal("0.1")
SIMULADO_DO_JOB = Decimal("7400123.65")
BASELINE_DO_JOB = Decimal("5730771.25")
ORCAMENTO_DO_JOB = Decimal("5000000")


def test_sondagem_e_a_taxa_proporcional_ao_orcamento_truncada() -> None:
    assert percentual_de_sondagem(TAXA_DO_JOB, SIMULADO_DO_JOB, ORCAMENTO_DO_JOB) == Decimal(
        "0.0675"
    )


@pytest.mark.parametrize(
    ("percentual", "simulado", "orcamento"),
    [
        pytest.param("0.1", "1000", "1000", id="orcamento-igual-ao-simulado"),
        pytest.param("0.1", "1000", "1200", id="orcamento-acima-do-simulado"),
        pytest.param("0.1", "1000", "0", id="orcamento-zero"),
        pytest.param("0.1", "1000", "-10", id="orcamento-negativo"),
        pytest.param("0", "1000", "500", id="taxa-zero"),
        pytest.param("0.0001", "1000000", "1", id="trunca-a-zero"),
    ],
)
def test_nao_sonda_fora_do_intervalo(percentual: str, simulado: str, orcamento: str) -> None:
    assert (
        percentual_de_sondagem(Decimal(percentual), Decimal(simulado), Decimal(orcamento)) is None
    )


def test_com_orcamento_abaixo_do_baseline_a_primeira_taxa_e_a_sondagem() -> None:
    """Os totais não estimam abaixo do baseline, e o job terminava sem tentar taxa nenhuma."""
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": TAXA_DO_JOB}),
        SIMULADO_DO_JOB,
        ORCAMENTO_DO_JOB,
        baseline=BASELINE_DO_JOB,
        anteriores=[TaxaSimulada(TAXA_DO_JOB, SIMULADO_DO_JOB)],
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_SONDAGEM)
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["percentual"] == Decimal("0.0675")


def test_orcamento_igual_ao_baseline_tambem_e_sondado() -> None:
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": TAXA_DO_JOB}),
        SIMULADO_DO_JOB,
        BASELINE_DO_JOB,
        baseline=BASELINE_DO_JOB,
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_SONDAGEM)


def test_entre_o_baseline_e_o_simulado_a_primeira_taxa_continua_pelos_totais() -> None:
    alternativa = propor_alternativa(
        _representacao(), Decimal("492100"), Decimal("485000"), baseline=Decimal("480312")
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_ESTIMATIVA)
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["percentual"] == Decimal("0.0099")


def test_a_taxa_refinada_diz_que_saiu_da_reta() -> None:
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0.02")}),
        Decimal("1800"),
        Decimal("1700"),
        baseline=Decimal("1200"),
        anteriores=[ORIGINAL, PRIMEIRA],
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_REFINAMENTO)


def test_sem_proposta_nao_ha_metodo() -> None:
    alternativa = propor_alternativa(
        _representacao(), Decimal("400000"), Decimal("485000"), baseline=Decimal("480312")
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_SEM_MARGEM, None)


@pytest.mark.parametrize(
    "parte_fixa",
    ["0", "1000000", "4000000", "4900000", "4999999", "5730771.25"],
    ids=[
        "sem-parte-fixa",
        "pequena",
        "media",
        "perto-do-orcamento",
        "taxa-que-cabe-abaixo-do-quantum",
        "igual-ao-baseline",
    ],
)
def test_pela_reta_a_sondagem_nao_corta_demais_e_o_refinamento_acha_a_taxa(
    parte_fixa: str,
) -> None:
    """A comissão é a parte fixa mais a taxa vezes as vendas no escopo. Para qualquer parte fixa
    entre zero e o baseline, a sondagem fica no máximo um `QUANTUM` abaixo da taxa que cabe. Se
    ela não couber, o refinamento pelos dois pontos chega a uma taxa que cabe, ou conclui que
    nenhuma taxa de pelo menos um `QUANTUM` caberia."""
    fixa = Decimal(parte_fixa)
    vendas_no_escopo = (SIMULADO_DO_JOB - fixa) / TAXA_DO_JOB

    def comissao(taxa: Decimal) -> Decimal:
        return fixa + taxa * vendas_no_escopo

    sondagem = percentual_de_sondagem(TAXA_DO_JOB, SIMULADO_DO_JOB, ORCAMENTO_DO_JOB)
    assert sondagem is not None
    assert comissao(sondagem + QUANTUM) > ORCAMENTO_DO_JOB
    if comissao(sondagem) <= ORCAMENTO_DO_JOB:
        # A sondagem coube, e é ela a sugestão: o fluxo não refina uma taxa que já coube.
        return

    refinada = percentual_refinado(
        [
            TaxaSimulada(TAXA_DO_JOB, SIMULADO_DO_JOB),
            TaxaSimulada(sondagem, comissao(sondagem)),
        ],
        ORCAMENTO_DO_JOB,
    )
    if comissao(QUANTUM) <= ORCAMENTO_DO_JOB:
        assert refinada is not None
        assert comissao(refinada) <= ORCAMENTO_DO_JOB < comissao(refinada + QUANTUM)
    else:
        assert refinada is None


# ---- todas as taxas da regra pelo mesmo fator ----


def _regra_mista() -> dict[str, object]:
    """Percentual, taxas por cargo e efeitos percentuais, ao lado de elementos sem taxa."""
    return {
        "nucleo": {
            **NUCLEO,
            "cargo": ["100", "150", "200"],
            "percentual": Decimal("0.02"),
            "taxas_por_cargo": [
                {"cargo": "100", "percentual": Decimal("0.03")},
                {"cargo": "150", "percentual": Decimal("0.05")},
                {"cargo": "200", "percentual": Decimal("0")},
            ],
        },
        "especificacoes": [
            {
                "ref": "elem.1",
                "construto": "janela_datas",
                "data_inicial": "2025-11-20",
                "data_final": "2025-11-30",
                "efeito": {"tipo": "substituicao_pct", "valor": Decimal("0.04")},
            },
            {
                "ref": "elem.2",
                "construto": "faixa_valor",
                "limite_inferior": Decimal("50000"),
                "limite_superior": Decimal("100000"),
                "efeito": {"tipo": "acrescimo_pct", "valor": Decimal("-0.01")},
            },
            FAIXA_EM_REAIS,
            BONUS,
            LIMIAR,
            EXCLUSAO,
            GENERICO,
        ],
    }


def test_reduz_todas_as_taxas_e_mantem_o_resto_da_regra() -> None:
    """A referência é o percentual do núcleo, que a estimativa leva de 0,02 a 0,0079; as outras
    taxas acompanham na mesma proporção, truncadas."""
    representacao = _regra_mista()
    original = deepcopy(representacao)

    alternativa = propor_alternativa(
        representacao, Decimal("492100"), Decimal("485000"), baseline=Decimal("480312")
    )

    esperada = deepcopy(original)
    esperada["nucleo"]["percentual"] = Decimal("0.0079")  # type: ignore[index]
    esperada["nucleo"]["taxas_por_cargo"][0]["percentual"] = Decimal("0.0118")  # type: ignore[index]
    esperada["nucleo"]["taxas_por_cargo"][1]["percentual"] = Decimal("0.0197")  # type: ignore[index]
    esperada["especificacoes"][0]["efeito"]["valor"] = Decimal("0.0158")  # type: ignore[index]
    # Truncar em direção a zero: o acréscimo negativo diminui em módulo, como as demais taxas.
    esperada["especificacoes"][1]["efeito"]["valor"] = Decimal("-0.0039")  # type: ignore[index]
    assert alternativa.motivo == MOTIVO_PROPOSTA
    assert alternativa.representacao == esperada
    assert representacao == original


def test_sonda_todas_as_taxas_quando_o_orcamento_nao_supera_o_baseline() -> None:
    representacao = _so_taxas_por_cargo(
        {"cargo": "100", "percentual": Decimal("0.03")},
        {"cargo": "150", "percentual": Decimal("0.05")},
    )

    alternativa = propor_alternativa(
        representacao, SIMULADO_DO_JOB, ORCAMENTO_DO_JOB, baseline=BASELINE_DO_JOB
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_SONDAGEM)
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["taxas_por_cargo"] == [
        {"cargo": "100", "percentual": Decimal("0.0202")},
        {"cargo": "150", "percentual": Decimal("0.0336")},
    ]


def test_refina_pela_taxa_de_referencia_e_aplica_o_fator_a_todas() -> None:
    """A primeira taxa da cadeia foi de 0,025 a 0,02; a seguinte cabe em 0,0175, 7/8 da atual."""
    representacao = _so_taxas_por_cargo(
        {"cargo": "100", "percentual": Decimal("0.02")},
        {"cargo": "150", "percentual": Decimal("0.04")},
    )

    alternativa = propor_alternativa(
        representacao,
        Decimal("1800"),
        Decimal("1700"),
        baseline=Decimal("1200"),
        anteriores=[ORIGINAL, PRIMEIRA],
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_REFINAMENTO)
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["taxas_por_cargo"] == [
        {"cargo": "100", "percentual": Decimal("0.0175")},
        {"cargo": "150", "percentual": Decimal("0.0350")},
    ]


def test_nao_propoe_quando_uma_taxa_zeraria() -> None:
    """Uma taxa que vira zero tira o cargo da regra, e isso não é reduzir a regra."""
    representacao = _so_taxas_por_cargo(
        {"cargo": "100", "percentual": Decimal("0.03")},
        {"cargo": "150", "percentual": Decimal("0.0001")},
    )

    alternativa = propor_alternativa(
        representacao, Decimal("492100"), Decimal("485000"), baseline=Decimal("480312")
    )

    assert (alternativa.motivo, alternativa.representacao) == (MOTIVO_SEM_MARGEM, None)


def test_regra_sem_taxa_positiva_nao_e_suportada() -> None:
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0")}),
        Decimal("492100"),
        Decimal("485000"),
        baseline=Decimal("480312"),
    )

    assert (alternativa.motivo, alternativa.representacao) == (MOTIVO_NAO_SUPORTADA, None)


def test_le_as_taxas_na_ordem_que_a_api_confere() -> None:
    assert taxas(_regra_mista()) == [
        Decimal("0.02"),
        Decimal("0.03"),
        Decimal("0.05"),
        Decimal("0"),
        Decimal("0.04"),
        Decimal("-0.01"),
    ]


@pytest.mark.parametrize(
    ("representacao", "referencia"),
    [
        pytest.param(_regra_mista(), Decimal("0.02"), id="percentual-do-nucleo"),
        pytest.param(
            _so_taxas_por_cargo(
                {"cargo": "200", "percentual": Decimal("0")},
                {"cargo": "100", "percentual": Decimal("0.03")},
            ),
            Decimal("0.03"),
            id="primeira-taxa-por-cargo-positiva",
        ),
        pytest.param(
            _representacao(nucleo={"percentual": Decimal("0")}), None, id="nenhuma-positiva"
        ),
    ],
)
def test_a_referencia_e_a_primeira_taxa_positiva(
    representacao: dict[str, object], referencia: Decimal | None
) -> None:
    assert taxa_de_referencia(representacao) == referencia
