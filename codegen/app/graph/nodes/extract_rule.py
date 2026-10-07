"""Extract a submission and publish its persisted reference to the api."""

import asyncio
from collections import Counter
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from httpx import NetworkError, TimeoutException
from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import (
    ConclusaoDaTrilha,
    EtapaAlterada,
    NoConcluido,
    NoGrafo,
    RegraExtraida,
)
from app.core.logger import get_logger, job_id_ctx, no_ctx
from app.core.metrics.global_metrics import (
    CONSTRUTOS_DA_EXTRACAO,
    elementos_extraidos,
    falhas_extracao,
    job_duration,
    job_failures,
    job_runs,
    rebaixamentos_extracao,
)
from app.extracao.modelos import FalhaExtracaoError
from app.extracao.motor import extrair_regra
from app.falhas import FalhaDoJobError
from app.graph.core.llm import registry
from app.graph.core.state import AgentState
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.extracoes import buscar_extracao, gravar_extracao
from app.repositorio.submissoes import TranscricaoIndisponivelError, buscar_transcricao

ETAPA: NoGrafo = "extracao_parametros"
logger = get_logger("app.graph.nodes.extract_rule")


class EntradaExtracaoInvalidaError(FalhaDoJobError):
    etapa = ETAPA


class FalhaTransitoriaExtracaoError(RuntimeError):
    """Sanitized infrastructure failure; the consumer retries the message."""


def _motivo_da_falha(erro: BaseException, classe: str) -> str:
    # Classify by type: exception text can contain artifacts or credentials.
    if isinstance(erro, FalhaDoJobError | asyncio.CancelledError):
        return classe
    if isinstance(erro, TimeoutError | TimeoutException):
        return "timeout"
    if isinstance(erro, ConnectionError | NetworkError):
        return "conexao"
    return "falha_na_operacao"


async def extract_rule(state: AgentState, config: RunnableConfig) -> AgentState:
    job_id = UUID(state["job_id"])
    token_job = job_id_ctx.set(str(job_id))
    token_no = no_ctx.set(ETAPA)
    inicio = perf_counter()
    job_runs.labels(job_name="extract_rule").inc()
    logger.info("extraction started")
    classe = "publicacao"
    operacao = "publicar_etapa_alterada"
    extracao_reutilizada = False
    try:
        producers = config["configurable"]["producers"]
        sessoes = config["configurable"]["sessoes"]
        await producers.etapa_alterada(EtapaAlterada(job_id=job_id, etapa=ETAPA, status="iniciada"))
        classe = "entrada_invalida"
        operacao = "validar_entrada"
        if (
            state.get("regra_id")
            or state.get("origem") not in ("voz", "texto")
            or not state.get("submissao_id")
        ):
            raise EntradaExtracaoInvalidaError("Invalid extraction input")
        submissao_id = UUID(state["submissao_id"])
        classe = "persistencia"
        operacao = "buscar_transcricao"
        texto = await buscar_transcricao(sessoes, submissao_id)
        operacao = "buscar_extracao"
        salvo = await buscar_extracao(sessoes, job_id=job_id, submissao_id=submissao_id)
        extracao_reutilizada = salvo is not None
        if salvo is None:
            classe = "provedor"
            operacao = "carregar_modelo"
            modelo = registry.get_model("extraction")
            metadados_modelo = registry.get_model_metadata("extraction")
            operacao = "extrair_regra"
            resultado = await extrair_regra(
                texto,
                state["competencias"],
                modelo=modelo,
                metadados_modelo=metadados_modelo,
            )
            classe = "persistencia"
            operacao = "gravar_extracao"
            salvo = await gravar_extracao(
                sessoes,
                job_id=job_id,
                submissao_id=submissao_id,
                resultado=resultado,
            )
        classe = "publicacao"
        operacao = "publicar_regra_extraida"
        await producers.regra_extraida(
            RegraExtraida(job_id=job_id, submissao_id=submissao_id, extracao_id=salvo.id)
        )
        regra: dict[str, Any] = salvo.representacao.para_contrato()
        referencias = [f"nucleo.{campo}" for campo in regra["nucleo"]]
        referencias.extend(e["ref"] for e in regra["especificacoes"])
        operacao = "publicar_no_concluido"
        await producers.no_concluido(
            NoConcluido(
                evento_id=id_do_evento_de_trilha(job_id, ETAPA, salvo.id),
                job_id=job_id,
                no=ETAPA,
                concluido_em=datetime.now(UTC),
                prompt_id=salvo.prompt_id,
                conclusao=ConclusaoDaTrilha(
                    resumo="Regra extraída e persistida; referência entregue à api.",
                    fontes=["submissoes.transcricao"],
                    elementos_extraidos=referencias,
                ),
            )
        )
        contagens = Counter(
            e["construto"] if e["construto"] in CONSTRUTOS_DA_EXTRACAO else "outro"
            for e in regra["especificacoes"]
        )
        contagens["nucleo"] = len(regra["nucleo"])
        rebaixamentos = Counter(r.motivo for r in salvo.rebaixamentos)
        for construto, quantidade in contagens.items():
            elementos_extraidos.labels(construto=construto).inc(quantidade)
        for motivo, quantidade in rebaixamentos.items():
            rebaixamentos_extracao.labels(motivo=motivo).inc(quantidade)
        logger.info(
            "extraction finished",
            extra={
                "extracao_id": str(salvo.id),
                "extracao_reutilizada": extracao_reutilizada,
                "elementos_por_construto": dict(contagens),
                "rebaixamentos_por_motivo": dict(rebaixamentos),
            },
        )
        return {"prompt_id": str(salvo.prompt_id), "resposta_id": str(salvo.resposta_id)}
    except (asyncio.CancelledError, Exception) as erro:
        if isinstance(erro, TranscricaoIndisponivelError):
            classe = "transcricao_indisponivel"
        elif isinstance(erro, FalhaExtracaoError):
            classe = "saida_invalida"
        elif isinstance(erro, asyncio.CancelledError):
            classe = "cancelamento"
        job_failures.labels(job_name="extract_rule").inc()
        falhas_extracao.labels(classe=classe).inc()
        logger.warning(
            "extraction failed",
            extra={
                "classe": classe,
                "motivo": _motivo_da_falha(erro, classe),
                "operacao": operacao,
                "extracao_reutilizada": extracao_reutilizada,
            },
        )
        if isinstance(erro, FalhaDoJobError | asyncio.CancelledError):
            raise
    finally:
        job_duration.labels(job_name="extract_rule").observe(perf_counter() - inicio)
        no_ctx.reset(token_no)
        job_id_ctx.reset(token_job)
    raise FalhaTransitoriaExtracaoError("Extraction infrastructure unavailable")
