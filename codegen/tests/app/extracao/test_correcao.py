from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from app.extracao.correcao import DiagnosticoOperacao, aplicar_operacoes_correcao
from app.extracao.modelos import FalhaExtracaoError, Rebaixamento
from app.extracao.parametros import validar_parametros
from app.extracao.registro import CONSTRUTOS_HABILITADOS, Construto
from app.extracao.schema_correcao import schema_operacoes_correcao
from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import ValorRegra

PUBLICADAS = ["2025-08", "2025-09", "2025-11"]
BONUS = "bônus especial"
TEXTO = f"A comissão passa para 3% e entra um {BONUS}."
RASCUNHO = {"construto_pretendido": "bonus_fixo", "descricao": BONUS, "trecho": BONUS}


def definir(tipo: str, campo: str, valor: Any, trecho: str) -> dict[str, Any]:
    return {
        "tipo": tipo,
        "trecho": trecho,
        "campo": campo,
        "valor": {"valor": valor, "trecho": trecho},
    }


def codigos(campo: str, *itens: tuple[str, str]) -> dict[str, Any]:
    return {
        "tipo": "definir_nucleo",
        "trecho": itens[0][1] if itens else "vale para todas as marcas",
        "campo": campo,
        "valor": [{"valor": valor, "trecho": trecho} for valor, trecho in itens],
    }


PERCENTUAL = definir("definir_nucleo", "percentual", Decimal("0.03"), "3%")


@pytest.fixture
def regra() -> RepresentacaoRegra:
    return RepresentacaoRegra.model_validate(
        {
            "nucleo": {
                "percentual": Decimal("0.025"),
                "loja": ["13"],
                "marca": ["10"],
                "cargo": ["100"],
                "vigencia": {"inicio": "2025-08", "fim": "2025-12"},
            },
            "especificacoes": [
                {"ref": f"elem.{i}", "construto": "generico", "descricao": f"critério {i}"}
                for i in (1, 2, 3)
            ],
        }
    )


@pytest.fixture
def parametros() -> dict[str, Any]:
    return {"orcamento": 500000, "meta_venda": 12000000, "competencias": PUBLICADAS[:2]}


def aplicar(
    regra: RepresentacaoRegra, parametros: dict[str, Any], *operacoes: object, texto: str = TEXTO
) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    corrigida, completos, diagnosticos = aplicar_operacoes_correcao(
        regra, parametros, {"operacoes": list(operacoes)}, PUBLICADAS, texto_correcao=texto
    )
    return corrigida.para_contrato(), completos, diagnosticos


def test_altera_so_percentual_e_preserva_todo_o_resto(
    regra: RepresentacaoRegra, parametros: dict[str, Any]
) -> None:
    esperado = deepcopy(regra.para_contrato())
    esperado["nucleo"]["percentual"] = Decimal("0.03")  # type: ignore[index]

    corrigida, completos, diagnosticos = aplicar(regra, parametros, PERCENTUAL)

    assert corrigida == esperado
    assert completos == parametros
    assert diagnosticos == []


@pytest.mark.parametrize(
    ("operacao", "texto", "campo", "valor"),
    [
        (codigos("loja", ("15", "loja 15")), "só na loja 15", "loja", ["15"]),
        (codigos("marca"), "vale para todas as marcas", "marca", []),
        (codigos("cargo", ("300", "cargo 300")), "só o cargo 300", "cargo", ["300"]),
        (
            definir(
                "definir_nucleo",
                "vigencia",
                {"inicio": "2025-12", "fim": "2025-08"},
                "de dezembro a agosto",
            ),
            "vale de dezembro a agosto",
            "vigencia",
            {"inicio": "2025-12", "fim": "2025-08"},
        ),
        (
            definir("definir_nucleo", "percentual", Decimal("-0.1"), "-10%"),
            "a comissão é de -10%",
            "percentual",
            Decimal("-0.1"),
        ),
    ],
)
def test_define_campos_e_preserva_incoerencias_sem_corrigir(
    regra: RepresentacaoRegra,
    parametros: dict[str, Any],
    operacao: dict[str, Any],
    texto: str,
    campo: str,
    valor: Any,
) -> None:
    esperado: Any = deepcopy(regra.para_contrato())
    esperado["nucleo"][campo] = valor

    corrigida, _, diagnosticos = aplicar(regra, parametros, operacao, texto=texto)

    assert corrigida == esperado
    assert diagnosticos == []


