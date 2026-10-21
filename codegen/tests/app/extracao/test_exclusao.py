import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.extracao.construto import ContextoExtracao
from app.extracao.construtos.exclusao import converter
from app.extracao.modelos import ElementoRebaixadoError, ResultadoExtracao
from app.extracao.motor import extrair_regra
from tests.app.extracao.test_motor import METADADOS, modelo_falso

ARQUIVO = Path(__file__).resolve().parents[2] / "fixtures" / "corpus_exclusao.json"
CASOS: list[dict[str, Any]] = json.loads(ARQUIVO.read_text(encoding="utf-8"), parse_float=Decimal)
PUBLICADAS = ["2025-11"]


def lastro(valor: str, trecho: str) -> dict[str, str]:
    return {"valor": valor, "trecho": trecho}


def rascunho(trecho: str, dimensao: str, valores: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "construto_pretendido": "exclusao",
        "descricao": trecho,
        "trecho": trecho,
        "dimensao": dimensao,
        "valores": valores,
    }


async def extrair(
    elementos: list[dict[str, Any]], texto: str, competencias: Sequence[str] = PUBLICADAS
) -> ResultadoExtracao:
    modelo = modelo_falso({"nucleo": {}, "elementos": elementos, "parametros": {}})
    return await extrair_regra(texto, competencias, modelo=modelo, metadados_modelo=METADADOS)


def especificacoes(resultado: ResultadoExtracao) -> list[Any]:
    regra: Any = resultado.representacao.para_contrato()
    return list(regra["especificacoes"])


@pytest.mark.parametrize("caso", CASOS, ids=[c["id"] for c in CASOS])
async def test_caso_do_corpus_pelo_motor_com_modelo_falso(caso: dict[str, Any]) -> None:
    modelo = modelo_falso(caso["rascunho"])

    resultado = await extrair_regra(
        caso["texto"], caso["competencias_publicadas"], modelo=modelo, metadados_modelo=METADADOS
    )

    assert resultado.representacao.para_contrato() == caso["representacao_esperada"]
    assert resultado.parametros == caso["parametros_esperados"]
    assert [r.motivo for r in resultado.rebaixamentos] == (
        [caso["motivo_esperado"]] if caso["motivo_esperado"] else []
    )


async def test_nomes_do_mesmo_cargo_viram_um_unico_codigo() -> None:
    texto = "Exceto os gerentes"
    valores = [lastro("GERENTE DE LOJA", "gerentes"), lastro("GERENTE QUIOSQUE", "gerentes")]

    resultado = await extrair([rascunho(texto, "cargo", valores)], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}
    ]


