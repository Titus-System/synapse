"""`decision` node: encaminha o job conforme o veredito que o worker apurou.

O encaminhamento sai de um campo validado do estado, nunca de texto de modelo: resposta de
LLM não decide qual nó roda em seguida (AGENTS.md - Security). A aresta que lê este campo
vive em `engine.py`, como todas as outras.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.config import get_settings
from app.contratos.mensagens import (
    ConclusaoDaTrilha,
    EtapaAlterada,
    NoConcluido,
    NoGrafo,
    Veredito,
)
from app.core.logger import get_logger
from app.core.metrics.global_metrics import TENTATIVAS_DE_TAXA, tentativas_de_taxa
from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.regras import contar_tentativas
from app.repositorio.resultados import buscar_execucao_da_meta

logger = get_logger("app.graph.nodes.decision")

ETAPA: NoGrafo = "decisao"

#: Para onde o fluxo seguiu, no campo `encaminhamento` da trilha (US04).
ENCAMINHAMENTO_SUGESTAO = "sugestao_adaptacao"
ENCAMINHAMENTO_FIM = "fim"
ENCAMINHAMENTO_META = "busca_meta"

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
    """Publish where the flow goes, and record it in the audit trail.

    A regra inviável só de núcleo vai à sugestão em toda tentativa, e é a sugestão que aplica
    o limite delas: assim só ela anuncia que a iteração terminou sem alternativa (T-271).
    """
    resultado_id = state.get("resultado_id")
    if resultado_id is None:
        raise DecisaoSemResultadoError("resume carried no resultado_id")

    job_id = UUID(state["job_id"])
    veredito = state.get("veredito")
    # Sem veredito não há tentativa a contar: o job sem orçamento e a simulação que falhou
    # terminam aqui.
    tentativas = (
        await contar_tentativas(config["configurable"]["sessoes"], job_id, UUID(state["regra_id"]))
        if state.get("status_simulacao") == "sucesso" and veredito is not None
        else None
    )
    encaminhamento = (
        ENCAMINHAMENTO_SUGESTAO
        if tentativas is not None
        and veredito == Veredito.INVIAVEL
        and not state["representacao_regra"].get("especificacoes")
        else ENCAMINHAMENTO_FIM
    )
    if (
        get_settings().BUSCA_META_ENABLED
        and "busca_meta" not in state
        and state.get("status_simulacao") == "sucesso"
        and veredito == Veredito.VIAVEL
        and state.get("orcamento") is not None
        and not state["representacao_regra"].get("especificacoes")
    ):
        execucao = await buscar_execucao_da_meta(
            config["configurable"]["sessoes"], job_id, UUID(resultado_id)
        )
        base = execucao.meta if execucao.meta is not None else execucao.vendas_historicas
        if (
            execucao.proposito == "simulacao"
            and execucao.status == "sucesso"
            and execucao.regra_id == UUID(state["regra_id"])
            and execucao.codigo_id == UUID(state["codigo_gerado_id"])
            and execucao.orcamento == Decimal(state["orcamento"])
            and execucao.simulado is not None
            and execucao.simulado.is_finite()
            and execucao.simulado < Decimal(state["orcamento"])
            and base is not None
            and base.is_finite()
            and base > 0
        ):
            encaminhamento = ENCAMINHAMENTO_META
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
                    {
                        ENCAMINHAMENTO_SUGESTAO: RESUMO_SUGESTAO,
                        ENCAMINHAMENTO_META: "Fluxo encaminhado para a busca de uma meta maior.",
                    }.get(encaminhamento, RESUMO_FIM)
                ),
                encaminhamento=encaminhamento,
            ),
            regra_id=UUID(state["regra_id"]),
        )
    )
    if (
        tentativas is not None
        and tentativas.regra_e_tentativa
        and str(tentativas.feitas) in TENTATIVAS_DE_TAXA
    ):
        # O desfecho da alternativa que esta simulação testou.
        tentativas_de_taxa.labels(tentativa=str(tentativas.feitas), desfecho=veredito).inc()
    # A presença dos parâmetros, nunca o valor que o usuário disse. A do orçamento explica o
    # encaminhamento: sem ele não há veredito e o fluxo termina (T-281).
    contexto: dict[str, object] = {
        "no": ETAPA,
        "encaminhamento": encaminhamento,
        "com_orcamento": state.get("orcamento") is not None,
        "com_meta_venda": state.get("meta_venda") is not None,
    }
    atualizacao: AgentState = {"encaminhamento": encaminhamento}
    if tentativas is not None:
        contexto["tentativas_de_taxa"] = tentativas.feitas
        atualizacao["tentativas_de_taxa"] = tentativas.feitas
    logger.info("node conclusion published", extra=contexto)
    return atualizacao