@pytest.mark.parametrize(
    ("operacao", "texto", "campo", "valor"),
    [
        (codigos("loja", ("LOJA-15", "LOJA-15")), "só na LOJA-15", "loja", ["15"]),
        (
            codigos("marca", ("AZUL", "marca azul"), ("30", "código 30")),
            "só a marca azul, código 30",
            "marca",
            ["30"],
        ),
    ],
)
def test_codigo_do_nucleo_e_resolvido_no_vocabulario(
    regra: RepresentacaoRegra, operacao: dict[str, Any], texto: str, campo: str, valor: list[str]
) -> None:
    corrigida, _, diagnosticos = aplicar(regra, {}, operacao, texto=texto)

    assert corrigida["nucleo"][campo] == valor
    assert diagnosticos == []


@pytest.mark.parametrize(
    ("operacao", "texto", "motivo"),
    [
        (
            definir("definir_nucleo", "percentual", Decimal("0.05"), "a meta"),
            "tira a meta",
            "valor_sem_lastro",
        ),
        (
            definir("definir_nucleo", "percentual", Decimal("0.05"), "3%"),
            "passa para 3%",
            "valor_sem_lastro",
        ),
        (
            definir("definir_nucleo", "percentual", Decimal("0.03"), "3%")
            | {"trecho": "passa para três"},
            "passa para três",
            "valor_sem_lastro",
        ),
        (
            codigos("loja", ("Centro", "loja do Centro")),
            "inclui a loja do Centro",
            "codigo_fora_do_vocabulario",
        ),
        (
            codigos("loja", ("15", "lojas 15"), ("Centro", "Centro")),
            "só nas lojas 15 e Centro",
            "codigo_fora_do_vocabulario",
        ),
        (
            definir(
                "definir_nucleo",
                "vigencia",
                {"inicio": "2024-11", "fim": "2024-11"},
                "só em novembro",
            ),
            "vale só em novembro",
            "valor_sem_lastro",
        ),
        (
            definir(
                "definir_nucleo",
                "vigencia",
                {"inicio": "2025-12", "fim": "2025-12"},
                "no fim do ano",
            ),
            "vale no fim do ano",
            "periodo_nao_resolvido",
        ),
        (
            definir("definir_parametro", "orcamento", 600000, "R$ 500 mil"),
            "orçamento de R$ 500 mil",
            "valor_sem_lastro",
        ),
        (
            definir("definir_parametro", "competencias", ["2024-11"], "só novembro"),
            "simula só novembro",
            "valor_sem_lastro",
        ),
        (
            definir("definir_parametro", "competencias", ["2025-12"], "no fim do ano"),
            "simula no fim do ano",
            "periodo_nao_resolvido",
        ),
    ],
)
def test_valor_sem_lastro_no_texto_da_correcao_mantem_o_anterior(
    regra: RepresentacaoRegra,
    parametros: dict[str, Any],
    operacao: dict[str, Any],
    texto: str,
    motivo: str,
) -> None:
    corrigida, completos, diagnosticos = aplicar(regra, parametros, operacao, texto=texto)

    assert corrigida == regra.para_contrato()
    assert completos == parametros
    assert diagnosticos == [DiagnosticoOperacao(1, motivo)]  # type: ignore[arg-type]


def test_remove_so_o_elemento_e_renumera_na_ordem(regra: RepresentacaoRegra) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {"tipo": "remover_elemento", "ref": "elem.2", "trecho": "remova critério 2"},
        texto="remova critério 2",
    )

    assert corrigida["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": "critério 1"},
        {"ref": "elem.2", "construto": "generico", "descricao": "critério 3"},
    ]
    assert diagnosticos == []


def test_substitui_na_mesma_posicao_com_montagem_e_rebaixamento(regra: RepresentacaoRegra) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {"tipo": "substituir_elemento", "ref": "elem.2", "trecho": BONUS, "elemento": RASCUNHO},
    )

    assert corrigida["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": "critério 1"},
        {"ref": "elem.2", "construto": "generico", "descricao": BONUS},
        {"ref": "elem.3", "construto": "generico", "descricao": "critério 3"},
    ]
    assert diagnosticos == [Rebaixamento("elem.2", "construto_nao_habilitado", "bonus_fixo")]


