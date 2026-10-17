"""Busca da meta com números do worker e estado recuperável entre candidatas."""

import time
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from langchain_core.runnables import RunnableConfig

from app.busca_meta import Ponto, escolher
from app.contratos.mensagens import (
    ConclusaoDaTrilha,
    MetaVendaSugerida,
    NoConcluido,
    SemSolucaoMeta,
)
from app.core.logger import get_logger, no_ctx
from app.core.metrics.global_metrics import (
    busca_meta_candidatos,
    busca_meta_espera,
    busca_meta_processamento,
    buscas_meta,
)
from app.graph.core.state import AgentState, BuscaMeta, PontoBusca
from app.repositorio.encerramentos import foi_encerrado
from app.repositorio.resultados import buscar_execucao_da_meta

logger = get_logger("app.graph.nodes.search_sales_target")


async def search_sales_target(state: AgentState, config: RunnableConfig) -> AgentState:
    token = no_ctx.set("search_sales_target")
    try:
        with busca_meta_processamento.time():
            try:
                return await _avaliar(state, config)
            except Exception as erro:
                logger.warning(
                    "sales target processing failed",
                    extra={
                        "operacao": "avaliacao",
                        "classe": type(erro).__name__,
                    },
                )
                raise
    finally:
        no_ctx.reset(token)


async def _avaliar(state: AgentState, config: RunnableConfig) -> AgentState:
    sessoes = config["configurable"]["sessoes"]
    job_id = UUID(state["job_id"])
    anterior = state.get("busca_meta")
    busca: BuscaMeta = (
        anterior.copy()
        if anterior is not None
        else {
            "pontos": [],
            "pendente": None,
            "motivo": None,
            "vencedora": None,
            "iniciada_em": time.time(),
            "enviada_em": 0,
            "encerrada": False,
        }
    )
    resultado_id = state["resultado_id"]
    execucao = await buscar_execucao_da_meta(sessoes, job_id, UUID(resultado_id))
    orcamento = Decimal(state["orcamento"])
    meta = execucao.meta if execucao.meta is not None else execucao.vendas_historicas
    if anterior is not None:
        busca_meta_espera.observe(max(0, time.time() - busca["enviada_em"]))
        logger.info("sales target result received", extra={"resultado_id": resultado_id})
    else:
        logger.info("sales target search started", extra={"regra_id": state["regra_id"]})
    if (
        execucao.status != "sucesso"
        or execucao.simulado is None
        or not execucao.simulado.is_finite()
        or meta is None
        or not meta.is_finite()
        or meta <= 0
        or execucao.orcamento != orcamento
    ):
        busca["motivo"] = "falha_execucao"
        busca["pendente"] = None
        return {"busca_meta": busca}
    ponto: PontoBusca = {
        "meta": str(meta),
        "comissao": str(execucao.simulado),
        "resultado_id": resultado_id,
    }
    busca["pontos"] = [*busca["pontos"], ponto]
    passo = escolher(
        [
            Ponto(Decimal(p["meta"]), Decimal(p["comissao"]), p["resultado_id"])
            for p in busca["pontos"]
        ],
        orcamento,
    )
    busca["pendente"] = str(passo.candidata) if passo.candidata is not None else None
    busca["motivo"] = passo.motivo
    busca["vencedora"] = passo.vencedora.resultado_id if passo.vencedora else None
    return {"busca_meta": busca}


async def cancelada(state: AgentState, config: RunnableConfig) -> bool:
    if await foi_encerrado(config["configurable"]["sessoes"], UUID(state["job_id"])):
        buscas_meta.labels(desfecho="cancelada", motivo="job_encerrado").inc()
        logger.info("sales target search cancelled", extra={"regra_id": state["regra_id"]})
        return True
    return False


async def publish_sales_target(state: AgentState, config: RunnableConfig) -> AgentState:
    token = no_ctx.set("search_sales_target")
    try:
        with busca_meta_processamento.time():
            try:
                return await _publicar(state, config)
            except Exception as erro:
                logger.warning(
                    "sales target processing failed",
                    extra={
                        "operacao": "publicacao",
                        "classe": type(erro).__name__,
                    },
                )
                raise
    finally:
        no_ctx.reset(token)


async def _publicar(state: AgentState, config: RunnableConfig) -> AgentState:
    busca: BuscaMeta = state["busca_meta"].copy()
    busca["encerrada"] = True
    if await cancelada(state, config):
        return {"busca_meta": busca}
    job_id, regra_id = UUID(state["job_id"]), UUID(state["regra_id"])
    evento = MetaVendaSugerida(job_id=job_id, regra_id=regra_id)
    if busca["vencedora"] is not None:
        vencedora = next(p for p in busca["pontos"] if p["resultado_id"] == busca["vencedora"])
        evento.meta_venda = Decimal(vencedora["meta"])
        evento.resultado_id = UUID(vencedora["resultado_id"])
        desfecho, motivo = "sugerida", "encontrada"
        resumo = "Busca concluída com uma meta maior simulada dentro do orçamento."
    else:
        evento.sem_solucao = SemSolucaoMeta.model_validate({"motivo": busca["motivo"]})
        desfecho, motivo = "sem_solucao", evento.sem_solucao.motivo
        resumo = {
            "nao_monotonica": "Busca encerrada: a comissão não foi monotônica nas metas simuladas.",
            "intervalo_esgotado": "Busca encerrada sem meta maior no intervalo pesquisado.",
            "falha_execucao": "Busca encerrada: uma candidata não produziu resultado válido.",
        }[motivo]
    producers = config["configurable"]["producers"]
    await producers.meta_venda_sugerida(evento)
    await producers.no_concluido(
        NoConcluido(
            evento_id=uuid5(NAMESPACE_URL, f"synapse:{job_id}:{regra_id}:busca_meta"),
            job_id=job_id,
            regra_id=regra_id,
            no="decisao",
            concluido_em=datetime.now(UTC),
            conclusao=ConclusaoDaTrilha(resumo=resumo),
        )
    )
    buscas_meta.labels(desfecho=desfecho, motivo=motivo).inc()
    busca_meta_candidatos.observe(len(busca["pontos"]) - 1 + (motivo == "falha_execucao"))
    logger.info(
        "sales target search finished",
        extra={
            "regra_id": str(regra_id),
            "desfecho": desfecho,
            "motivo": motivo,
            "resultado_id": busca["vencedora"],
        },
    )
    return {"busca_meta": busca}
