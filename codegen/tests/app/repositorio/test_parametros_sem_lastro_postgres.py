"""`parametros_sem_lastro` contra o DDL das migrations da api, num Postgres descartável (T-280)."""

import os
from typing import Any
from uuid import UUID, uuid4

import pytest
import simplejson

from app.repositorio.extracoes import parametros_sem_lastro

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="Requer Docker; habilitar com RUN_POSTGRES_INTEGRATION=1",
    ),
]

REBAIXAMENTOS = [
    {"ref": "parametros.orcamento", "motivo": "valor_sem_lastro"},
    {"ref": "elem.1", "construto_pretendido": "bonus_fixo", "motivo": "construto_nao_habilitado"},
    {"ref": "parametros.competencias", "motivo": "periodo_nao_resolvido"},
]


async def _extracao(dono: Any, job: UUID, submissao: UUID) -> None:
    prompt, resposta = uuid4(), uuid4()
    await dono.execute(
        "INSERT INTO prompts(id, job_id, no, conteudo, modelo, criado_em)"
        " VALUES($1, $2, 'extracao_parametros', 'p', '{}', now())",
        prompt,
        job,
    )
    await dono.execute(
        "INSERT INTO respostas_modelo(id, job_id, prompt_id, conteudo, criado_em)"
        " VALUES($1, $2, $3, 'r', now())",
        resposta,
        job,
        prompt,
    )
    await dono.execute(
        "INSERT INTO extracoes_regras"
        " (id, job_id, submissao_id, resposta_id, representacao, rebaixamentos, criado_em)"
        " VALUES($1, $2, $3, $4, '{}', $5::jsonb, now())",
        uuid4(),
        job,
        submissao,
        resposta,
        simplejson.dumps(REBAIXAMENTOS),
    )


async def _versao(
    dono: Any, job: UUID, versao: int, origem: str, anterior: UUID | None = None
) -> UUID:
    regra = uuid4()
    await dono.execute(
        "INSERT INTO regras"
        " (id, job_id, versao, origem, regra_origem_id, nucleo, especificacoes, hash, criada_em)"
        " VALUES($1, $2, $3, $4, $5, '{}', '[]', $6, now())",
        regra,
        job,
        versao,
        origem,
        anterior,
        uuid4().hex * 2,
    )
    return regra


async def test_versao_extraida_traz_os_parametros_descartados_por_falta_de_lastro(
    banco_extracao: Any,
) -> None:
    sessoes, dono, job, submissao = banco_extracao
    await _extracao(dono, job, submissao)
    extraida = await _versao(dono, job, 1, "extracao")

    assert await parametros_sem_lastro(sessoes, job, extraida) == {"orcamento", "competencias"}


@pytest.mark.parametrize("origem", ["correcao", "confirmacao_usuario", "sugestao_adaptacao"])
async def test_versao_seguinte_nao_e_checada_contra_a_extracao(
    banco_extracao: Any, origem: str
) -> None:
    """A correção já respondeu ao conflito, com ou sem o parâmetro; checá-la o manteria."""
    sessoes, dono, job, submissao = banco_extracao
    await _extracao(dono, job, submissao)
    extraida = await _versao(dono, job, 1, "extracao")
    seguinte = await _versao(dono, job, 2, origem, extraida)

    assert await parametros_sem_lastro(sessoes, job, seguinte) == frozenset()


async def test_versao_de_outro_job_nao_traz_parametro(banco_extracao: Any) -> None:
    sessoes, dono, job, submissao = banco_extracao
    await _extracao(dono, job, submissao)
    extraida = await _versao(dono, job, 1, "extracao")

    assert await parametros_sem_lastro(sessoes, uuid4(), extraida) == frozenset()


async def test_job_sem_extracao_nao_traz_parametro(banco_extracao: Any) -> None:
    sessoes, dono, job, _ = banco_extracao
    formulario = await _versao(dono, job, 1, "formulario")

    assert await parametros_sem_lastro(sessoes, job, formulario) == frozenset()