@pytest.mark.parametrize(
    ("texto", "elemento"),
    [
        (
            "o limite inferior da faixa é 40 mil",
            {
                "construto_pretendido": "generico",
                "descricao": "critério 2 com limite inferior de 90 mil",
                "trecho": "o limite inferior da faixa é 40 mil",
            },
        ),
        (
            "Está certo assim, pode seguir.",
            {"construto_pretendido": "generico", "descricao": "critério 2", "trecho": "critério 2"},
        ),
    ],
)
def test_substituicao_sem_lastro_mantem_o_elemento_atual(
    regra: RepresentacaoRegra, texto: str, elemento: dict[str, str]
) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {"tipo": "substituir_elemento", "ref": "elem.2", "trecho": texto, "elemento": elemento},
        texto=texto,
    )

    assert corrigida == regra.para_contrato()
    assert diagnosticos == [DiagnosticoOperacao(1, "valor_sem_lastro")]


def test_adiciona_no_final_sem_copiar_campos_do_modelo(regra: RepresentacaoRegra) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {"tipo": "adicionar_elemento", "trecho": BONUS, "elemento": {**RASCUNHO, "ref": "elem.99"}},
    )

    assert corrigida["especificacoes"] == [
        *regra.para_contrato()["especificacoes"],  # type: ignore[misc]
        {"ref": "elem.4", "construto": "generico", "descricao": BONUS},
    ]
    assert diagnosticos == [Rebaixamento("elem.4", "construto_nao_habilitado", "bonus_fixo")]


def test_lista_vazia_devolve_a_regra_e_os_parametros_atuais(
    regra: RepresentacaoRegra, parametros: dict[str, Any]
) -> None:
    corrigida, completos, diagnosticos = aplicar(regra, parametros)

    assert corrigida == regra.para_contrato()
    assert completos == parametros
    assert diagnosticos == []


@pytest.mark.parametrize("tipo", ["remover_elemento", "substituir_elemento"])
def test_ref_inexistente_preserva_regra_e_registra_diagnostico_local(
    regra: RepresentacaoRegra, tipo: str
) -> None:
    operacao: dict[str, Any] = {"tipo": tipo, "ref": "elem.99", "trecho": BONUS}
    if tipo == "substituir_elemento":
        operacao["elemento"] = RASCUNHO

    corrigida, _, diagnosticos = aplicar(regra, {}, operacao)

    assert corrigida == regra.para_contrato()
    assert diagnosticos == [DiagnosticoOperacao(1, "referencia_inexistente")]
    assert not hasattr(diagnosticos[0], "para_contrato")


@pytest.mark.parametrize(
    "invalida",
    [
        {"tipo": "desconhecida"},
        {"tipo": "definir_nucleo", "campo": "matricula", "valor": "1"},
        {"tipo": "definir_nucleo", "campo": "percentual", "valor": None},
        definir("definir_nucleo", "percentual", True, "3%"),
        {"tipo": "definir_nucleo", "campo": "percentual", "valor": Decimal("0.03")},
        {"tipo": "definir_parametro", "campo": "orcamento", "valor": 600000},
        {"tipo": "remover_elemento", "ref": "elem.1", "extra": "privado"},
        {"tipo": "remover_parametro", "campo": "desconhecido"},
        {"tipo": "definir_parametro", "campo": "orcamento", "valor": None},
        definir("definir_parametro", "competencias", [], "simula"),
        {"tipo": "adicionar_elemento", "elemento": {}},
        None,
        "privado",
    ],
)
def test_ignora_operacao_invalida_sem_perder_as_validas(
    regra: RepresentacaoRegra, invalida: object
) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {**invalida, "trecho": "3%"} if isinstance(invalida, dict) else invalida,
        PERCENTUAL,
    )

    esperado: Any = deepcopy(regra.para_contrato())
    esperado["nucleo"]["percentual"] = Decimal("0.03")
    assert corrigida == esperado
    assert diagnosticos == [DiagnosticoOperacao(1, "operacao_invalida")]


