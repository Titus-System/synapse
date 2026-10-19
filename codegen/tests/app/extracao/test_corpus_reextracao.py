"""Corpus T-224: falsos exercitam determinismo; modelo real exige credencial configurada."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from app.config import get_settings
from app.extracao.lastro import numeros_citados
from app.extracao.reextracao import reextrair_regra
from app.graph.core.llm.registry import get_model, get_model_metadata
from app.repositorio.rodadas_correcao import CorrecaoAnterior
from app.representacao_regra import RepresentacaoRegra
from tests.app.graph.conftest import FakeChatModel

ARQUIVO = Path(__file__).resolve().parents[2] / "fixtures" / "corpus_reextracao.json"
CORPUS: list[dict[str, Any]] = json.loads(ARQUIVO.read_text(), parse_float=Decimal)
PUBLICADAS = ["2025-10", "2025-11"]
REGRA = RepresentacaoRegra.model_validate(
    {"nucleo": {"percentual": Decimal("0.025")}, "especificacoes": []}
)
PARAMETROS = {"orcamento": Decimal("500000"), "meta_venda": Decimal("12000000")}
CONFLITOS = [{"elementos": ["nucleo.percentual"], "motivo": "percentual conflitante"}]


def _historico(caso: dict[str, Any]) -> list[CorrecaoAnterior]:
    return [CorrecaoAnterior(item["conflitos"], item["texto"]) for item in caso["historico"]]


def test_corpus_reextracao_versionado_cobre_os_casos_da_t224() -> None:
    ids = [caso["id"] for caso in CORPUS]

    assert len(set(ids)) == len(ids)
    assert len(ids) >= 5
    assert {
        "primeira_correcao_sem_historico",
        "terceira_correcao_com_conflitos_e_textos",
        "historico_nao_e_fonte_de_valores_novos",
        "remocao_precisa_trecho_da_correcao",
        "orcamento_hallucinado_com_trecho_validado",
    } <= set(ids)
    for caso in CORPUS:
        assert caso["texto"]
        assert isinstance(caso["historico"], list)
        assert isinstance(caso["operacoes_falsas"], list)


@pytest.mark.parametrize("caso", CORPUS, ids=lambda caso: caso["id"])
async def test_corpus_reextracao_com_modelo_falso(caso: dict[str, Any]) -> None:
    import simplejson

    modelo = FakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content=simplejson.dumps(
                        {"operacoes": caso["operacoes_falsas"]}, use_decimal=True
                    )
                )
            ]
        )
    )

    resultado = await reextrair_regra(
        RepresentacaoRegra.model_validate(caso.get("regra_atual", REGRA.para_contrato())),
        PARAMETROS,
        CONFLITOS,
        caso["texto"],
        PUBLICADAS,
        modelo=modelo,
        metadados_modelo={"modelo": "fake"},
        historico=_historico(caso),
    )

    assert (
        resultado.representacao.para_contrato()["nucleo"]["percentual"]
        == caso["percentual_esperado"]
    )
    assert resultado.parametros["orcamento"] == caso["orcamento_esperado"]
    assert resultado.parametros["meta_venda"] == caso["meta_esperada"]
    assert [item.motivo for item in resultado.rebaixamentos] == caso["motivos_esperados"]
    assert resultado.representacao.para_contrato()["especificacoes"] == caso.get(
        "especificacoes_esperadas", []
    )
    assert len(modelo.seen_messages) == 1


@pytest.mark.llm
@pytest.mark.parametrize(
    "caso",
    [caso for caso in CORPUS if caso["modelo_real"]],
    ids=lambda caso: caso["id"],
)
async def test_corpus_reextracao_modelo_real(caso: dict[str, Any]) -> None:
    if not get_settings().GOOGLE_API_KEY:
        pytest.skip("T-224: modelo real não executado; GOOGLE_API_KEY ausente")

    from tests.app.apoio_provedor_real import executar_com_retentativa_503

    get_model.cache_clear()
    resultado = await executar_com_retentativa_503(
        lambda: reextrair_regra(
            RepresentacaoRegra.model_validate(caso.get("regra_atual", REGRA.para_contrato())),
            PARAMETROS,
            CONFLITOS,
            caso["texto"],
            PUBLICADAS,
            modelo=get_model("extraction"),
            metadados_modelo=get_model_metadata("extraction"),
            historico=_historico(caso),
        )
    )

    assert (
        resultado.representacao.para_contrato()["nucleo"]["percentual"]
        == caso["percentual_esperado"]
    )
    assert resultado.parametros["orcamento"] == caso["orcamento_esperado"]
    assert resultado.parametros["meta_venda"] == caso["meta_esperada"]
    especificacoes = resultado.representacao.para_contrato()["especificacoes"]
    if caso["id"] == "bonus_parcial_preserva_condicao":
        assert len(especificacoes) == 1
        descricao = especificacoes[0]["descricao"]
        assert numeros_citados(descricao) == {"600", "10.000"}
        assert "acima" in descricao.casefold()
        assert "mês" in descricao.casefold() or "mensal" in descricao.casefold()
    else:
        assert especificacoes == caso.get("especificacoes_esperadas", [])
