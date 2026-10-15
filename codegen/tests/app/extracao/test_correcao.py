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
TEXTO = "bônus especial"
RASCUNHO = {"construto_pretendido": "bonus_fixo", "descricao": TEXTO, "trecho": TEXTO}
PERCENTUAL = {"tipo": "definir_nucleo", "campo": "percentual", "valor": Decimal("0.03")}


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
    regra: RepresentacaoRegra, parametros: dict[str, Any], *operacoes: object
) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    corrigida, completos, diagnosticos = aplicar_operacoes_correcao(
        regra, parametros, {"operacoes": list(operacoes)}, PUBLICADAS, texto_correcao=TEXTO
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
    ("campo", "valor"),
    [
        ("loja", ["15"]),
        ("marca", []),
        ("cargo", ["300"]),
        ("vigencia", {"inicio": "2025-12", "fim": "2025-08"}),
        ("percentual", Decimal("-0.1")),
    ],
)
def test_define_campos_e_preserva_incoerencias_sem_corrigir(
    regra: RepresentacaoRegra, parametros: dict[str, Any], campo: str, valor: Any
) -> None:
    esperado: Any = deepcopy(regra.para_contrato())
    esperado["nucleo"][campo] = valor

    corrigida, _, diagnosticos = aplicar(
        regra, parametros, {"tipo": "definir_nucleo", "campo": campo, "valor": valor}
    )

    assert corrigida == esperado
    assert diagnosticos == []


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
        {"ref": "elem.2", "construto": "generico", "descricao": TEXTO},
        {"ref": "elem.3", "construto": "generico", "descricao": "critério 3"},
    ]
    assert diagnosticos == [Rebaixamento("elem.2", "construto_nao_habilitado", "bonus_fixo")]


def test_adiciona_no_final_sem_copiar_campos_do_modelo(regra: RepresentacaoRegra) -> None:
    corrigida, _, diagnosticos = aplicar(
        regra, {}, {"tipo": "adicionar_elemento", "elemento": {**RASCUNHO, "ref": "elem.99"}}
    )

    assert corrigida["especificacoes"] == [
        *regra.para_contrato()["especificacoes"],  # type: ignore[misc]
        {"ref": "elem.4", "construto": "generico", "descricao": TEXTO},
    ]
    assert diagnosticos == [Rebaixamento("elem.4", "construto_nao_habilitado", "bonus_fixo")]


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
        {"tipo": "definir_nucleo", "campo": "percentual", "valor": True},
        {"tipo": "remover_elemento", "ref": "elem.1", "extra": "privado"},
        {"tipo": "remover_parametro", "campo": "desconhecido"},
        {"tipo": "definir_parametro", "campo": "orcamento", "valor": None},
        {"tipo": "definir_parametro", "campo": "competencias", "valor": []},
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
        {"ref": "elem.1", "construto": "generico", "descricao": TEXTO},
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
        {"tipo": "substituir_elemento", "ref": "elem.2", "elemento": RASCUNHO},
        {"tipo": "remover_elemento", "ref": "elem.2"},
    )

    assert [e["descricao"] for e in corrigida["especificacoes"]] == ["critério 1", "critério 3"]
    assert diagnosticos == []


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("orcamento", 600000),
        ("meta_venda", -1),
        ("competencias", ["2025-11"]),
        ("competencias", ["2026-01"]),
    ],
)
def test_define_parametro_e_preserva_demais_inclusive_periodo_fora_das_publicadas(
    regra: RepresentacaoRegra, parametros: dict[str, Any], campo: str, valor: Any
) -> None:
    corrigida, completos, diagnosticos = aplicar(
        regra, parametros, {"tipo": "definir_parametro", "campo": campo, "valor": valor}
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
    operacoes = {"operacoes": [{"tipo": "definir_nucleo", "campo": "loja", "valor": ["15"]}]}
    originais = deepcopy((regra.para_contrato(), parametros, operacoes, PUBLICADAS))

    corrigida, completos, _ = aplicar_operacoes_correcao(regra, parametros, operacoes, PUBLICADAS)
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
        {"operacoes": []},
        {"operacoes": None},
        {"operacoes": {}},
        {"operacoes": [PERCENTUAL], "extra": "privado"},
    ],
)
def test_rejeita_envelope_globalmente_invalido_sem_reter_conteudo(
    regra: RepresentacaoRegra, envelope: object
) -> None:
    with pytest.raises(FalhaExtracaoError) as erro:
        aplicar_operacoes_correcao(regra, {}, envelope, PUBLICADAS)

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
        regra, {}, {"tipo": "adicionar_elemento", "elemento": elemento}
    )

    assert corrigida["especificacoes"][-1] == {
        "ref": "elem.4",
        "construto": "generico",
        "descricao": "convertido: " + TEXTO,
    }
    assert diagnosticos == []


def test_preserva_lastro_da_montagem_existente(regra: RepresentacaoRegra) -> None:
    elemento = {**RASCUNHO, "trecho": "ausente da correção"}

    corrigida, _, diagnosticos = aplicar(
        regra, {}, {"tipo": "adicionar_elemento", "elemento": elemento}
    )

    assert corrigida["especificacoes"][-1]["descricao"] == "Elemento sem lastro verificável"
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
    assert not validador.is_valid({"operacoes": [{"tipo": "desconhecida"}]})
    assert not validador.is_valid({"operacoes": [{**PERCENTUAL, "valor": "3%"}]})
    assert not validador.is_valid({"operacoes": [{**PERCENTUAL, "extra": 1}]})
    assert not validador.is_valid(
        {"operacoes": [{"tipo": "adicionar_elemento", "elemento": {**RASCUNHO, "extra": 1}}]}
    )