def test_refs_do_lote_se_referem_a_versao_original(regra: RepresentacaoRegra) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {"tipo": "remover_elemento", "ref": "elem.1", "trecho": "remova critério 1"},
        {"tipo": "substituir_elemento", "ref": "elem.2", "trecho": BONUS, "elemento": RASCUNHO},
        {"tipo": "remover_elemento", "ref": "elem.1", "trecho": "remova critério 1"},
        texto="remova critério 1 e faça bônus especial",
    )

    assert corrigida["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": BONUS},
        {"ref": "elem.2", "construto": "generico", "descricao": "critério 3"},
    ]
    assert diagnosticos == [
        DiagnosticoOperacao(3, "referencia_inexistente"),
        Rebaixamento("elem.1", "construto_nao_habilitado", "bonus_fixo"),
    ]


def test_descarta_rebaixamento_de_elemento_removido_no_mesmo_lote(
    regra: RepresentacaoRegra,
) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {"tipo": "substituir_elemento", "ref": "elem.2", "trecho": BONUS, "elemento": RASCUNHO},
        {"tipo": "remover_elemento", "ref": "elem.2", "trecho": "remova critério 2"},
        texto="bônus especial e remova critério 2",
    )

    assert [e["descricao"] for e in corrigida["especificacoes"]] == ["critério 1", "critério 3"]
    assert diagnosticos == []


@pytest.mark.parametrize(
    ("campo", "valor", "texto"),
    [
        ("orcamento", 600000, "orçamento de R$ 600 mil"),
        ("meta_venda", -1, "meta de -1"),
        ("competencias", ["2025-11"], "simula só novembro"),
        ("competencias", ["2026-01"], "simula janeiro de 2026"),
    ],
)
def test_define_parametro_e_preserva_demais_inclusive_periodo_fora_das_publicadas(
    regra: RepresentacaoRegra, parametros: dict[str, Any], campo: str, valor: Any, texto: str
) -> None:
    corrigida, completos, diagnosticos = aplicar(
        regra, parametros, definir("definir_parametro", campo, valor, texto), texto=texto
    )

    assert completos == {**parametros, campo: valor}
    assert validar_parametros(completos) == completos
    assert RepresentacaoRegra.model_validate(corrigida).para_contrato() == regra.para_contrato()
    assert diagnosticos == []


@pytest.mark.parametrize("campo", ["meta_venda", "orcamento", "competencias"])
def test_remove_parametro_por_ausencia_sem_null(
    regra: RepresentacaoRegra, parametros: dict[str, Any], campo: str
) -> None:
    _, completos, diagnosticos = aplicar(
        regra,
        parametros,
        {"tipo": "remover_parametro", "campo": campo, "trecho": "remova"},
        texto=f"remova {campo}",
    )

    assert completos == {k: v for k, v in parametros.items() if k != campo}
    assert diagnosticos == []


def test_argumentos_e_resultado_nao_compartilham_objetos_mutaveis(
    regra: RepresentacaoRegra, parametros: dict[str, Any]
) -> None:
    operacoes = {"operacoes": [codigos("loja", ("15", "loja 15"))]}
    originais = deepcopy((regra.para_contrato(), parametros, operacoes, PUBLICADAS))

    corrigida, completos, _ = aplicar_operacoes_correcao(
        regra, parametros, operacoes, PUBLICADAS, texto_correcao="só na loja 15"
    )
    assert corrigida.para_contrato()["nucleo"]["loja"] == ["15"]  # type: ignore[index]
    saida: Any = corrigida.root
    saida["nucleo"]["loja"].append("99")
    saida["especificacoes"][0]["descricao"] = "alterado"
    periodo: Any = completos["competencias"]
    periodo.append("2025-12")

    assert (regra.para_contrato(), parametros, operacoes, PUBLICADAS) == originais


@pytest.mark.parametrize(
    "envelope",
    [
        None,
        "",
        [],
        {},
        {"operacoes": None},
        {"operacoes": {}},
        {"operacoes": [PERCENTUAL], "extra": "privado"},
    ],
)
def test_rejeita_envelope_globalmente_invalido_sem_reter_conteudo(
    regra: RepresentacaoRegra, envelope: object
) -> None:
    with pytest.raises(FalhaExtracaoError) as erro:
        aplicar_operacoes_correcao(regra, {}, envelope, PUBLICADAS, texto_correcao=TEXTO)

    assert str(erro.value) == "Envelope de correção inválido"
    assert erro.value.etapa == "extracao_parametros"
    assert erro.value.__context__ is None


