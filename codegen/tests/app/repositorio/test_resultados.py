from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
import simplejson

from app.repositorio.resultados import ResultadoIndisponivelError, buscar_totais

JOB_ID = uuid4()
RESULTADO_ID = uuid4()


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


async def test_buscar_totais_le_o_par_que_a_adaptacao_precisa() -> None:
    linha = {"totais": {"simulado": Decimal("492100.00"), "orcamento": Decimal("485000.00")}}

    totais = await buscar_totais(_sessionmaker(linha), JOB_ID, RESULTADO_ID)

    assert totais.simulado == Decimal("492100.00")
    assert totais.orcamento == Decimal("485000.00")


async def test_buscar_totais_decodifica_jsonb_recebido_como_texto_preservando_decimal() -> None:
    """Sem o `::text` o driver devolveria float, e o total viraria um número aproximado."""
    bruto = simplejson.dumps({"simulado": Decimal("492100.01"), "orcamento": Decimal("485000.00")})

    totais = await buscar_totais(_sessionmaker({"totais": bruto}), JOB_ID, RESULTADO_ID)

    assert totais.simulado == Decimal("492100.01")
    assert isinstance(totais.simulado, Decimal)


async def test_buscar_totais_filtra_pelo_job_do_resultado() -> None:
    """Resultado de outro job não pode embasar a adaptação deste."""
    sessoes = _sessionmaker({"totais": {"simulado": 1, "orcamento": 2}})

    await buscar_totais(sessoes, JOB_ID, RESULTADO_ID)

    _, parametros = sessoes.sessao.executado_com
    assert parametros == {"resultado_id": str(RESULTADO_ID), "job_id": str(JOB_ID)}


async def test_buscar_totais_recusa_resultado_inexistente() -> None:
    with pytest.raises(ResultadoIndisponivelError):
        await buscar_totais(_sessionmaker(None), JOB_ID, RESULTADO_ID)


@pytest.mark.parametrize(
    "totais",
    [{}, {"simulado": Decimal("1")}, {"orcamento": Decimal("1")}],
    ids=["vazio", "sem_orcamento", "sem_simulado"],
)
async def test_buscar_totais_recusa_desfecho_sem_os_dois_totais(totais: dict[str, Any]) -> None:
    """Fora de `sucesso` o worker não grava totais, e não há razão a aplicar."""
    with pytest.raises(ResultadoIndisponivelError):
        await buscar_totais(_sessionmaker({"totais": totais}), JOB_ID, RESULTADO_ID)
