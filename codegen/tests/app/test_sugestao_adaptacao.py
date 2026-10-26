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
    comissao_fora_da_regra,
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


def test_com_comissao_atual_no_escopo_estima_a_taxa_que_cabe_e_nao_a_do_baseline() -> None:
    """A regra troca 2% por 3% nas vendas de R$ 40.000 do escopo; fora dele ficam R$ 1.000. O
    baseline é R$ 1.800 e a regra custa R$ 2.200, e em R$ 2.000 cabe até 2,5%. Pelo baseline
    inteiro, a estimativa daria 1,5%, abaixo dos 2% que o escopo já recebe, e caberia: a iteração
    terminaria nela."""
    fora_do_escopo = Decimal("1000")
    vendas_no_escopo = Decimal("40000")
    simulado = fora_do_escopo + vendas_no_escopo * Decimal("0.03")

    candidato = percentual_que_cabe(
        Decimal("0.03"), simulado, Decimal("2000"), parte_fixa=fora_do_escopo
    )

    assert candidato == Decimal("0.025")


def test_candidata_e_a_maior_taxa_que_cabe_quando_a_parte_fixa_e_a_verdadeira() -> None:
    percentual = Decimal("0.10")
    custo_inalterado = Decimal("900")
    vendas_no_escopo = Decimal("3000")
    orcamento = Decimal("1100")
    simulado = custo_inalterado + vendas_no_escopo * percentual

    candidato = percentual_que_cabe(percentual, simulado, orcamento, parte_fixa=custo_inalterado)

    assert candidato is not None
    assert custo_inalterado + vendas_no_escopo * candidato <= orcamento
    assert custo_inalterado + vendas_no_escopo * (candidato + QUANTUM) > orcamento


def test_estima_sobre_os_totais_do_exemplo_do_contrato() -> None:
    """Sem comissão prévia nas linhas que a nova taxa alcança, a parte fixa é o baseline."""
    candidato = percentual_que_cabe(
        Decimal("0.025"), Decimal("492100"), Decimal("485000"), parte_fixa=Decimal("480312")
    )

    assert candidato == Decimal("0.0099")


def test_com_a_parte_fixa_no_orcamento_nenhuma_taxa_cabe() -> None:
    """A comissão que a regra não move já consome o orçamento: reduzir a taxa não basta."""
    assert (
        percentual_que_cabe(
            Decimal("0.03"), Decimal("2200"), Decimal("1000"), parte_fixa=Decimal("1000")
        )
        is None
    )


def test_trunca_para_baixo_em_vez_de_arredondar() -> None:
    candidato = percentual_que_cabe(
        Decimal("0.02"), Decimal("1000"), Decimal("999.9"), parte_fixa=Decimal("0")
    )

    assert candidato == Decimal("0.0199")


@pytest.mark.parametrize(
    "parte_fixa,simulado,orcamento",
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
    parte_fixa: str, simulado: str, orcamento: str
) -> None:
    assert (
        percentual_que_cabe(
            Decimal("0.025"), Decimal(simulado), Decimal(orcamento), parte_fixa=Decimal(parte_fixa)
        )
        is None
    )


def test_nao_propoe_um_percentual_que_zera() -> None:
    assert (
        percentual_que_cabe(
            Decimal("0.0001"), Decimal("1000000"), Decimal("1"), parte_fixa=Decimal("0")
        )
        is None
    )


def test_propoe_mexendo_so_no_percentual_sem_mutar_a_regra_original() -> None:
    representacao = _representacao()
    original = deepcopy(representacao)

    alternativa = propor_alternativa(
        representacao, Decimal("492100"), Decimal("485000"), parte_fixa=Decimal("480312")
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
        parte_fixa=Decimal("480312"),
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
        representacao, Decimal("492100"), Decimal("485000"), parte_fixa=Decimal("480312")
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
        _representacao(), Decimal("400000"), Decimal("485000"), parte_fixa=Decimal("480312")
    )

    assert alternativa.motivo == MOTIVO_SEM_MARGEM
    assert alternativa.representacao is None


def test_recusa_uma_proposta_que_ja_nasce_incoerente() -> None:
    alternativa = propor_alternativa(
        _representacao(nucleo={"vigencia": {"inicio": "2025-12", "fim": "2025-08"}}),
        Decimal("492100"),
        Decimal("485000"),
        parte_fixa=Decimal("480312"),
    )

    assert alternativa.motivo == MOTIVO_INCOERENTE
    assert alternativa.representacao is None


