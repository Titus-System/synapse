"""Read-only access to `resultados_simulacao`, for the nodes that decide about a result.

Only `SELECT`: the row is written by the `worker`, that runs the code and apura os números
(migration `010-cria-resultados-simulacao.sql`). Nada aqui recalcula um total - o evento
traz referência, e o número vem da linha que o worker gravou (ADR-001).
"""

from decimal import Decimal
from uuid import UUID

import simplejson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.falhas import FalhaDoJobError


class ResultadoIndisponivelError(FalhaDoJobError):
    """O resultado referenciado não existe para este job, ou não tem totais utilizáveis.

    Nunca carrega conteúdo do resultado - só a etapa. Uma reentrega não faz a linha
    aparecer nem completar os totais, então a falha é permanente.
    """

    etapa = "sugestao_adaptacao"


class TotaisDaSimulacao:
    """O par que a adaptação precisa: o que a regra custou e o teto que ela furou."""

    __slots__ = ("orcamento", "simulado")

    def __init__(self, simulado: Decimal, orcamento: Decimal) -> None:
        self.simulado = simulado
        self.orcamento = orcamento


def _decimal(valor: object) -> Decimal | None:
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, int) and not isinstance(valor, bool):
        return Decimal(valor)
    return None


async def buscar_totais(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, resultado_id: UUID
) -> TotaisDaSimulacao:
    """Load `totais.simulado` and `totais.orcamento` from the worker's result row.

    Raises `ResultadoIndisponivelError` when the row is missing for that job or when either
    total is absent - o que acontece em todo desfecho que não é `sucesso`.
    """
    # `::text` pelo mesmo motivo de `buscar_regra`: sem o cast o driver decodifica o jsonb
    # com float, e o total viraria um número aproximado.
    consulta = text(
        "SELECT totais::text AS totais FROM resultados_simulacao"
        " WHERE id = :resultado_id AND job_id = :job_id"
    )
    parametros = {"resultado_id": str(resultado_id), "job_id": str(job_id)}
    async with sessoes() as sessao:
        resultado = await sessao.execute(consulta, parametros)
        linha = resultado.mappings().one_or_none()

    if linha is None:
        raise ResultadoIndisponivelError("Simulation result not found for this job")

    bruto = linha["totais"]
    totais = simplejson.loads(bruto, use_decimal=True) if isinstance(bruto, str) else bruto
    if not isinstance(totais, dict):
        raise ResultadoIndisponivelError("Simulation result has no totals")

    simulado = _decimal(totais.get("simulado"))
    orcamento = _decimal(totais.get("orcamento"))
    if simulado is None or orcamento is None:
        raise ResultadoIndisponivelError("Simulation result is missing simulado/orcamento")
    return TotaisDaSimulacao(simulado, orcamento)
