from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
import simplejson

from app.repositorio.regras import RegraInvalidaError, buscar_regra

JOB_ID = uuid4()
REGRA_ID = uuid4()


class _ResultadoFalso:
    def __init__(self, linha: dict[str, Any] | None) -> None:
        self._linha = linha

    def mappings(self) -> "_ResultadoFalso":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self._linha


class _SessaoFalsa:
    def __init__(self, linha: dict[str, Any] | None) -> None:
        self._linha = linha
        self.executado_com: tuple[Any, Any] | None = None

    async def execute(self, statement: Any, params: Any) -> _ResultadoFalso:
        self.executado_com = (statement, params)
        return _ResultadoFalso(self._linha)


def _sessionmaker(linha: dict[str, Any] | None) -> Any:
    sessao = _SessaoFalsa(linha)

    @asynccontextmanager
    async def sessoes() -> AsyncIterator[_SessaoFalsa]:
        yield sessao

    sessoes.sessao = sessao  # type: ignore[attr-defined]
    return sessoes


async def test_buscar_regra_valida_a_linha_encontrada() -> None:
    linha = {
        "nucleo": {"percentual": Decimal("0.025")},
        "especificacoes": [],
    }
    sessoes = _sessionmaker(linha)

    regra = await buscar_regra(sessoes, JOB_ID, REGRA_ID)

    assert regra.para_contrato()["nucleo"]["percentual"] == Decimal("0.025")


async def test_buscar_regra_decodifica_jsonb_recebido_como_texto_preservando_decimal() -> None:
    linha = {
        "nucleo": simplejson.dumps({"percentual": Decimal("0.025")}, use_decimal=True),
        "especificacoes": simplejson.dumps([], use_decimal=True),
    }
    sessoes = _sessionmaker(linha)

    regra = await buscar_regra(sessoes, JOB_ID, REGRA_ID)

    assert regra.para_contrato()["nucleo"]["percentual"] == Decimal("0.025")


async def test_buscar_regra_usa_job_id_e_regra_id_como_parametros() -> None:
    sessoes = _sessionmaker({"nucleo": {}, "especificacoes": []})

    await buscar_regra(sessoes, JOB_ID, REGRA_ID)

    _, parametros = sessoes.sessao.executado_com  # type: ignore[attr-defined]
    assert parametros == {"regra_id": str(REGRA_ID), "job_id": str(JOB_ID)}


async def test_buscar_regra_recusa_quando_a_linha_nao_existe() -> None:
    sessoes = _sessionmaker(None)

    with pytest.raises(RegraInvalidaError):
        await buscar_regra(sessoes, JOB_ID, REGRA_ID)


async def test_buscar_regra_recusa_quando_a_regra_falha_o_contrato() -> None:
    linha = {"nucleo": {"percentual": "not-a-number"}, "especificacoes": []}
    sessoes = _sessionmaker(linha)

    with pytest.raises(RegraInvalidaError):
        await buscar_regra(sessoes, JOB_ID, REGRA_ID)


async def test_buscar_regra_nao_expoe_o_conteudo_da_regra_no_erro() -> None:
    linha = {
        "nucleo": {"percentual": "not-a-number", "segredo": "conteudo-sensivel"},
        "especificacoes": [],
    }
    sessoes = _sessionmaker(linha)

    with pytest.raises(RegraInvalidaError) as erro:
        await buscar_regra(sessoes, JOB_ID, REGRA_ID)

    assert "conteudo-sensivel" not in str(erro.value)
