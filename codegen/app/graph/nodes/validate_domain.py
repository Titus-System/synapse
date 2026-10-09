"""Deterministic domain validation before code generation."""

from asyncio import CancelledError
from datetime import UTC, datetime
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import ConclusaoDaTrilha, NoConcluido, NoGrafo
from app.core.logger import get_logger, no_ctx
from app.core.metrics.global_metrics import (
    job_duration,
    job_failures,
    job_runs,
    resultados_validacao_dominio,
)
from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState, ConflitoDominio
from app.nos import validacao_dominio
from app.repositorio.artefatos import id_do_evento_de_trilha

logger = get_logger("app.graph.nodes.validate_domain")
ETAPA: NoGrafo = "validacao_dominio"


def _classe_da_falha(erro: BaseException) -> str:
    """Classify by type only: the exception text can carry rule values or broker details."""
    if isinstance(erro, TimeoutError):
        return "timeout"
    if isinstance(erro, ConnectionError):
        return "conexao"
    return "falha_na_operacao"


async def validate_domain(state: AgentState, config: RunnableConfig) -> AgentState:
    token = no_ctx.set(ETAPA)
    job_runs.labels(job_name="validate_domain").inc()
    try:
        with job_duration.labels(job_name="validate_domain").time():
            logger.info("domain validation started")
            validacao = validacao_dominio.verificar(state["representacao_regra"])
            conflitos: list[ConflitoDominio] = [
                {"elementos": list(conflito.elementos), "motivo": conflito.motivo}
                for conflito in validacao.conflitos
            ]
            elementos = list(dict.fromkeys(e for c in conflitos for e in c["elementos"]))
            resultado = "liberada" if validacao.liberado else "barrada"
            resumo = (
                "Regra liberada pela validação de domínio."
                if validacao.liberado
                else (
                    f"Regra barrada: {len(conflitos)} conflito(s). "
                    f"Elementos: {', '.join(elementos)}."
                )
            )
            job_id, regra_id = UUID(state["job_id"]), UUID(state["regra_id"])
            await config["configurable"]["producers"].no_concluido(
                NoConcluido(
                    evento_id=id_do_evento_de_trilha(job_id, ETAPA, regra_id),
                    job_id=job_id,
                    no=ETAPA,
                    concluido_em=datetime.now(UTC),
                    conclusao=ConclusaoDaTrilha(resumo=resumo),
                    regra_id=regra_id,
                )
            )
            resultados_validacao_dominio.labels(resultado=resultado).inc()
            logger.info(
                "domain validation finished",
                extra={
                    "resultado": resultado,
                    "quantidade_conflitos": len(conflitos),
                    "elementos": elementos,
                },
            )
            return {"regra_liberada": validacao.liberado, "conflitos": conflitos}
    except (Exception, CancelledError) as erro:
        job_failures.labels(job_name="validate_domain").inc()
        if isinstance(erro, FalhaDoJobError):
            # A permanent failure keeps its type and etapa - never masked as transient.
            logger.error("domain validation failed", extra={"classe": "falha_do_job"})
            raise
        if isinstance(erro, CancelledError):
            logger.error("domain validation failed", extra={"classe": "cancelamento"})
            # Recreated with a fixed message: a cancellation can still carry arbitrary content.
            raise CancelledError("Domain validation cancelled") from None
        classe = _classe_da_falha(erro)
        logger.error("domain validation failed", extra={"classe": classe})
        # Provider/database exceptions can carry rule values; the boundary gets only a fixed error.
        raise RuntimeError("Domain validation failed") from None
    finally:
        no_ctx.reset(token)