def test_reutiliza_conversor_habilitado(
    regra: RepresentacaoRegra, monkeypatch: pytest.MonkeyPatch
) -> None:
    def converter(elemento: dict[str, Any]) -> dict[str, ValorRegra]:
        return {"descricao": "convertido: " + elemento["descricao"]}

    monkeypatch.setitem(
        CONSTRUTOS_HABILITADOS,
        "generico",
        Construto(propriedades={}, obrigatorios=(), instrucoes="Teste", converter=converter),
    )
    elemento = {**RASCUNHO, "construto_pretendido": "generico"}

    corrigida, _, diagnosticos = aplicar(
        regra, {}, {"tipo": "adicionar_elemento", "trecho": BONUS, "elemento": elemento}
    )

    assert corrigida["especificacoes"][-1] == {
        "ref": "elem.4",
        "construto": "generico",
        "descricao": "convertido: " + BONUS,
    }
    assert diagnosticos == []


def test_rebaixa_elemento_sem_lastro_usando_trecho_da_operacao(
    regra: RepresentacaoRegra,
) -> None:
    elemento = {**RASCUNHO, "trecho": "ausente da correção"}

    corrigida, _, diagnosticos = aplicar(
        regra, {}, {"tipo": "adicionar_elemento", "trecho": BONUS, "elemento": elemento}
    )

    assert corrigida["especificacoes"][-1]["descricao"] == BONUS
    assert diagnosticos == [Rebaixamento("elem.4", "valor_sem_lastro", "bonus_fixo")]


def test_schema_fecha_envelope_e_exatamente_seis_operacoes() -> None:
    schema = schema_operacoes_correcao()

    assert schema["additionalProperties"] is False
    variantes = schema["properties"]["operacoes"]["items"]["anyOf"]
    assert {v["properties"]["tipo"]["const"] for v in variantes} == {
        "definir_nucleo",
        "substituir_elemento",
        "remover_elemento",
        "adicionar_elemento",
        "definir_parametro",
        "remover_parametro",
    }
    assert len(variantes) == 6
    assert all(v["additionalProperties"] is False for v in variantes)
    Draft202012Validator.check_schema(schema)
    validador = Draft202012Validator(schema)
    assert validador.is_valid({"operacoes": [PERCENTUAL]})
    assert validador.is_valid({"operacoes": []})
    assert not validador.is_valid({"operacoes": [{**PERCENTUAL, "valor": Decimal("0.03")}]})
    assert not validador.is_valid({"operacoes": [{"tipo": "desconhecida"}]})
    assert not validador.is_valid(
        {"operacoes": [definir("definir_nucleo", "percentual", "3%", "3%")]}
    )
    assert not validador.is_valid({"operacoes": [{**PERCENTUAL, "extra": 1}]})
    assert not validador.is_valid(
        {"operacoes": [{"tipo": "adicionar_elemento", "elemento": {**RASCUNHO, "extra": 1}}]}
    )


@pytest.mark.parametrize("trecho", [None, "", "  ", "Trecho INVENTADO"])
@pytest.mark.parametrize(
    "operacao",
    [
        PERCENTUAL,
        {"tipo": "remover_elemento", "ref": "elem.1"},
        {"tipo": "substituir_elemento", "ref": "elem.1", "elemento": RASCUNHO},
        {"tipo": "adicionar_elemento", "elemento": RASCUNHO},
        {"tipo": "remover_parametro", "campo": "orcamento"},
        definir("definir_parametro", "orcamento", 600000, "R$ 600 mil"),
    ],
)
def test_operacao_sem_trecho_literal_nao_altera_nada(
    regra: RepresentacaoRegra,
    parametros: dict[str, Any],
    operacao: dict[str, Any],
    trecho: str | None,
) -> None:
    candidata = {**operacao}
    if trecho is None:
        candidata.pop("trecho", None)
    else:
        candidata["trecho"] = trecho

    corrigida, completos, diagnosticos = aplicar(regra, parametros, candidata)

    assert corrigida == regra.para_contrato()
    assert completos == parametros
    assert diagnosticos == [DiagnosticoOperacao(1, "operacao_sem_trecho")]


def test_uma_operacao_sem_trecho_nao_impede_as_outras_validas(
    regra: RepresentacaoRegra,
) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {"tipo": "remover_elemento", "ref": "elem.1"},
        PERCENTUAL,
    )

    assert len(corrigida["especificacoes"]) == 3
    assert corrigida["nucleo"]["percentual"] == Decimal("0.03")
    assert diagnosticos == [DiagnosticoOperacao(1, "operacao_sem_trecho")]


