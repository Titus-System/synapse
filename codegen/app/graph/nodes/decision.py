"""`decision` node: encaminha o job conforme o veredito que o worker apurou.

O encaminhamento sai de um campo validado do estado, nunca de texto de modelo: resposta de
LLM não decide qual nó roda em seguida (AGENTS.md - Security). A aresta que lê este campo
vive em `engine.py`, como todas as outras.
"""

from datetime import UTC, datetime
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import (
    ConclusaoDaTrilha,
    EtapaAlterada,
    NoConcluido,
    NoGrafo,
    Veredito,
)
from app.core.logger import get_logger
from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState
from app.repositorio.artefatos import id_do_evento_de_trilha

logger = get_logger("app.graph.nodes.decision")

ETAPA: NoGrafo = "decisao"

#: Para onde o fluxo seguiu, no campo `encaminhamento` da trilha (US04).
ENCAMINHAMENTO_SUGESTAO = "sugestao_adaptacao"
ENCAMINHAMENTO_FIM = "fim"

# O resumo não repete o veredito: ele já está em `resultados_simulacao.veredito`, e a
# trilha registra o que o nó concluiu, não o que a linha vizinha já alcança.
RESUMO_SUGESTAO = "Fluxo encaminhado para a sugestão de adaptação da regra."
RESUMO_FIM = "Fluxo encerrado no codegen: não há adaptação a propor para este desfecho."


class DecisaoSemResultadoError(FalhaDoJobError):
    """A retomada não trouxe o resultado, então não há desfecho para encaminhar.

    Uma reentrega não inventa a referência que faltou, então a falha é permanente.
    """

    etapa = ETAPA


async def decision(state: AgentState, config: RunnableConfig) -> AgentState:
    """Publish where the flow goes, and record it in the audit trail."""
    resultado_id = state.get("resultado_id")
    if resultado_id is None:
        raise DecisaoSemResultadoError("resume carried no resultado_id")

    job_id = UUID(state["job_id"])
    encaminhamento = (
        ENCAMINHAMENTO_SUGESTAO
        if state.get("veredito") == Veredito.INVIAVEL
        else ENCAMINHAMENTO_FIM
    )
    producers = config["configurable"]["producers"]

    await producers.etapa_alterada(EtapaAlterada(job_id=job_id, etapa=ETAPA, status="iniciada"))
    await producers.no_concluido(
        NoConcluido(
            evento_id=id_do_evento_de_trilha(job_id, ETAPA, UUID(resultado_id)),
            job_id=job_id,
            no=ETAPA,
            concluido_em=datetime.now(UTC),
            conclusao=ConclusaoDaTrilha(
                resumo=(
                    RESUMO_SUGESTAO if encaminhamento == ENCAMINHAMENTO_SUGESTAO else RESUMO_FIM
                ),
                encaminhamento=encaminhamento,
            ),
            regra_id=UUID(state["regra_id"]),
        )
    )
    logger.info("node conclusion published", extra={"no": ETAPA})
    return {"encaminhamento": encaminhamento}
