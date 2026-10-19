"""`suggest_adaptation` node: propõe uma regra alternativa que caiba no orçamento.

A proposta é calculada sobre os totais que o worker apurou e gravada por quem é dona da
versão da regra - a `api` -, por este evento. Ela ainda não foi simulada aqui: a
arquitetura exige que a alternativa passe pela geração e pela execução antes de chegar ao
usuário (ARCHITECTURE.md §3.3).

Cada taxa nova é uma tentativa com ciclo próprio, e a alternativa que não coube volta aqui
pela decisão. Este nó aplica o limite de tentativas e é o único que anuncia que a iteração
terminou sem alternativa (T-271).
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
from app.core.metrics.global_metrics import tentativas_de_taxa
from app.graph.core.state import AgentState
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.resultados import buscar_taxas_simuladas, buscar_totais
from app.representacao_regra import RepresentacaoRegra
from app.sugestao_adaptacao import (
    LIMITE_DE_TENTATIVAS,
    MOTIVO_INCOERENTE,
    MOTIVO_LIMITE,
    MOTIVO_NAO_SUPORTADA,
    MOTIVO_PROPOSTA,
    MOTIVO_SEM_MARGEM,
    Alternativa,
    propor_alternativa,
)

logger = get_logger("app.graph.nodes.suggest_adaptation")

ETAPA: NoGrafo = "sugestao_adaptacao"

RESUMO_PROPOSTA = (
    "Alternativa proposta com o percentual do núcleo ajustado ao orçamento do período; "
    "a versão nova é gravada pela api e simulada antes de ser exibida."
)
#: O que a trilha registra de cada motivo, sem o conteúdo da proposta nem número algum.
RESUMOS = {
    MOTIVO_PROPOSTA: RESUMO_PROPOSTA,
    MOTIVO_SEM_MARGEM: (
        "Nenhuma taxa nova a propor: não há como estimar uma taxa menor que caiba no orçamento."
    ),
    MOTIVO_INCOERENTE: "Nenhuma taxa nova a propor: a taxa estimada deixaria a regra incoerente.",
    MOTIVO_NAO_SUPORTADA: (
        "Nenhuma taxa nova a propor: a adaptação só ajusta a taxa de regras sem especificações."
    ),
    MOTIVO_LIMITE: (
        "Nenhuma taxa nova a propor: as três tentativas simuladas não couberam no orçamento."
    ),
}


async def suggest_adaptation(state: AgentState, config: RunnableConfig) -> AgentState:
    """Propose the next rate from the recorded totals, or announce there is none to try."""
    job_id = UUID(state["job_id"])
    regra_id = UUID(state["regra_id"])
    resultado_id = UUID(state["resultado_id"])
    producers = config["configurable"]["producers"]
    sessoes = config["configurable"]["sessoes"]
    # Vem do checkpoint da decisão, então a reentrega numera igual. Sem ela, o ciclo parou
    # antes de a decisão contar, quando só chegava aqui o job ainda sem sugestão.
    feitas = state.get("tentativas_de_taxa", 0)
    tentativa = feitas + 1

    await producers.etapa_alterada(EtapaAlterada(job_id=job_id, etapa=ETAPA, status="iniciada"))

    if tentativa > LIMITE_DE_TENTATIVAS:
        alternativa = Alternativa(MOTIVO_LIMITE)
    else:
        totais = await buscar_totais(sessoes, job_id, resultado_id)
        # O método sai das taxas da cadeia, e não do número da tentativa, que é do job: a regra
        # que não veio de uma sugestão começa pelos totais mesmo depois de outras tentativas.
        anteriores = await buscar_taxas_simuladas(sessoes, job_id, regra_id)
        alternativa = propor_alternativa(
            state["representacao_regra"],
            totais.simulado,
            totais.orcamento,
            baseline=totais.baseline,
            anteriores=anteriores,
        )

    if alternativa.representacao is not None:
        await producers.sugestao_adaptacao_proposta(
            SugestaoAdaptacaoProposta(
                job_id=job_id,
                regra_origem_id=regra_id,
                resultado_id=resultado_id,
                representacao=RepresentacaoRegra.model_validate(alternativa.representacao),
                tentativa=tentativa,
            )
        )
        logger.info(
            "adaptation proposal published",
            extra={"no": ETAPA, "tentativa": tentativa, "metodo": alternativa.metodo},
        )
    else:
        # Estrutural como a proposta: é o que encerra a iteração na `api`, que não espera outra
        # tentativa depois dele. Vai antes do `no-concluido`, pelo mesmo motivo.
        await producers.etapa_alterada(
            EtapaAlterada(job_id=job_id, etapa=ETAPA, status="sem_alternativa")
        )
        logger.info(
            "adaptation iteration ended without alternative",
            extra={"no": ETAPA, "motivo": alternativa.motivo, "tentativas_de_taxa": feitas},
        )

    # Por último, como no nó de delegação: o nó conclui quando a proposta foi entregue, e
    # anunciar antes afirmaria algo que ainda pode falhar. O motivo entra no resumo sem o
    # conteúdo da proposta - a trilha guarda referência, nunca artefato.
    await producers.no_concluido(
        NoConcluido(
            evento_id=id_do_evento_de_trilha(job_id, ETAPA, resultado_id),
            job_id=job_id,
            no=ETAPA,
            concluido_em=datetime.now(UTC),
            conclusao=ConclusaoDaTrilha(resumo=RESUMOS[alternativa.motivo]),
            regra_id=regra_id,
        )
    )
    # A proposta tem o desfecho na simulação, que a decisão conta, e o limite não é uma
    # tentativa nova: a terceira já foi contada como inviável.
    if alternativa.motivo not in (MOTIVO_PROPOSTA, MOTIVO_LIMITE):
        tentativas_de_taxa.labels(tentativa=str(tentativa), desfecho=alternativa.motivo).inc()
    logger.info(
        "node conclusion published",
        extra={"no": ETAPA, "motivo": alternativa.motivo, "tentativas_de_taxa": feitas},
    )
    return {}
