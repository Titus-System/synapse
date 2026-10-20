"""Corpus versionado: casos de núcleo e parâmetros exigem modelo real configurado."""

import asyncio
import json
import sys
from collections.abc import AsyncGenerator
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
from google.genai.errors import ServerError
from langchain_core.language_models import BaseChatModel

from app.config import get_settings
from app.extracao.modelos import ResultadoExtracao
from app.extracao.motor import extrair_regra
from app.extracao.registro import CONSTRUTOS_HABILITADOS
from app.graph.core.llm.registry import get_model, get_model_metadata
from app.representacao_regra import RepresentacaoRegra

ARQUIVO = Path(__file__).resolve().parents[2] / "fixtures" / "corpus_extracao.json"
CORPUS: list[dict[str, Any]] = json.loads(ARQUIVO.read_text(encoding="utf-8"), parse_float=Decimal)
CORPUS += [
    caso
    for caso in json.loads(
        ARQUIVO.with_name("corpus_condicao_limiar.json").read_text(encoding="utf-8"),
        parse_float=Decimal,
    )
    if not caso.get("somente_modelo_falso")
]


def test_corpus_versionado_cobre_categorias_obrigatorias() -> None:
    ids = [caso["id"] for caso in CORPUS]

    assert len(ids) == len(set(ids))
    assert len(ids) >= 11
    assert {
        "cinco_campos",
        "sem_filtros",
        "vigencia_mes",
        "vigencia_intervalo",
        "virgula",
        "percentual_por_cento",
        "extenso",
        "nomes_canonicos",
        "gerentes",
        "elemento_generico",
        "instrucoes_maliciosas",
        "simulacao_completa",
        "sem_parametros",
    } <= set(ids)
    for caso in CORPUS:
        assert caso["texto"] and caso["competencias_publicadas"]
        assert set(caso["representacao_esperada"]) == {"nucleo", "especificacoes"}
        assert isinstance(caso["parametros_esperados"], dict)
        RepresentacaoRegra.model_validate(caso["representacao_esperada"])


def test_corpus_mantem_percentuais_com_precisao_decimal() -> None:
    percentuais = [
        caso["representacao_esperada"]["nucleo"]["percentual"]
        for caso in CORPUS
        if "percentual" in caso["representacao_esperada"]["nucleo"]
    ]

    assert percentuais
    assert all(isinstance(percentual, Decimal) for percentual in percentuais)


def _indisponibilidade_503(erro: BaseException) -> bool:
    """Identifica apenas o 503 real do SDK, mesmo quando encapsulado pelo LangChain."""
    causa: BaseException | None = erro
    while causa is not None:
        if isinstance(causa, ServerError) and causa.code == 503:
            return True
        causa = causa.__cause__
    return False


async def _extrair_com_retentativa(
    caso: dict[str, Any], modelo: BaseChatModel
) -> ResultadoExtracao:
    # O SDK já executa tentativas internas. Acrescentamos uma única tentativa para
    # instabilidades 503; se persistir, o corpus não foi efetivamente verificado.
    for tentativa in range(2):
        try:
            return await extrair_regra(
                caso["texto"],
                caso["competencias_publicadas"],
                modelo=modelo,
                metadados_modelo=get_model_metadata("extraction"),
            )
        except Exception as erro:
            if not _indisponibilidade_503(erro):
                raise
            if tentativa == 1:
                pytest.skip("provedor indisponível (503 UNAVAILABLE após 2 tentativas)")
            await asyncio.sleep(2)
    raise AssertionError("tentativas esgotadas sem resultado")


def _erro_de_provedor(codigo: int) -> RuntimeError:
    erro = RuntimeError("erro encapsulado pelo provedor")
    erro.__cause__ = ServerError(codigo, {"error": {"status": "UNAVAILABLE"}})
    return erro


def test_somente_503_do_provedor_eh_indisponibilidade_temporaria() -> None:
    assert _indisponibilidade_503(_erro_de_provedor(503))
    assert _indisponibilidade_503(ServerError(503, {"error": {"status": "UNAVAILABLE"}}))
    assert not _indisponibilidade_503(_erro_de_provedor(500))
    assert not _indisponibilidade_503(ValueError("503 UNAVAILABLE"))