def test_valor_do_historico_nao_justifica_parametro_novo(
    regra: RepresentacaoRegra, parametros: dict[str, Any]
) -> None:
    trecho = "mantenha a regra"
    corrigida, completos, diagnosticos = aplicar(
        regra,
        parametros,
        definir("definir_parametro", "orcamento", 700000, "R$ 700 mil") | {"trecho": trecho},
        texto="por favor, mantenha a regra",
    )

    assert corrigida == regra.para_contrato()
    assert completos == parametros
    assert diagnosticos == [DiagnosticoOperacao(1, "valor_sem_lastro")]


def test_substituto_com_valor_nao_sustentado_preserva_o_elemento_inteiro(
    regra: RepresentacaoRegra,
) -> None:
    texto = "Troque a faixa anterior pela faixa de R$ 40 mil."
    elemento = {
        "construto_pretendido": "faixa_valor",
        "descricao": "faixa de R$ 90 mil",
        "trecho": "faixa de R$ 40 mil",
    }

    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {
            "tipo": "substituir_elemento",
            "ref": "elem.2",
            "trecho": "faixa de R$ 40 mil",
            "elemento": elemento,
        },
        texto=texto,
    )

    assert corrigida == regra.para_contrato()
    assert diagnosticos == [DiagnosticoOperacao(1, "valor_sem_lastro")]


def test_elemento_adicionado_com_numero_inventado_nunca_insere_esse_numero(
    regra: RepresentacaoRegra,
) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {
            "tipo": "adicionar_elemento",
            "trecho": BONUS,
            "elemento": {"descricao": "bônus de 700 mil", "construto_pretendido": "generico"},
        },
    )

    assert corrigida["especificacoes"][-1] == {
        "ref": "elem.4",
        "construto": "generico",
        "descricao": BONUS,
    }
    assert diagnosticos == [Rebaixamento("elem.4", "valor_sem_lastro", "generico")]


DESCRICAO_BONUS = "bônus de R$ 500 para quem vender acima de R$ 10.000 no mês"
CORRECAO_BONUS = "o bônus passa para 600 reais"


def regra_com_bonus() -> RepresentacaoRegra:
    return RepresentacaoRegra.model_validate(
        {
            "nucleo": {"percentual": Decimal("0.025")},
            "especificacoes": [
                {"ref": "elem.1", "construto": "generico", "descricao": DESCRICAO_BONUS},
                {"ref": "elem.2", "construto": "generico", "descricao": "teto de R$ 900"},
            ],
        }
    )


def substituir_bonus(descricao: str, texto: str = CORRECAO_BONUS) -> dict[str, Any]:
    return {
        "tipo": "substituir_elemento",
        "ref": "elem.1",
        "trecho": texto,
        "elemento": {
            "construto_pretendido": "generico",
            "descricao": descricao,
            "trecho": texto,
        },
    }


def test_correcao_parcial_do_bonus_preserva_o_limite_da_regra_atual() -> None:
    regra = regra_com_bonus()
    descricao = DESCRICAO_BONUS.replace("500", "600")
    esperado: Any = deepcopy(regra.para_contrato())
    esperado["especificacoes"][0]["descricao"] = descricao

    corrigida, _, diagnosticos = aplicar(
        regra, {}, substituir_bonus(descricao), texto=CORRECAO_BONUS
    )

    assert corrigida == esperado
    assert diagnosticos == [Rebaixamento("elem.1", "construto_nao_habilitado", "generico")]


@pytest.mark.parametrize("texto", [CORRECAO_BONUS, "Está certo assim, pode seguir."])
def test_bonus_com_valor_inventado_nao_perde_condicao_nem_vira_confirmacao(texto: str) -> None:
    regra = regra_com_bonus()
    descricao = DESCRICAO_BONUS.replace("500", "700")

    corrigida, _, diagnosticos = aplicar(regra, {}, substituir_bonus(descricao, texto), texto=texto)

    assert corrigida == regra.para_contrato()
    assert diagnosticos == [DiagnosticoOperacao(1, "valor_sem_lastro")]


