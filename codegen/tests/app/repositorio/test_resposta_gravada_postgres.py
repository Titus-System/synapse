"""`buscar_resposta_gravada` contra o DDL das migrations da api, num Postgres descartável."""

import os
from typing import Any
from uuid import uuid4

import pytest

from app.repositorio.artefatos import (
    RespostaGravada,
    buscar_resposta_gravada,
    gravar_prompt_e_resposta,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="Requer Docker; habilitar com RUN_POSTGRES_INTEGRATION=1",
    ),
]

PROMPT = '{"dados_nao_confiaveis_da_correcao": {"texto": "o percentual passa para 3%"}}'
RESPOSTA = '{"operacoes": []}'


async def test_acha_a_chamada_gravada_pelo_prompt_do_job_no_no(banco_extracao: Any) -> None:
    sessoes, _, job, submissao = banco_extracao
    prompt_id, resposta_id = await gravar_prompt_e_resposta(
        sessoes,
        job_id=job,
        no="extracao_parametros",
        prompt=PROMPT,
        modelo={"provedor": "teste"},
        resposta=RESPOSTA,
        consumo_tokens=None,
    )

    gravada = await buscar_resposta_gravada(
        sessoes, job_id=job, no="extracao_parametros", prompt=PROMPT, submissao_id=submissao
    )

    assert gravada == RespostaGravada(prompt_id, resposta_id, RESPOSTA)


@pytest.mark.parametrize("diferenca", ["outro_job", "outro_no", "outro_prompt"])
async def test_nao_acha_a_chamada_de_outro_job_no_ou_prompt(
    banco_extracao: Any, diferenca: str
) -> None:
    sessoes, _, job, submissao = banco_extracao
    await gravar_prompt_e_resposta(
        sessoes,
        job_id=job,
        no="extracao_parametros",
        prompt=PROMPT,
        modelo={"provedor": "teste"},
        resposta=RESPOSTA,
        consumo_tokens=None,
    )
    busca = {
        "job_id": job,
        "no": "extracao_parametros",
        "prompt": PROMPT,
        "submissao_id": submissao,
    }
    if diferenca == "outro_job":
        busca["job_id"] = uuid4()
    elif diferenca == "outro_no":
        busca["no"] = "geracao_codigo"
    else:
        busca["prompt"] = PROMPT + " "

    assert await buscar_resposta_gravada(sessoes, **busca) is None


async def test_nao_acha_a_chamada_gravada_antes_da_submissao(banco_extracao: Any) -> None:
    """Uma correção nova com o mesmo texto não herda a resposta de uma correção anterior."""
    sessoes, dono, job, _ = banco_extracao
    await gravar_prompt_e_resposta(
        sessoes,
        job_id=job,
        no="extracao_parametros",
        prompt=PROMPT,
        modelo={"provedor": "teste"},
        resposta=RESPOSTA,
        consumo_tokens=None,
    )
    usuario = await dono.fetchval("SELECT usuario_id FROM jobs WHERE id = $1", job)
    posterior = uuid4()
    await dono.execute(
        "INSERT INTO submissoes(id, usuario_id, tipo, transcricao, criado_em)"
        " VALUES($1, $2, 'texto', 'o percentual passa para 3%', now() + interval '1 second')",
        posterior,
        usuario,
    )

    gravada = await buscar_resposta_gravada(
        sessoes, job_id=job, no="extracao_parametros", prompt=PROMPT, submissao_id=posterior
    )

    assert gravada is None
