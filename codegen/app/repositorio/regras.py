"""Read-only access to `regras`, for the graph's `load_rule` and `decision` nodes.

Only `SELECT` here: the row is written once by the `api`, before `regra-submetida` is
published (AGENTS.md - "a `api` é dona do estado do job... os demais serviços escrevem
apenas os artefatos que produzem"). `codegen`'s database user also has `INSERT` on this
table (migration `006-cria-regras.sql`, for a future reprocessing/adaptation flow), but
nothing in this task's scope writes to it.
"""

from dataclasses import dataclass
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

    Reading the rule is the first step of domain validation.
    """

    etapa = "validacao_dominio"


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


@dataclass(frozen=True, slots=True)
class TentativasDeTaxa:
    """As taxas novas que o job já tentou até a versão simulada, inclusive."""

    feitas: int
    regra_e_tentativa: bool


async def contar_tentativas(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, regra_id: UUID
) -> TentativasDeTaxa:
    """Count the job's `sugestao_adaptacao` versions up to `regra_id`, and whether it is one.

    O limite é por job, mesmo depois de uma nova confirmação. A conta para na versão simulada
    porque a `api` pode já ter gravado a proposta seguinte quando um resultado é reentregue, e a
    reentrega não pode virar mais uma tentativa.
    """
    consulta = text(
        "SELECT r.origem = 'sugestao_adaptacao' AS regra_e_tentativa,"
        " (SELECT count(*) FROM regras s WHERE s.job_id = r.job_id"
        "  AND s.origem = 'sugestao_adaptacao' AND s.versao <= r.versao) AS feitas"
        " FROM regras r WHERE r.id = :regra_id AND r.job_id = :job_id"
    )
    parametros = {"regra_id": str(regra_id), "job_id": str(job_id)}
    async with sessoes() as sessao:
        resultado = await sessao.execute(consulta, parametros)
        # A versão foi lida por `load_rule` neste ciclo, e `regras` só recebe INSERT.
        linha = resultado.mappings().one()
    return TentativasDeTaxa(int(linha["feitas"]), bool(linha["regra_e_tentativa"]))
