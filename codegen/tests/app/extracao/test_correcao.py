from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from app.extracao.construto import Construto, ContextoExtracao
from app.extracao.correcao import DiagnosticoOperacao, aplicar_operacoes_correcao
from app.extracao.modelos import FalhaExtracaoError, Rebaixamento
from app.extracao.parametros import validar_parametros
from app.extracao.registro import CONSTRUTOS_HABILITADOS
from app.extracao.schema_correcao import schema_operacoes_correcao
from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import ValorRegra

PUBLICADAS = ["2025-08", "2025-09", "2025-11"]
BONUS = "bônus especial"
TEXTO = f"A comissão passa para 3% e entra um {BONUS}."
RASCUNHO = {"construto_pretendido": "construto_futuro", "descricao": BONUS, "trecho": BONUS}


def definir(tipo: str, campo: str, valor: Any, trecho: str) -> dict[str, Any]:
    return {"tipo": tipo, "campo": campo, "valor": {"valor": valor, "trecho": trecho}}


def codigos(campo: str, *itens: tuple[str, str]) -> dict[str, Any]:
    return {
        "tipo": "definir_nucleo",
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
            definir("definir_nucleo", "percentual", Decimal("0.03"), "3%"),
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
    corrigida, _, diagnosticos = aplicar(regra, {}, {"tipo": "remover_elemento", "ref": "elem.2"})

    assert corrigida["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": "critério 1"},
        {"ref": "elem.2", "construto": "generico", "descricao": "critério 3"},
    ]
    assert diagnosticos == []


def test_substitui_na_mesma_posicao_com_montagem_e_rebaixamento(regra: RepresentacaoRegra) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra, {}, {"tipo": "substituir_elemento", "ref": "elem.2", "elemento": RASCUNHO}
    )

    assert corrigida["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": "critério 1"},
        {"ref": "elem.2", "construto": "generico", "descricao": BONUS},
        {"ref": "elem.3", "construto": "generico", "descricao": "critério 3"},
    ]
    assert diagnosticos == [Rebaixamento("elem.2", "construto_nao_habilitado", "construto_futuro")]


@pytest.mark.parametrize(
    ("texto", "elemento"),
    [
        (
            "o limite inferior da faixa é 40 mil",
            {
                "construto_pretendido": "generico",
                "descricao": "critério 2 com limite inferior de 40 mil",
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
        {"tipo": "substituir_elemento", "ref": "elem.2", "elemento": elemento},
        texto=texto,
    )

    assert corrigida == regra.para_contrato()
    assert diagnosticos == [DiagnosticoOperacao(1, "valor_sem_lastro")]


def test_adiciona_no_final_sem_copiar_campos_do_modelo(regra: RepresentacaoRegra) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra, {}, {"tipo": "adicionar_elemento", "elemento": {**RASCUNHO, "ref": "elem.99"}}
    )

    assert corrigida["especificacoes"] == [
        *regra.para_contrato()["especificacoes"],  # type: ignore[misc]
        {"ref": "elem.4", "construto": "generico", "descricao": BONUS},
    ]
    assert diagnosticos == [Rebaixamento("elem.4", "construto_nao_habilitado", "construto_futuro")]


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
    operacao: dict[str, Any] = {"tipo": tipo, "ref": "elem.99"}
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
    corrigida, _, diagnosticos = aplicar(regra, {}, invalida, PERCENTUAL)

    esperado: Any = deepcopy(regra.para_contrato())
    esperado["nucleo"]["percentual"] = Decimal("0.03")
    assert corrigida == esperado
    assert diagnosticos == [DiagnosticoOperacao(1, "operacao_invalida")]


def test_refs_do_lote_se_referem_a_versao_original(regra: RepresentacaoRegra) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {"tipo": "remover_elemento", "ref": "elem.1"},
        {"tipo": "substituir_elemento", "ref": "elem.2", "elemento": RASCUNHO},
        {"tipo": "remover_elemento", "ref": "elem.1"},
    )

    assert corrigida["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": BONUS},
        {"ref": "elem.2", "construto": "generico", "descricao": "critério 3"},
    ]
    assert diagnosticos == [
        DiagnosticoOperacao(3, "referencia_inexistente"),
        Rebaixamento("elem.1", "construto_nao_habilitado", "construto_futuro"),
    ]


def test_descarta_rebaixamento_de_elemento_removido_no_mesmo_lote(
    regra: RepresentacaoRegra,
) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra,
        {},
        {"tipo": "substituir_elemento", "ref": "elem.2", "elemento": RASCUNHO},
        {"tipo": "remover_elemento", "ref": "elem.2"},
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
        regra, parametros, {"tipo": "remover_parametro", "campo": campo}
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
    def converter(elemento: dict[str, Any], _: ContextoExtracao) -> dict[str, ValorRegra]:
        return {"descricao": "convertido: " + elemento["descricao"]}

    monkeypatch.setitem(
        CONSTRUTOS_HABILITADOS,
        "generico",
        Construto(propriedades={}, obrigatorios=(), instrucoes="Teste", converter=converter),
    )
    elemento = {**RASCUNHO, "construto_pretendido": "generico"}

    corrigida, _, diagnosticos = aplicar(
        regra, {}, {"tipo": "adicionar_elemento", "elemento": elemento}
    )

    assert corrigida["especificacoes"][-1] == {
        "ref": "elem.4",
        "construto": "generico",
        "descricao": "convertido: " + BONUS,
    }
    assert diagnosticos == []


def test_preserva_lastro_da_montagem_existente(regra: RepresentacaoRegra) -> None:
    elemento = {**RASCUNHO, "trecho": "ausente da correção"}

    corrigida, _, diagnosticos = aplicar(
        regra, {}, {"tipo": "adicionar_elemento", "elemento": elemento}
    )

    assert corrigida["especificacoes"][-1]["descricao"] == "Elemento sem lastro verificável"
    assert diagnosticos == [Rebaixamento("elem.4", "valor_sem_lastro", "construto_futuro")]


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
