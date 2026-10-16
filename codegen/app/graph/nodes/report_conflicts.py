"""Hand the domain conflicts to the api and end the cycle.

A rule with conflicts waits for the user's correction, and the api owns that wait (the job and
the correction round). The cycle publishes the pause and finishes; it does not fail the job.
"""

from asyncio import CancelledError
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import ConflitoDaRodada, EtapaAlterada, NoGrafo
from app.core.logger import get_logger, no_ctx
from app.core.metrics.global_metrics import job_duration, job_failures, job_runs
from app.graph.core.state import AgentState

logger = get_logger("app.graph.nodes.report_conflicts")
ETAPA: NoGrafo = "confirmacao"


def _classe_da_falha(erro: BaseException) -> str:
    """Classify by type only: the exception text can carry broker details."""
    if isinstance(erro, TimeoutError):
        return "timeout"
    if isinstance(erro, ConnectionError):
        return "conexao"
    return "falha_na_operacao"


async def report_conflicts(state: AgentState, config: RunnableConfig) -> AgentState:
    """Publish the pause with the conflicts `validate_domain` recorded, as the last thing done.

    A rerun after a crash publishes the pause again; the api opens one round per `regra_id`.
    """
    token = no_ctx.set(ETAPA)
    job_runs.labels(job_name="report_conflicts").inc()
    try:
        with job_duration.labels(job_name="report_conflicts").time():
            conflitos = state["conflitos"]
            await config["configurable"]["producers"].etapa_alterada(
                EtapaAlterada(
                    job_id=UUID(state["job_id"]),
                    etapa=ETAPA,
                    status="aguardando_correcao",
                    regra_id=UUID(state["regra_id"]),
                    conflitos=[
                        ConflitoDaRodada(elementos=conflito["elementos"], motivo=conflito["motivo"])
                        for conflito in conflitos
                    ],
                )
            )
            elementos = list(dict.fromkeys(e for c in conflitos for e in c["elementos"]))
            logger.info(
                "domain conflicts published",
                extra={"quantidade_conflitos": len(conflitos), "elementos": elementos},
            )
            return {}
    except (Exception, CancelledError) as erro:
        job_failures.labels(job_name="report_conflicts").inc()
        if isinstance(erro, CancelledError):
            logger.error("conflict report failed", extra={"classe": "cancelamento"})
            # Recreated with a fixed message: a cancellation can still carry arbitrary content.
            raise CancelledError("Conflict report cancelled") from None
        logger.error("conflict report failed", extra={"classe": _classe_da_falha(erro)})
        # A validation error can echo a conflict reason, which carries rule values; the
        # boundary gets only a fixed error and requeues the message.
        raise RuntimeError("Conflict report failed") from None
    finally:
        no_ctx.reset(token)
