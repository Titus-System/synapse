"""`derive_code` node: the code of a rate alternative, derived from the code already simulated.

Runs for every validated rule. A version that is not a `sugestao_adaptacao` goes on to
`code_generation` untouched. An alternative whose origin version has a code that succeeded in
the worker gets that code with the new rates in place of the old ones (`app/derivacao_codigo.py`),
without calling the model, and goes straight to `dispatch_execution`; when the code cannot be
derived, the model generates it as for any other version.

The derived code points at the prompt that produced the origin code: no prompt is sent and no
reply is recorded for it. The trail says the code was derived, not generated.
"""

from datetime import UTC, datetime
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import ConclusaoDaTrilha, EtapaAlterada, NoConcluido
from app.core.logger import get_logger, no_ctx
from app.core.metrics.global_metrics import derivacoes_codigo
from app.derivacao_codigo import pares_de_taxa, trocar_taxas
from app.graph.core.state import AgentState
from app.graph.nodes.code_generation import NO_GERACAO_CODIGO
from app.repositorio.artefatos import (
    buscar_codigo_simulado,
    gravar_codigo_derivado,
    id_do_evento_de_trilha,
)
from app.repositorio.regras import buscar_procedencia, buscar_regra

logger = get_logger("app.graph.nodes.derive_code")

DERIVADO = "derivado"
GERAR = "gerar"

RESUMO_DA_TRILHA = (
    "Código Python da alternativa derivado do código já simulado da versão de origem: as taxas "
    "da sugestão no lugar das anteriores, e nenhuma outra parte do código alterada."
)


async def derive_code(state: AgentState, config: RunnableConfig) -> AgentState:
    """Derive and record the alternative's code, or hand the version over to the model."""
    sessoes = config["configurable"]["sessoes"]
    job_id = UUID(state["job_id"])
    regra_id = UUID(state["regra_id"])
    procedencia = await buscar_procedencia(sessoes, job_id, regra_id)
    if procedencia.origem != "sugestao_adaptacao" or procedencia.regra_origem_id is None:
        return {"derivacao": GERAR}

    token = no_ctx.set(NO_GERACAO_CODIGO)
    try:
        origem = await buscar_codigo_simulado(sessoes, job_id, procedencia.regra_origem_id)
        if origem is None:
            return _gerar_pelo_modelo("sem_codigo_simulado")
        regra_de_origem = await buscar_regra(sessoes, job_id, procedencia.regra_origem_id)
        pares = pares_de_taxa(regra_de_origem.para_contrato(), state["representacao_regra"])
        if pares is None:
            return _gerar_pelo_modelo("regra_alterada")
        fonte = trocar_taxas(origem.fonte, pares)
        if fonte is None:
            return _gerar_pelo_modelo("taxas_nao_localizadas")

        producers = config["configurable"]["producers"]
        await producers.etapa_alterada(
            EtapaAlterada(job_id=job_id, etapa=NO_GERACAO_CODIGO, status="iniciada")
        )
        codigo_gerado_id = await gravar_codigo_derivado(
            sessoes, job_id=job_id, regra_id=regra_id, origem=origem, fonte=fonte
        )
        # Publicado antes de `executar-codigo`, como em `extract_code`: é a linha de
        # `simulacoes` que a api cria a partir dele que liga o job ao resultado do worker.
        await producers.no_concluido(
            NoConcluido(
                evento_id=id_do_evento_de_trilha(job_id, NO_GERACAO_CODIGO, codigo_gerado_id),
                job_id=job_id,
                no=NO_GERACAO_CODIGO,
                concluido_em=datetime.now(UTC),
                conclusao=ConclusaoDaTrilha(resumo=RESUMO_DA_TRILHA),
                regra_id=regra_id,
                prompt_id=origem.prompt_id,
                codigo_gerado_id=codigo_gerado_id,
            )
        )
        derivacoes_codigo.labels(desfecho=DERIVADO).inc()
        logger.info(
            "alternative code derived from the origin code",
            extra={
                "codigo_gerado_id": str(codigo_gerado_id),
                "codigo_origem_id": str(origem.id),
                "taxas_trocadas": len(pares),
            },
        )
        return {
            "derivacao": DERIVADO,
            "prompt_id": str(origem.prompt_id),
            "codigo_fonte": fonte,
            "codigo_gerado_id": str(codigo_gerado_id),
        }
    finally:
        no_ctx.reset(token)


def _gerar_pelo_modelo(motivo: str) -> AgentState:
    derivacoes_codigo.labels(desfecho=motivo).inc()
    logger.info("alternative code not derived; generating with the model", extra={"motivo": motivo})
    return {"derivacao": GERAR}