def test_percentual_inteiro_do_json_tambem_pode_ser_adaptado() -> None:
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": 1}),
        Decimal("1000"),
        Decimal("500"),
        parte_fixa=Decimal("0"),
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


def test_a_partir_da_segunda_tentativa_propoe_pelos_pares_e_nao_pela_parte_fixa() -> None:
    """Com a parte fixa 1200, a estimativa inicial daria 0,0166; os pares dão a taxa que cabe."""
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0.02")}),
        Decimal("1800"),
        Decimal("1700"),
        parte_fixa=Decimal("1200"),
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
def test_com_menos_de_duas_taxas_simuladas_estima_pela_parte_fixa(
    anteriores: list[TaxaSimulada],
) -> None:
    """Sem reta a traçar, é a primeira taxa desta regra, mesmo que o job já tenha tentado outras."""
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0.02")}),
        Decimal("1800"),
        Decimal("1700"),
        parte_fixa=Decimal("1200"),
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
        parte_fixa=Decimal("0"),
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
        parte_fixa=Decimal("1200"),
        anteriores=[ORIGINAL, PRIMEIRA],
    )

    assert alternativa.motivo == MOTIVO_SEM_MARGEM


# ---- sem detalhamento, a sondagem (T-283) ----

# Um job real: 10% para o cargo 100 em setembro e outubro, simulado na meta de R$ 100 milhões,
# com orçamento de R$ 5 milhões abaixo do baseline na meta.
TAXA_DO_JOB = Decimal("0.1")
SIMULADO_DO_JOB = Decimal("7400123.65")
BASELINE_DO_JOB = Decimal("5730771.25")
ORCAMENTO_DO_JOB = Decimal("5000000")


def test_sem_parte_fixa_a_taxa_e_proporcional_ao_orcamento_truncada() -> None:
    assert percentual_que_cabe(
        TAXA_DO_JOB, SIMULADO_DO_JOB, ORCAMENTO_DO_JOB, parte_fixa=Decimal(0)
    ) == Decimal("0.0675")


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
def test_sem_parte_fixa_nao_estima_fora_do_intervalo(
    percentual: str, simulado: str, orcamento: str
) -> None:
    assert (
        percentual_que_cabe(
            Decimal(percentual), Decimal(simulado), Decimal(orcamento), parte_fixa=Decimal(0)
        )
        is None
    )


def test_sem_detalhamento_a_primeira_taxa_e_a_sondagem() -> None:
    """Sem as linhas do resultado, nenhuma é sabidamente fixa, e a parte fixa é zero."""
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": TAXA_DO_JOB}),
        SIMULADO_DO_JOB,
        ORCAMENTO_DO_JOB,
        parte_fixa=None,
        anteriores=[TaxaSimulada(TAXA_DO_JOB, SIMULADO_DO_JOB)],
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_SONDAGEM)
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["percentual"] == Decimal("0.0675")


def test_com_a_parte_fixa_do_detalhamento_a_primeira_taxa_e_a_estimativa() -> None:
    """O orçamento abaixo do baseline não muda o método: a reta passa pela parte fixa."""
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": TAXA_DO_JOB}),
        SIMULADO_DO_JOB,
        ORCAMENTO_DO_JOB,
        parte_fixa=Decimal("4000000"),
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_ESTIMATIVA)
    assert alternativa.representacao is not None
    assert alternativa.representacao["nucleo"]["percentual"] == Decimal("0.0294")


def test_com_a_parte_fixa_acima_do_orcamento_a_alternativa_e_a_sondagem() -> None:
    """Nenhuma taxa cabe, mas a alternativa ainda é simulada para o usuário ver o motivo."""
    regra = _representacao(nucleo={"percentual": TAXA_DO_JOB})

    alternativa = propor_alternativa(
        regra, SIMULADO_DO_JOB, ORCAMENTO_DO_JOB, parte_fixa=BASELINE_DO_JOB
    )
    sondagem = propor_alternativa(regra, SIMULADO_DO_JOB, ORCAMENTO_DO_JOB, parte_fixa=None)

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_SONDAGEM)
    assert alternativa.representacao == sondagem.representacao