async def test_matricula_com_numero_de_loja_nao_vira_exclusao_de_loja() -> None:
    texto = "Comissão de 2%, exceto a matrícula 13"
    trecho = "exceto a matrícula 13"

    resultado = await extrair([rascunho(trecho, "loja", [lastro("13", "13")])], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": trecho}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


async def test_dimensao_matricula_nao_cabe_no_rascunho_e_vira_generico() -> None:
    texto = "Exceto a matrícula MATRIC-422"

    resultado = await extrair(
        [rascunho(texto, "matricula", [lastro("MATRIC-422", "MATRIC-422")])], texto
    )

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": texto}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


@pytest.mark.parametrize(
    "alteracao",
    [
        {"valores": []},
        {"valores": ["13"]},
        {"dimensao": None},
        {"valores": None},
    ],
    ids=["valores_vazios", "valor_sem_trecho", "sem_dimensao", "sem_valores"],
)
async def test_rascunho_incompleto_vira_generico(alteracao: dict[str, Any]) -> None:
    texto = "Para todas as lojas, exceto a 13"
    elemento = rascunho("exceto a 13", "loja", [lastro("13", "13")])
    elemento.update(alteracao)
    elemento = {chave: valor for chave, valor in elemento.items() if valor is not None}

    resultado = await extrair([elemento], texto)

    assert [e["construto"] for e in especificacoes(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


async def test_codigo_sem_lastro_rebaixa_a_exclusao_inteira() -> None:
    texto = "Para todas as lojas, exceto a 13"
    valores = [lastro("13", "13"), lastro("58", "58")]

    resultado = await extrair([rascunho("exceto a 13", "loja", valores)], texto)

    assert especificacoes(resultado) == [
        {
            "ref": "elem.1",
            "construto": "generico",
            "descricao": "exceto a 13",
            "campos": {"dimensao": "loja", "valores": ["13"]},
        }
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["valor_sem_lastro"]


async def test_cargo_ambiguo_rebaixa_sem_escolher_um_codigo() -> None:
    texto = "Exceto os vendedores"

    resultado = await extrair([rascunho(texto, "cargo", [lastro("vendedor", "vendedores")])], texto)

    assert especificacoes(resultado) == [
        {
            "ref": "elem.1",
            "construto": "generico",
            "descricao": texto,
            "campos": {"dimensao": "cargo"},
        }
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


@pytest.mark.parametrize(
    "texto",
    [
        "Bônus de R$ 500 para todos, exceto os gerentes (150)",
        "Bônus de 500 reais para todos, exceto os gerentes (150)",
        "Acréscimo de 1% para todos, exceto os gerentes (150)",
        "Acréscimo de um por cento para todos, exceto os gerentes (150)",
    ],
)
async def test_excecao_junto_de_um_efeito_proprio_vira_generico(texto: str) -> None:
    resultado = await extrair([rascunho(texto, "cargo", [lastro("150", "gerentes (150)")])], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": texto}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


def test_rebaixamento_nao_carrega_o_texto_do_usuario() -> None:
    texto = "Para todas as lojas, exceto a 13 e a LOJA_PRIVADA"
    elemento = rascunho(
        "exceto a 13 e a LOJA_PRIVADA",
        "loja",
        [lastro("13", "13"), lastro("LOJA_PRIVADA", "LOJA_PRIVADA")],
    )

    with pytest.raises(ElementoRebaixadoError) as erro:
        converter(elemento, ContextoExtracao(texto, PUBLICADAS))

    assert erro.value.args == ("codigo_fora_do_vocabulario",)
    assert erro.value.campos == {"dimensao": "loja", "valores": ["13"]}
    assert erro.value.__cause__ is None
    assert erro.value.__context__ is None


async def test_prompt_traz_instrucoes_e_exemplos_de_exclusao() -> None:
    texto = CASOS[0]["texto"]

    resultado = await extrair(CASOS[0]["rascunho"]["elementos"], texto)

    instrucoes = json.loads(resultado.chamada.prompt)["instrucoes_fixas_do_sistema"]
    variantes = instrucoes["schema_saida"]["properties"]["elementos"]["items"]["anyOf"]
    [variante] = [
        v for v in variantes if v["properties"]["construto_pretendido"].get("enum") == ["exclusao"]
    ]
    dimensao = variante["properties"]["dimensao"]["description"]
    assert "Condição sobre a venda" in dimensao and "é condicao_limiar" in dimensao
    assert "'" not in dimensao
    assert "{valor, trecho} por código" in variante["properties"]["valores"]["description"]
    [exclusao] = [i for i in instrucoes["construtos_habilitados"] if i.startswith("exclusao:")]
    for termo in (
        "loja, marca ou cargo",
        "Um elemento por dimensão",
        "{valor, trecho}",
        "'Todas as lojas, menos a 13' só exclui",
        "'Somente a loja 13' só inclui: é núcleo",
        "fica no núcleo mesmo quando também é excluído",
        "nunca corrigida aqui",
        "com exceção dos gerentes (150)",
        "Este bônus não se aplica aos cargos de gerente",
        "exceto a 13 e a 58",
        "'Pague 2% nas lojas 13 e 58, exceto a loja 13' -> nucleo.loja com 13 e 58",
        "trecho 'Não vale para a loja 5', com o N maiúsculo como no texto",
        "exceto a matrícula MATRIC-422",
        "só para uma de várias regras do texto",
        "Quando o texto tem várias regras, o núcleo é só a primeira",
        "loja 7 e 4% não entram no núcleo",
    ):
        assert termo in exclusao
