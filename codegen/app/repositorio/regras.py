"""Read-only access to `regras`, for the graph's `load_rule` node.

Only `SELECT` here: the row is written once by the `api`, before `regra-submetida` is
published (AGENTS.md - "a `api` é dona do estado do job... os demais serviços escrevem
apenas os artefatos que produzem"). `codegen`'s database user also has `INSERT` on this
table (migration `006-cria-regras.sql`, for a future reprocessing/adaptation flow), but
nothing in this task's scope writes to it.
"""

from uuid import UUID

import simplejson
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.falhas import FalhaDoJobError
from app.representacao_regra import RepresentacaoRegra


class RegraInvalidaError(FalhaDoJobError):
    """The rule the event points to is missing, or fails `RepresentacaoRegra`'s contract.

    Never carries the rule's content - only the caller's job/rule ids, which are already
    correlation ids, not artifact data. A redelivery does not make the rule valid, so this
    failure is permanent.

    `load_rule` has no etapa of its own in the closed vocabulary: reading the rule is the
    first step of the generation the job is already in (`gerando_regra`).
    """

    etapa = "geracao_codigo"


def _como_objeto(valor: object) -> object:
    # `::text` in the query below guarantees a JSON string here regardless of driver-level
    # auto-decoding; without the cast, asyncpg/SQLAlchemy parses jsonb numbers as `float`,
    # which `ValorRegra` rejects under `strict=True` and silently loses precision either way.
    if isinstance(valor, str):
        return simplejson.loads(valor, use_decimal=True)
    return valor


async def buscar_regra(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, regra_id: UUID
) -> RepresentacaoRegra:
    """Load and validate the rule `regra_id` confirmed for `job_id`.

    Raises `RegraInvalidaError` when the row does not exist for that job, or when its
    `nucleo`/`especificacoes` fail `RepresentacaoRegra`'s validation.
    """
    consulta = text(
        "SELECT nucleo::text AS nucleo, especificacoes::text AS especificacoes"
        " FROM regras WHERE id = :regra_id AND job_id = :job_id"
    )
    parametros = {"regra_id": str(regra_id), "job_id": str(job_id)}
    async with sessoes() as sessao:
        resultado = await sessao.execute(consulta, parametros)
        linha = resultado.mappings().one_or_none()

    if linha is None:
        raise RegraInvalidaError("Rule not found for this job") from None

    try:
        return RepresentacaoRegra.model_validate(
            {
                "nucleo": _como_objeto(linha["nucleo"]),
                "especificacoes": _como_objeto(linha["especificacoes"]),
            }
        )
    except ValidationError as erro:
        raise RegraInvalidaError("Rule failed RepresentacaoRegra's contract") from erro