def test_a_taxa_refinada_diz_que_saiu_da_reta() -> None:
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0.02")}),
        Decimal("1800"),
        Decimal("1700"),
        parte_fixa=Decimal("1200"),
        anteriores=[ORIGINAL, PRIMEIRA],
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_PROPOSTA, METODO_REFINAMENTO)


def test_sem_proposta_nao_ha_metodo() -> None:
    alternativa = propor_alternativa(
        _representacao(), Decimal("400000"), Decimal("485000"), parte_fixa=Decimal("480312")
    )

    assert (alternativa.motivo, alternativa.metodo) == (MOTIVO_SEM_MARGEM, None)


@pytest.mark.parametrize(
    "verdadeira",
    ["0", "1000000", "4000000", "4900000", "4999999"],
    ids=["sem-parte-fixa", "pequena", "media", "perto-do-orcamento", "cabe-abaixo-do-quantum"],
)
@pytest.mark.parametrize("conhecida", ["0", "0.5", "1"], ids=["nada", "metade", "toda"])
def test_pela_reta_a_estimativa_nunca_corta_demais_e_o_refinamento_acha_a_taxa(
    verdadeira: str, conhecida: str
) -> None:
    """A comissão é a parte fixa mais a taxa vezes as vendas no escopo. Com qualquer fração da
    parte fixa conhecida, a estimativa fica no máximo um `QUANTUM` abaixo da taxa que cabe, e só
    cabe quando é ela. Se ela não couber, o refinamento pelos dois pontos chega à taxa que cabe,
    ou conclui que nenhuma taxa de pelo menos um `QUANTUM` caberia."""
    fixa = Decimal(verdadeira)
    vendas_no_escopo = (SIMULADO_DO_JOB - fixa) / TAXA_DO_JOB

    def comissao(taxa: Decimal) -> Decimal:
        return fixa + taxa * vendas_no_escopo

    nenhuma_cabe = comissao(QUANTUM) > ORCAMENTO_DO_JOB
    estimada = percentual_que_cabe(
        TAXA_DO_JOB, SIMULADO_DO_JOB, ORCAMENTO_DO_JOB, parte_fixa=fixa * Decimal(conhecida)
    )
    if estimada is None:
        assert nenhuma_cabe
        return
    assert comissao(estimada + QUANTUM) > ORCAMENTO_DO_JOB
    if comissao(estimada) <= ORCAMENTO_DO_JOB:
        # A estimativa coube, e é ela a sugestão: o fluxo não refina uma taxa que já coube.
        return

    refinada = percentual_refinado(
        [
            TaxaSimulada(TAXA_DO_JOB, SIMULADO_DO_JOB),
            TaxaSimulada(estimada, comissao(estimada)),
        ],
        ORCAMENTO_DO_JOB,
    )
    if nenhuma_cabe:
        assert refinada is None
    else:
        assert refinada is not None
        assert comissao(refinada) <= ORCAMENTO_DO_JOB < comissao(refinada + QUANTUM)


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
        representacao, Decimal("492100"), Decimal("485000"), parte_fixa=Decimal("480312")
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


def test_sonda_todas_as_taxas_sem_detalhamento() -> None:
    representacao = _so_taxas_por_cargo(
        {"cargo": "100", "percentual": Decimal("0.03")},
        {"cargo": "150", "percentual": Decimal("0.05")},
    )

    alternativa = propor_alternativa(
        representacao, SIMULADO_DO_JOB, ORCAMENTO_DO_JOB, parte_fixa=None
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
        parte_fixa=Decimal("1200"),
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
        representacao, Decimal("492100"), Decimal("485000"), parte_fixa=Decimal("480312")
    )

    assert (alternativa.motivo, alternativa.representacao) == (MOTIVO_SEM_MARGEM, None)


