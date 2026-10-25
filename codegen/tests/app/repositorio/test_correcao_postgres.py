"""As consultas da correção do código gerado no Postgres real, com as migrations da api."""

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.correcao_codigo import FalhaDaExecucao
from app.repositorio.resultados import (
    ResultadoDesconhecidoError,
    buscar_falha_da_execucao,
    posicao_do_codigo,
)
from tests.app.repositorio.test_tentativas_postgres import Historico, banco

__all__ = ["banco"]

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="Requer Docker; habilitar com RUN_POSTGRES_INTEGRATION=1",
    ),
]


async def test_posicao_conta_os_codigos_da_mesma_versao_na_ordem_de_criacao(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    """Códigos de outra versão do job não contam: cada versão tem o próprio limite."""
    sessoes, historico = banco
    job = await historico.job()
    original = await historico.versao(job, 1, "extracao", "0.03")
    alternativa = await historico.versao(
        job, 2, "sugestao_adaptacao", "0.02", regra_origem=original
    )
    await historico.codigo(job, original)
    primeiro = await historico.codigo(job, alternativa)
    segundo = await historico.codigo(job, alternativa)
    terceiro = await historico.codigo(job, alternativa)

    posicoes = [await posicao_do_codigo(sessoes, job, c) for c in (primeiro, segundo, terceiro)]

    assert posicoes == [1, 2, 3]


async def test_posicao_de_codigo_de_outro_job_e_zero(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    sessoes, historico = banco
    job = await historico.job()
    codigo = await historico.codigo(job, await historico.versao(job, 1, "extracao", "0.03"))

    assert await posicao_do_codigo(sessoes, await historico.job(), codigo) == 0
    assert await posicao_do_codigo(sessoes, job, uuid4()) == 0


async def test_falha_le_o_diagnostico_e_so_as_assercoes_violadas(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    sessoes, historico = banco
    job = await historico.job()
    regra = await historico.versao(job, 1, "extracao", "0.03")
    diagnostico = {"causa": "cobertura_incompleta", "elementos_ausentes": ["elem.1"]}
    violada = {
        "nome": "sem_comissao_negativa",
        "detalhe": "valor não finito",
        "resultado": "violada",
    }
    resultado = await historico.resultado(
        job,
        regra,
        None,
        status="erro_codigo",
        diagnostico=diagnostico,
        assercoes=[{"nome": "outra", "detalhe": None, "resultado": "ok"}, violada],
    )

    falha = await buscar_falha_da_execucao(sessoes, job, resultado)

    assert falha == FalhaDaExecucao("erro_codigo", diagnostico, [violada])


async def test_falha_de_outro_job_nao_e_lida(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    sessoes, historico = banco
    job = await historico.job()
    resultado = await historico.resultado(
        job, await historico.versao(job, 1, "extracao", "0.03"), None, status="erro_codigo"
    )

    with pytest.raises(ResultadoDesconhecidoError):
        await buscar_falha_da_execucao(sessoes, await historico.job(), resultado)
