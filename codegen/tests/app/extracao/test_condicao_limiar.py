import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.extracao.registro import CONSTRUTOS_HABILITADOS
from tests.app.extracao.test_motor import extrair, modelo_falso

ARQUIVO = Path(__file__).resolve().parents[2] / "fixtures" / "corpus_condicao_limiar.json"
CASOS: list[dict[str, Any]] = json.loads(ARQUIVO.read_text(encoding="utf-8"), parse_float=Decimal)


@pytest.mark.parametrize("caso", CASOS, ids=[c["id"] for c in CASOS])
async def test_condicao_limiar_pelo_motor_com_modelo_falso(caso: dict[str, Any]) -> None:
    if any(c in CONSTRUTOS_HABILITADOS for c in caso.get("construtos_desabilitados", [])):
        pytest.skip("caso de fallback exige construto desabilitado")
    resultado = await extrair(modelo_falso(caso["rascunho"]), caso["texto"])

    assert resultado.representacao.para_contrato() == caso["representacao_esperada"]
    assert resultado.parametros == caso["parametros_esperados"]
    assert [r.motivo for r in resultado.rebaixamentos] == (
        [caso["motivo_esperado"]] if caso["motivo_esperado"] else []
    )


async def test_prompt_orienta_escopos_operadores_meta_e_precedencia() -> None:
    modelo = modelo_falso(CASOS[0]["rascunho"])
    resultado = await extrair(modelo, CASOS[0]["texto"])
    instrucoes = json.loads(resultado.chamada.prompt)["instrucoes_fixas_do_sistema"]
    construtos = " ".join(instrucoes["construtos_habilitados"])

    for termo in (
        "condicao_limiar",
        "venda_total",
        "matricula",
        "loja",
        "marca",
        "rede",
        ">=",
        ">",
        "<=",
        "<",
        "==",
        "generico",
        "campos",
        "meta_venda",
        "faixa_valor",
        "Se a loja vender no mínimo R$ 50 mil no mês, a comissão é de 3%",
        "bônus de R$ 500 só vale se a loja vender R$ 100 mil",
    ):
        assert termo in construtos
    assert "condicao_limiar" in CONSTRUTOS_HABILITADOS


@pytest.mark.parametrize("campo", ["metrica", "operador", "limiar"])
async def test_campo_essencial_ausente_nao_entrega_condicao(campo: str) -> None:
    caso = deepcopy(CASOS[0])
    del caso["rascunho"]["elementos"][0][campo]

    resultado = await extrair(modelo_falso(caso["rascunho"]), caso["texto"])

    assert resultado.representacao.para_contrato()["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": caso["texto"]}
    ]
    assert resultado.rebaixamentos[0].motivo == "campo_obrigatorio_ausente"


async def test_lastro_de_outra_frase_nao_sustenta_limiar() -> None:
    caso = deepcopy(CASOS[0])
    caso["rascunho"]["elementos"][0]["limiar"] = {"valor": 70000, "trecho": "R$ 70 mil"}
    texto = caso["texto"] + ". O orçamento é de R$ 70 mil."

    resultado = await extrair(modelo_falso(caso["rascunho"]), texto)

    assert resultado.representacao.para_contrato()["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": caso["texto"]}
    ]
    assert resultado.rebaixamentos[0].motivo == "valor_sem_lastro"


async def test_numero_por_extenso_com_percentual_no_mesmo_trecho() -> None:
    caso = deepcopy(CASOS[0])
    caso["texto"] = "Se a loja vender no mínimo cinquenta mil reais, a comissão é de 3%"
    elemento = caso["rascunho"]["elementos"][0]
    elemento.update(descricao=caso["texto"], trecho=caso["texto"])
    elemento["limiar"] = {"valor": 50000, "trecho": "cinquenta mil reais"}

    resultado = await extrair(modelo_falso(caso["rascunho"]), caso["texto"])

    assert resultado.representacao.para_contrato() == caso["representacao_esperada"]
    assert resultado.rebaixamentos == []


@pytest.mark.parametrize("escopo", ["departamento", "marca", "loja e rede"])
async def test_escopo_incompativel_com_trecho_nao_e_aceito(escopo: str) -> None:
    caso = deepcopy(CASOS[0])
    caso["rascunho"]["elementos"][0]["escopo_agregacao"] = escopo

    resultado = await extrair(modelo_falso(caso["rascunho"]), caso["texto"])

    assert resultado.representacao.para_contrato()["especificacoes"] == [
        {
            "ref": "elem.1",
            "construto": "generico",
            "descricao": caso["texto"],
            "campos": {"metrica": "venda_total", "operador": ">=", "limiar": 50000},
        }
    ]
    assert resultado.rebaixamentos[0].motivo == "termo_ambiguo"


async def test_aliases_sao_normalizados_sem_mudar_o_valor() -> None:
    caso = deepcopy(CASOS[0])
    caso["rascunho"]["elementos"][0].update(
        metrica="venda total", escopo_agregacao="da loja", operador="no mínimo"
    )

    resultado = await extrair(modelo_falso(caso["rascunho"]), caso["texto"])

    assert resultado.representacao.para_contrato() == caso["representacao_esperada"]
