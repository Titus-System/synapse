"""Writes of the artifacts the graph produces: `prompts`, `respostas_modelo`, `codigos_gerados`.

`codegen` only has `SELECT` and `INSERT` on these tables (`api` changesets 007 to 009), so a
row can never be corrected by an `UPDATE`. Every id is derived from the inputs (UUID v5) and
every insert uses `ON CONFLICT DO NOTHING`: re-running a node with the same inputs, e.g. after
the message is redelivered, writes nothing new and returns the same ids.

The same derivation also produces the idempotency key of the `no-concluido` event, which
references these rows - see `id_do_evento_de_trilha`.
"""

from hashlib import sha256
from typing import Any
from uuid import UUID, uuid5

import simplejson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.codigo_gerado import LINGUAGEM

_NAMESPACE = UUID("e4119130-a76b-41be-b0fd-4738b08edb87")

_INSERIR_PROMPT = text(
    "INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)"
    " VALUES (:id, :job_id, :no, :conteudo, CAST(:modelo AS jsonb), now())"
    " ON CONFLICT DO NOTHING"
)
_INSERIR_RESPOSTA = text(
    "INSERT INTO respostas_modelo (id, job_id, prompt_id, conteudo, consumo_tokens, criado_em)"
    " VALUES (:id, :job_id, :prompt_id, :conteudo, CAST(:consumo_tokens AS jsonb), now())"
    " ON CONFLICT DO NOTHING"
)
_INSERIR_CODIGO = text(
    "INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)"
    " VALUES (:id, :job_id, :regra_id, :linguagem, :fonte, :prompt_id, now())"
    " ON CONFLICT DO NOTHING"
)


def id_do_prompt(job_id: UUID, no: str, prompt: str, resposta: str) -> UUID:
    # The reply is part of the key: a later call with the same prompt that gets a different
    # reply is a different call, and must not collide with this one.
    digest = sha256(f"{prompt}\x00{resposta}".encode()).hexdigest()
    return uuid5(_NAMESPACE, f"prompt:{job_id}:{no}:{digest}")


def id_da_resposta(prompt_id: UUID) -> UUID:
    return uuid5(_NAMESPACE, f"resposta:{prompt_id}")


def id_do_codigo(prompt_id: UUID) -> UUID:
    return uuid5(_NAMESPACE, f"codigo:{prompt_id}")


def id_do_evento_de_trilha(job_id: UUID, no: str, referencia: UUID) -> UUID:
    """Chave de idempotência do `no-concluido` deste nó.

    `referencia` é a linha que o nó aponta - o código gerado, no nó de geração, ou o
    resultado da simulação, nos nós que decidem sobre ela.

    Derivada aqui, junto dos ids das linhas que o evento referencia, para reaproveitar o
    mesmo namespace e o mesmo esquema de prefixo que separa um id do outro. É determinística
    pelo mesmo motivo que os demais: republicar o evento numa reexecução do nó precisa
    carregar o mesmo id, senão o índice único de `trilhas_auditoria.evento_id` na api não
    tem como reconhecer a reentrega e a trilha ganharia uma linha duplicada.
    """
    return uuid5(_NAMESPACE, f"trilha:{job_id}:{no}:{referencia}")


async def gravar_prompt_e_resposta(
    sessoes: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    no: str,
    prompt: str,
    modelo: dict[str, Any],
    resposta: str,
    consumo_tokens: dict[str, Any] | None,
) -> tuple[UUID, UUID]:
    """Insert the prompt and the model's verbatim reply in one transaction.

    Returns `(prompt_id, resposta_id)`.
    """
    prompt_id = id_do_prompt(job_id, no, prompt, resposta)
    resposta_id = id_da_resposta(prompt_id)
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            _INSERIR_PROMPT,
            {
                "id": prompt_id,
                "job_id": job_id,
                "no": no,
                "conteudo": prompt,
                "modelo": simplejson.dumps(modelo, use_decimal=True),
            },
        )
        await sessao.execute(
            _INSERIR_RESPOSTA,
            {
                "id": resposta_id,
                "job_id": job_id,
                "prompt_id": prompt_id,
                "conteudo": resposta,
                "consumo_tokens": (
                    None
                    if consumo_tokens is None
                    else simplejson.dumps(consumo_tokens, use_decimal=True)
                ),
            },
        )
    return prompt_id, resposta_id


async def gravar_codigo(
    sessoes: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    regra_id: UUID,
    prompt_id: UUID,
    fonte: str,
) -> UUID:
    """Insert the extracted `regra.py` source and return its `codigo_gerado_id`."""
    codigo_gerado_id = id_do_codigo(prompt_id)
    async with sessoes() as sessao, sessao.begin():
        await sessao.execute(
            _INSERIR_CODIGO,
            {
                "id": codigo_gerado_id,
                "job_id": job_id,
                "regra_id": regra_id,
                "linguagem": LINGUAGEM,
                "fonte": fonte,
                "prompt_id": prompt_id,
            },
        )
    return codigo_gerado_id