async def test_503_tem_uma_retentativa_antes_de_ignorar(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = 0
    esperas: list[float] = []

    async def chamada_falsa(*_args: Any, **_kwargs: Any) -> str:
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            raise _erro_de_provedor(503)
        return "resultado confirmado"

    async def espera_falsa(segundos: float) -> None:
        esperas.append(segundos)

    monkeypatch.setattr(sys.modules[__name__], "extrair_regra", chamada_falsa)
    monkeypatch.setattr(asyncio, "sleep", espera_falsa)

    resultado = await _extrair_com_retentativa(
        {"texto": "teste", "competencias_publicadas": []},
        modelo=cast(BaseChatModel, object()),
    )

    assert resultado == "resultado confirmado"
    assert chamadas == 2
    assert esperas == [2]


async def test_503_persistente_eh_reportado_como_nao_executado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chamadas = 0

    async def chamada_falsa(*_args: Any, **_kwargs: Any) -> None:
        nonlocal chamadas
        chamadas += 1
        raise _erro_de_provedor(503)

    async def espera_falsa(_segundos: float) -> None:
        pass

    monkeypatch.setattr(sys.modules[__name__], "extrair_regra", chamada_falsa)
    monkeypatch.setattr(asyncio, "sleep", espera_falsa)

    with pytest.raises(pytest.skip.Exception, match="provedor indisponível"):
        await _extrair_com_retentativa(
            {"texto": "teste", "competencias_publicadas": []},
            modelo=cast(BaseChatModel, object()),
        )
    assert chamadas == 2


async def test_erro_nao_transitorio_nao_eh_ignorado(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas = 0

    async def chamada_falsa(*_args: Any, **_kwargs: Any) -> None:
        nonlocal chamadas
        chamadas += 1
        raise ValueError("erro no processamento")

    monkeypatch.setattr(sys.modules[__name__], "extrair_regra", chamada_falsa)

    with pytest.raises(ValueError, match="erro no processamento"):
        await _extrair_com_retentativa(
            {"texto": "teste", "competencias_publicadas": []},
            modelo=cast(BaseChatModel, object()),
        )
    assert chamadas == 1


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def modelo_corpus() -> AsyncGenerator[BaseChatModel, None]:
    # Um cliente e um loop para todo o corpus; fechar a conexao antes do fim do loop.
    get_model.cache_clear()
    modelo = get_model("extraction")
    try:
        yield modelo
    finally:
        cliente = getattr(modelo, "async_client", None)
        if cliente is not None:
            await cliente.aclose()
        get_model.cache_clear()


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="precisa de chave do provedor")
@pytest.mark.parametrize("caso", CORPUS, ids=[caso["id"] for caso in CORPUS])
@pytest.mark.asyncio(loop_scope="module")
async def test_corpus_contra_modelo_real(
    caso: dict[str, Any], modelo_corpus: BaseChatModel
) -> None:
    if any(c in CONSTRUTOS_HABILITADOS for c in caso.get("construtos_desabilitados", [])):
        pytest.skip("caso de fallback exige construto desabilitado")
    resultado = await _extrair_com_retentativa(caso, modelo_corpus)

    regra = resultado.representacao.para_contrato()
    assert regra["nucleo"] == caso["representacao_esperada"]["nucleo"]
    assert resultado.parametros == caso["parametros_esperados"]
    esperados = caso["representacao_esperada"]["especificacoes"]
    if esperados:
        assert len(regra["especificacoes"]) == len(esperados)
        assert [(e["ref"], e["construto"]) for e in regra["especificacoes"]] == [
            (e["ref"], e["construto"]) for e in esperados
        ]
        if "rascunho" in caso:
            assert regra["especificacoes"] == esperados
        else:
            assert all(e["descricao"] for e in regra["especificacoes"])
    else:
        assert regra["especificacoes"] == []
