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
from app.core.metrics.global_metrics import (
    TENTATIVAS_DE_TAXA,
    correcoes_codigo,
    desfechos_correcao_codigo,
    tentativas_de_taxa,
)
from app.correcao_codigo import ENCAMINHAMENTO_CORRECAO, STATUS_CORRIGIVEIS, corrige
from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.regras import contar_tentativas
from app.repositorio.resultados import (
    buscar_execucao_da_meta,
    buscar_falha_da_execucao,
    posicao_do_codigo,
)

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
RESUMO_CORRECAO = "Fluxo encaminhado para a correção do código gerado."


class DecisaoSemResultadoError(FalhaDoJobError):
    """A retomada não trouxe o resultado, então não há desfecho para encaminhar.

    Uma reentrega não inventa a referência que faltou, então a falha é permanente.
    """

    etapa = ETAPA


class CodigoDesconhecidoError(FalhaDoJobError):
    """O código executado não está entre os gerados para o job, e não há posição a contar.

    Sem a posição, a correção poderia passar do limite que a `api` aplica; a reentrega não
    faz o código aparecer, então a falha é permanente.
    """

    etapa = ETAPA


async def decision(state: AgentState, config: RunnableConfig) -> AgentState:
    """Publish where the flow goes, and record it in the audit trail.

    A regra inviável vai à sugestão em toda tentativa, qualquer que seja sua estrutura, e é a
    sugestão que aplica o limite delas e decide se há taxa a reduzir: assim só ela anuncia que
    a iteração terminou sem alternativa (T-271).
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
        if tentativas is not None and veredito == Veredito.INVIAVEL
        else ENCAMINHAMENTO_FIM
    )
    if (
        get_settings().BUSCA_META_ENABLED
        and "busca_meta" not in state
        and state.get("status_simulacao") == "sucesso"
        and veredito == Veredito.VIAVEL
        and state.get("orcamento") is not None
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
    # A posição só é lida quando a falha é corrigível: é ela que diz se ainda cabe uma correção
    # nesta versão, pela mesma conta que a `api` faz para decidir se o job termina.
    posicao: int | None = None
    causa: str | None = None
    if state.get("status_simulacao") in STATUS_CORRIGIVEIS:
        sessoes = config["configurable"]["sessoes"]
        posicao = await posicao_do_codigo(sessoes, job_id, UUID(state["codigo_gerado_id"]))
        if posicao == 0:
            raise CodigoDesconhecidoError("executed code is not among the job's generated code")
        if corrige(state.get("status_simulacao"), posicao):
            causa = (await buscar_falha_da_execucao(sessoes, job_id, UUID(resultado_id))).causa()
            encaminhamento = ENCAMINHAMENTO_CORRECAO
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
                        ENCAMINHAMENTO_CORRECAO: RESUMO_CORRECAO,
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
    pendente = state.get("correcao_pendente")
    if pendente is not None:
        # O desfecho da execução do código corrigido que a decisão anterior pediu.
        desfechos_correcao_codigo.labels(
            tentativa=str(pendente),
            desfecho="sucesso" if state.get("status_simulacao") == "sucesso" else "erro",
        ).inc()
    # A presença dos parâmetros, nunca o valor que o usuário disse. A do orçamento explica o
    # encaminhamento: sem ele não há veredito e o fluxo termina (T-281).
    contexto: dict[str, object] = {
        "no": ETAPA,
        "encaminhamento": encaminhamento,
        "com_orcamento": state.get("orcamento") is not None,
        "com_meta_venda": state.get("meta_venda") is not None,
    }
    atualizacao: AgentState = {"encaminhamento": encaminhamento}
    if pendente is not None:
        atualizacao["correcao_pendente"] = None
    if tentativas is not None:
        contexto["tentativas_de_taxa"] = tentativas.feitas
        atualizacao["tentativas_de_taxa"] = tentativas.feitas
    if posicao is not None:
        contexto["posicao_do_codigo"] = posicao
    if causa is not None and posicao is not None:
        # A causa do conjunto fechado, nunca a mensagem ou o traceback, que vêm do código gerado.
        contexto["causa"] = causa
        correcoes_codigo.labels(tentativa=str(posicao + 1), causa=causa).inc()
        atualizacao["correcao_pendente"] = posicao + 1
    logger.info("node conclusion published", extra=contexto)
    return atualizacao