def test_valor_de_outro_elemento_nao_e_lastro_para_o_bonus() -> None:
    regra = regra_com_bonus()
    descricao = DESCRICAO_BONUS.replace("500", "900")

    corrigida, _, diagnosticos = aplicar(
        regra, {}, substituir_bonus(descricao), texto=CORRECAO_BONUS
    )

    assert corrigida == regra.para_contrato()
    assert diagnosticos == [DiagnosticoOperacao(1, "valor_sem_lastro")]


def test_adicao_nao_herda_numeros_dos_elementos_atuais() -> None:
    regra = regra_com_bonus()
    operacao = substituir_bonus(DESCRICAO_BONUS)
    operacao["tipo"] = "adicionar_elemento"
    operacao.pop("ref")

    corrigida, _, diagnosticos = aplicar(regra, {}, operacao, texto=CORRECAO_BONUS)

    assert corrigida["especificacoes"][:-1] == regra.para_contrato()["especificacoes"]
    assert corrigida["especificacoes"][-1]["descricao"] == CORRECAO_BONUS
    assert diagnosticos == [Rebaixamento("elem.3", "valor_sem_lastro", "generico")]


def test_substituicao_rejeitada_preserva_a_alteracao_valida_anterior_do_lote() -> None:
    regra = regra_com_bonus()
    descricao = DESCRICAO_BONUS.replace("500", "600")
    esperado: Any = deepcopy(regra.para_contrato())
    esperado["especificacoes"][0]["descricao"] = descricao

    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        substituir_bonus(descricao),
        substituir_bonus(descricao.replace("600", "700")),
        texto=CORRECAO_BONUS,
    )

    assert corrigida == esperado
    assert diagnosticos == [
        DiagnosticoOperacao(2, "valor_sem_lastro"),
        Rebaixamento("elem.1", "construto_nao_habilitado", "generico"),
    ]


def test_trecho_do_elemento_ainda_precisa_existir_na_correcao_atual() -> None:
    regra = regra_com_bonus()
    operacao = substituir_bonus(DESCRICAO_BONUS)
    operacao["elemento"]["trecho"] = DESCRICAO_BONUS

    corrigida, _, diagnosticos = aplicar(regra, {}, operacao, texto=CORRECAO_BONUS)

    assert corrigida == regra.para_contrato()
    assert diagnosticos == [DiagnosticoOperacao(1, "valor_sem_lastro")]


@pytest.mark.parametrize("limiar", [10000, 11000])
def test_campo_numerico_preservado_exige_mesmo_campo_do_mesmo_construto(
    monkeypatch: pytest.MonkeyPatch,
    limiar: int,
) -> None:
    def converter(elemento: dict[str, Any]) -> dict[str, ValorRegra]:
        return {
            chave: elemento[chave]
            for chave in (
                "metrica",
                "escopo_agregacao",
                "operador",
                "limiar",
            )
        }

    monkeypatch.setitem(
        CONSTRUTOS_HABILITADOS,
        "condicao_limiar",
        Construto(
            propriedades={
                "metrica": {"type": "string"},
                "escopo_agregacao": {"type": "string"},
                "operador": {"type": "string"},
                "limiar": {"type": "number"},
            },
            obrigatorios=("metrica", "escopo_agregacao", "operador", "limiar"),
            instrucoes="Teste",
            converter=converter,
        ),
    )
    original = {
        "ref": "elem.1",
        "construto": "condicao_limiar",
        "metrica": "venda_total",
        "escopo_agregacao": "loja",
        "operador": ">=",
        "limiar": 10000,
    }
    regra = RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": [original]})
    texto = "a condição passa a valer por marca"
    operacao = {
        "tipo": "substituir_elemento",
        "ref": "elem.1",
        "trecho": texto,
        "elemento": {
            "construto_pretendido": "condicao_limiar",
            "descricao": "condição por marca",
            "trecho": texto,
            "metrica": "venda_total",
            "escopo_agregacao": "marca",
            "operador": ">=",
            "limiar": {"valor": limiar, "trecho": texto},
        },
    }

    corrigida, _, diagnosticos = aplicar(regra, {}, operacao, texto=texto)

    if limiar == 10000:
        assert corrigida["especificacoes"] == [{**original, "escopo_agregacao": "marca"}]
        assert diagnosticos == []
    else:
        assert corrigida == regra.para_contrato()
        assert diagnosticos == [DiagnosticoOperacao(1, "valor_sem_lastro")]
