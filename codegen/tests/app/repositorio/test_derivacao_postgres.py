"""As consultas da derivação do código da alternativa no Postgres real, com as migrations da api.

Conectado como o usuário do codegen, o teste também prova as permissões: a leitura de `regras`,
`codigos_gerados` e `resultados_simulacao` e o INSERT em `codigos_gerados`.
"""

import os
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositorio.artefatos import (
    buscar_codigo_simulado,
    gravar_codigo_derivado,
    id_do_codigo_derivado,
)
from app.repositorio.regras import Procedencia, buscar_procedencia
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


async def test_a_procedencia_e_a_origem_e_a_versao_de_que_a_alternativa_deriva(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    sessoes, historico = banco
    job = await historico.job()
    original = await historico.versao(job, 1, "extracao", "0.03")
    alternativa = await historico.versao(
        job, 2, "sugestao_adaptacao", "0.02", regra_origem=original
    )

    assert await buscar_procedencia(sessoes, job, original) == Procedencia("extracao", None)
    assert await buscar_procedencia(sessoes, job, alternativa) == Procedencia(
        "sugestao_adaptacao", original
    )


async def test_o_codigo_simulado_e_o_ultimo_da_versao_com_sucesso_na_simulacao(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    """Nem o código que falhou nem a execução candidata da busca da meta contam."""
    sessoes, historico = banco
    job = await historico.job()
    regra = await historico.versao(job, 1, "extracao", "0.03")
    que_passou = await historico.codigo(job, regra)
    resultado_que_passou = await historico.resultado(job, regra, "1000", codigo=que_passou)
    que_falhou = await historico.codigo(job, regra)
    await historico.resultado(job, regra, None, status="erro_codigo", codigo=que_falhou)
    da_busca = await historico.codigo(job, regra)
    await historico.resultado(job, regra, "900", proposito="busca_meta", codigo=da_busca)

    simulado = await buscar_codigo_simulado(sessoes, job, regra)

    assert simulado is not None
    assert simulado.id == que_passou
    assert simulado.fonte == "f"
    # O resultado da simulação que passou, e não o da falha nem o da execução da busca.
    assert simulado.resultado_id == resultado_que_passou


async def test_com_dois_sucessos_do_mesmo_codigo_a_origem_e_o_resultado_mais_recente(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    """O mesmo resultado que a api liga à simulação do código, e não um qualquer dos dois."""
    sessoes, historico = banco
    job = await historico.job()
    regra = await historico.versao(job, 1, "extracao", "0.03")
    codigo = await historico.codigo(job, regra)
    await historico.resultado(job, regra, "1000", codigo=codigo)
    mais_recente = await historico.resultado(job, regra, "1000", codigo=codigo)

    simulado = await buscar_codigo_simulado(sessoes, job, regra)

    assert simulado is not None
    assert simulado.id == codigo
    assert simulado.resultado_id == mais_recente


async def test_versao_sem_codigo_simulado_com_sucesso_nao_tem_origem(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    sessoes, historico = banco
    job = await historico.job()
    regra = await historico.versao(job, 1, "extracao", "0.03")
    await historico.resultado(job, regra, None, status="erro_codigo")

    assert await buscar_codigo_simulado(sessoes, job, regra) is None
    assert await buscar_codigo_simulado(sessoes, await historico.job(), regra) is None


async def test_o_codigo_derivado_aponta_o_prompt_da_origem_e_a_regravacao_nao_duplica(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    sessoes, historico = banco
    job = await historico.job()
    original = await historico.versao(job, 1, "extracao", "0.03")
    alternativa = await historico.versao(
        job, 2, "sugestao_adaptacao", "0.02", regra_origem=original
    )
    codigo = await historico.codigo(job, original)
    await historico.resultado(job, original, "1000", codigo=codigo)
    origem = await buscar_codigo_simulado(sessoes, job, original)
    assert origem is not None

    ids = [
        await gravar_codigo_derivado(
            sessoes, job_id=job, regra_id=alternativa, origem=origem, fonte="g"
        )
        for _ in range(2)
    ]

    assert ids == [id_do_codigo_derivado(origem.id, alternativa)] * 2
    async with sessoes() as sessao:
        linhas = (
            await sessao.execute(
                text("SELECT regra_id, prompt_id, fonte FROM codigos_gerados WHERE id = :id"),
                {"id": ids[0]},
            )
        ).all()
    assert [(UUID(str(r[0])), UUID(str(r[1])), r[2]) for r in linhas] == [
        (alternativa, origem.prompt_id, "g")
    ]
