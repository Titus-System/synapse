"""Deterministic domain validation before code generation."""

from asyncio import CancelledError
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contratos.mensagens import ConclusaoDaTrilha, NoConcluido, NoGrafo
from app.core.logger import get_logger, no_ctx
from app.core.metrics.global_metrics import (
    conflitos_validacao_dominio,
    job_duration,
    job_failures,
    job_runs,
    resultados_validacao_dominio,
)
from app.extracao.vocabulario import carregar_vocabulario
from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState, ConflitoDominio
from app.nos import validacao_dominio
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.extracoes import parametros_sem_lastro
from app.tipos_estado import ValorRegra

logger = get_logger("app.graph.nodes.validate_domain")
ETAPA: NoGrafo = "validacao_dominio"


def _classe_da_falha(erro: BaseException) -> str:
    """Classify by type only: the exception text can carry rule values or broker details."""
    if isinstance(erro, TimeoutError):
        return "timeout"
    if isinstance(erro, ConnectionError):
        return "conexao"
    return "falha_na_operacao"


def parametros_do_job(state: AgentState) -> dict[str, ValorRegra]:
    """Os parâmetros da simulação que a mensagem trouxe, com os números em `Decimal`.

    O estado os guarda como texto decimal. Ausência fica explícita para a validação pedir
    os parâmetros obrigatórios antes de liberar uma nova simulação.
    """
    parametros: dict[str, ValorRegra] = {}
    if "competencias" in state:
        competencias: list[ValorRegra] = list(state["competencias"])
        parametros["competencias"] = competencias
    if "orcamento" in state:
        parametros["orcamento"] = Decimal(state["orcamento"])
    if "meta_venda" in state:
        parametros["meta_venda"] = Decimal(state["meta_venda"])
    return parametros


async def verificar_versao(
    sessoes: async_sessionmaker[AsyncSession],
    job_id: UUID,
    regra_id: UUID,
    representacao: Mapping[str, object],
    parametros: Mapping[str, ValorRegra],
) -> validacao_dominio.ResultadoValidacao:
    """A validação de domínio da versão `regra_id`, com os parâmetros do job (T-280).

    A reextração recalcula por aqui os conflitos que a correção responde, para chegar ao mesmo
    resultado que esta validação gravou na rodada.
    """
    sem_lastro = await parametros_sem_lastro(sessoes, job_id, regra_id)
    return validacao_dominio.verificar(
        representacao,
        parametros,
        competencias_publicadas=carregar_vocabulario()["competencias_publicadas"],
        sem_lastro=sem_lastro,
    )


async def validate_domain(state: AgentState, config: RunnableConfig) -> AgentState:
    token = no_ctx.set(ETAPA)
    job_runs.labels(job_name="validate_domain").inc()
    try:
        with job_duration.labels(job_name="validate_domain").time():
            logger.info("domain validation started")
            job_id, regra_id = UUID(state["job_id"]), UUID(state["regra_id"])
            validacao = await verificar_versao(
                config["configurable"]["sessoes"],
                job_id,
                regra_id,
                state["representacao_regra"],
                parametros_do_job(state),
            )
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
            codigos = [conflito.codigo.value for conflito in validacao.conflitos]
            for codigo in codigos:
                conflitos_validacao_dominio.labels(codigo=codigo).inc()
            logger.info(
                "domain validation finished",
                extra={
                    "resultado": resultado,
                    "quantidade_conflitos": len(conflitos),
                    "elementos": elementos,
                    "codigos": codigos,
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