def test_regra_sem_taxa_positiva_nao_e_suportada() -> None:
    alternativa = propor_alternativa(
        _representacao(nucleo={"percentual": Decimal("0")}),
        Decimal("492100"),
        Decimal("485000"),
        parte_fixa=Decimal("480312"),
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


# ---- a parte fixa: a comissão das linhas que a regra não alcança ----


def _linha(
    comissao: str,
    *,
    loja: str = "13",
    marca: str = "10",
    cargo: str = "100",
    contribuicoes: dict[str, Decimal] | None = None,
) -> dict[str, object]:
    return {
        "cod_loja": loja,
        "cod_marca": marca,
        "cod_cargo": cargo,
        "comissao_baseline": Decimal(comissao),
        "comissao_simulada": Decimal(comissao),
        "diferenca": Decimal("0"),
        "contribuicoes": contribuicoes or {},
    }


def test_a_parte_fixa_soma_as_linhas_que_a_regra_nao_alcanca() -> None:
    """Fora da vigência, de cada filtro do núcleo e excluída: cada uma conta uma vez."""
    representacao = _representacao(especificacoes=[{**EXCLUSAO, "valores": ["13"]}])
    representacao["nucleo"] = {**NUCLEO, "loja": ["13", "58"]}  # type: ignore[assignment]
    linhas = {
        "2025-07": {"M-ANTES": _linha("1", loja="58")},
        "2025-11": {
            "M-LOJA": _linha("10", loja="14"),
            "M-MARCA": _linha("100", marca="20"),
            "M-CARGO": _linha("1000", cargo="150"),
            "M-EXCLUIDA": _linha("10000", loja="13"),
            "M-ALCANCADA": _linha("100000", loja="58"),
        },
    }

    assert comissao_fora_da_regra(representacao, linhas) == Decimal("11111")


def test_a_linha_que_a_regra_alcanca_nao_e_fixa_mesmo_sem_contribuicao() -> None:
    """A taxa atual dessa linha pode ser a mesma da regra: com outra taxa, ela muda."""
    linhas = {"2025-11": {"M-FORA": _linha("1000", loja="14"), "M-IGUAL": _linha("800")}}

    assert comissao_fora_da_regra(_representacao(), linhas) == Decimal("1000")


def test_a_linha_que_mudou_nao_e_fixa_mesmo_fora_do_escopo() -> None:
    """Um elemento a alcançou, como um bônus com alvo próprio: ela não é o que nenhuma taxa move."""
    linhas = {
        "2025-11": {
            "M-FORA": _linha("1000", loja="14"),
            "M-BONUS": _linha("350", loja="14", contribuicoes={"elem.4": Decimal("350")}),
        }
    }

    assert comissao_fora_da_regra(_representacao(), linhas) == Decimal("1000")


def test_sem_taxa_uniforme_o_cargo_sem_taxa_propria_e_fixo() -> None:
    """O contrato do núcleo manda o cargo sem taxa própria conservar o baseline."""
    representacao = _so_taxas_por_cargo({"cargo": "100", "percentual": Decimal("0.03")})
    representacao["nucleo"]["cargo"] = ["100", "150"]  # type: ignore[index]
    linhas = {"2025-11": {"M-150": _linha("500", cargo="150"), "M-100": _linha("800")}}

    assert comissao_fora_da_regra(representacao, linhas) == Decimal("500")


def test_com_taxa_uniforme_o_cargo_sem_taxa_propria_e_alcancado() -> None:
    representacao = _representacao(
        nucleo={"cargo": ["100", "150"], "taxas_por_cargo": [{"cargo": "100", "percentual": 0}]}
    )
    linhas = {"2025-11": {"M-150": _linha("500", cargo="150")}}

    assert comissao_fora_da_regra(representacao, linhas) == Decimal("0")


def test_filtro_vazio_e_vigencia_ausente_nao_restringem() -> None:
    nucleo = {chave: valor for chave, valor in NUCLEO.items() if chave != "vigencia"}
    representacao = {"nucleo": {**nucleo, "loja": []}, "especificacoes": []}
    linhas = {"2025-07": {"M-14": _linha("1000", loja="14")}}

    assert comissao_fora_da_regra(representacao, linhas) == Decimal("0")


@pytest.mark.parametrize(
    "linhas",
    [
        pytest.param({"2025-11": []}, id="competencia-sem-objeto"),
        pytest.param({"2025-11": {"M-1": "linha"}}, id="linha-sem-objeto"),
        pytest.param({"2025-11": {"M-1": {"cod_loja": "14"}}}, id="sem-comissao"),
    ],
)
def test_detalhamento_fora_da_forma_nao_da_parte_fixa(linhas: dict[str, object]) -> None:
    assert comissao_fora_da_regra(_representacao(), linhas) is None


def test_sem_detalhamento_nao_ha_parte_fixa() -> None:
    assert comissao_fora_da_regra(_representacao(), None) is None
