"""`suggest_adaptation` node: propõe uma regra alternativa que caiba no orçamento.

A proposta é calculada sobre os totais que o worker apurou e gravada por quem é dona da
versão da regra - a `api` -, por este evento. Ela ainda não foi simulada aqui: a
arquitetura exige que a alternativa passe pela geração e pela execução antes de chegar ao
usuário (ARCHITECTURE.md §3.3).
"""

from datetime import UTC, datetime
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import (
    ConclusaoDaTrilha,
    EtapaAlterada,
    NoConcluido,
    NoGrafo,
    SugestaoAdaptacaoProposta,
)
from app.core.logger import get_logger
from app.graph.core.state import AgentState
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.resultados import buscar_totais
from app.representacao_regra import RepresentacaoRegra
from app.sugestao_adaptacao import MOTIVO_PROPOSTA, propor_alternativa

logger = get_logger("app.graph.nodes.suggest_adaptation")

ETAPA: NoGrafo = "sugestao_adaptacao"

RESUMO_PROPOSTA = (
    "Alternativa proposta com o percentual do núcleo ajustado ao orçamento do período; "
    "a versão nova é gravada pela api e simulada antes de ser exibida."
)
RESUMO_SEM_PROPOSTA = "Nenhuma alternativa a propor: a regra segue para revisão manual."


async def suggest_adaptation(state: AgentState, config: RunnableConfig) -> AgentState:
    """Compute the alternative from the recorded totals and hand it to the api."""
    job_id = UUID(state["job_id"])
    regra_id = UUID(state["regra_id"])
    resultado_id = UUID(state["resultado_id"])
    producers = config["configurable"]["producers"]
    sessoes = config["configurable"]["sessoes"]

    await producers.etapa_alterada(EtapaAlterada(job_id=job_id, etapa=ETAPA, status="iniciada"))

    totais = await buscar_totais(sessoes, job_id, resultado_id)
    alternativa = propor_alternativa(
        state["representacao_regra"], totais.simulado, totais.orcamento
    )

    if alternativa.representacao is not None:
        await producers.sugestao_adaptacao_proposta(
            SugestaoAdaptacaoProposta(
                job_id=job_id,
                regra_origem_id=regra_id,
                resultado_id=resultado_id,
                representacao=RepresentacaoRegra.model_validate(alternativa.representacao),
            )
        )
        logger.info("adaptation proposal published", extra={"no": ETAPA})

    # Por último, como no nó de delegação: o nó conclui quando a proposta foi entregue, e
    # anunciar antes afirmaria algo que ainda pode falhar. O motivo entra no resumo sem o
    # conteúdo da proposta - a trilha guarda referência, nunca artefato.
    await producers.no_concluido(
        NoConcluido(
            evento_id=id_do_evento_de_trilha(job_id, ETAPA, resultado_id),
            job_id=job_id,
            no=ETAPA,
            concluido_em=datetime.now(UTC),
            conclusao=ConclusaoDaTrilha(
                resumo=(
                    RESUMO_PROPOSTA
                    if alternativa.motivo == MOTIVO_PROPOSTA
                    else RESUMO_SEM_PROPOSTA
                )
            ),
            regra_id=regra_id,
        )
    )
    logger.info("node conclusion published", extra={"no": ETAPA, "motivo": alternativa.motivo})
    return {}
