"""`explain_result` node: escreve a narrativa do resultado e confere cada número que ela cita.

Roda depois da decisão, só quando a simulação teve sucesso: erro de código e asserção violada não
têm número a narrar. A narrativa cita os números que o worker apurou e nunca os calcula; antes de
valer para o usuário, cada número do texto é conferido contra a lista dos apurados
(`app/explicacao.py`). O texto reprovado é gravado com `aderencia_conferida = false`, para o
auditor, e a `api` não o exibe.

A etapa nunca falha o ciclo. Provedor fora do ar, resposta vazia e texto reprovado terminam a
etapa sem narrativa exibível, e o grafo segue para a sugestão, para a busca da meta ou para o fim.
Por isso ela não usa `chamar_com_espera_do_provedor`, que espera o provedor voltar e avisa o
usuário: faz uma chamada, com o `max_retries` e o timeout do modelo, para atrasar pouco o que vem
depois. O nó não altera `encaminhamento` nem outro campo que a aresta seguinte leia.
"""

from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import ConclusaoDaTrilha, DesfechoExplicacao, NoConcluido, NoGrafo
from app.core.logger import get_logger, no_ctx
from app.core.metrics.global_metrics import explicacoes, job_duration, job_failures, job_runs
from app.explicacao import montar_numeros_citaveis, narrativa_confere
from app.falhas import FalhaDoJobError
from app.graph.core.llm.disponibilidade import e_indisponibilidade_do_provedor
from app.graph.core.llm.registry import get_model, get_model_metadata
from app.graph.core.state import AgentState
from app.prompts.explicacao import montar_prompt_explicacao
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.explicacoes import buscar_explicacao, gravar_chamada_e_explicacao
from app.repositorio.resultados import (
    ResultadoDesconhecidoError,
    buscar_decomposicao,
    buscar_totais_apurados,
)
from app.resposta_modelo import extrair_resposta

logger = get_logger("app.graph.nodes.explain_result")

#: Identifica a etapa em `prompts.no`, no `no` dos logs e na trilha.
ETAPA: NoGrafo = "explicacao"
NOME_DO_NO = "explain_result"

# Mesma regra do nó de geração: só a parada limpa vale. Um texto cortado por limite ou bloqueado
# pelo provedor pode ter números pela metade, e não é narrativa.
_FINISH_REASON_ACEITO = "STOP"

#: O que a trilha registra de cada desfecho, sem o texto da narrativa nem número algum.
RESUMOS: dict[DesfechoExplicacao, str] = {
    "conferida": "narrativa gravada e conferida contra os valores apurados",
    "reprovada": "narrativa gravada para auditoria e reprovada por citar número não apurado",
    "sem_resposta": "modelo não devolveu texto para explicar o resultado",
    "provedor_indisponivel": "indisponibilidade do provedor impediu obter a narrativa",
}


class ExplicacaoSemResultadoError(FalhaDoJobError):
    """O resultado a explicar não existe para o job ou não tem totais nem decomposição.

    Simulação com sucesso sempre tem os dois, então o resultado inconsistente falha o job em vez
    de seguir sem narrativa. Uma reentrega não faz a linha aparecer, e a falha é permanente.
    """

    etapa = ETAPA


async def explain_result(state: AgentState, config: RunnableConfig) -> AgentState:
    """Explain the successful simulation `state["resultado_id"]` and publish the conclusion.

    Se o resultado já tem linha em `explicacoes`, é uma reexecução do nó depois da gravação, e
    a conclusão é republicada com ela, sem nova chamada ao modelo. O contador de explicações
    só conta o processamento feito, e não essa republicação.
    """
    job_id = UUID(state["job_id"])
    resultado_id = UUID(state["resultado_id"])
    regra_id = UUID(state["regra_id"])
    sessoes = config["configurable"]["sessoes"]

    token = no_ctx.set(ETAPA)
    inicio = perf_counter()
    job_runs.labels(job_name=NOME_DO_NO).inc()
    try:
        logger.info("explanation started")
        gravada = await buscar_explicacao(
            sessoes, job_id=job_id, resultado_id=resultado_id, no=ETAPA
        )
        if gravada is not None:
            desfecho: DesfechoExplicacao = (
                "conferida" if gravada.aderencia_conferida else "reprovada"
            )
            await _publicar(
                config,
                job_id=job_id,
                regra_id=regra_id,
                resultado_id=resultado_id,
                desfecho=desfecho,
                prompt_id=gravada.prompt_id,
                explicacao_id=gravada.id,
            )
            logger.info("explanation republished", extra={"desfecho": desfecho})
            return {}

        try:
            totais = await buscar_totais_apurados(sessoes, job_id, resultado_id)
            decomposicao = await buscar_decomposicao(sessoes, job_id, resultado_id)
        except ResultadoDesconhecidoError:
            raise ExplicacaoSemResultadoError("simulation result not found or incomplete") from None
        meta_venda = state.get("meta_venda")
        citaveis = montar_numeros_citaveis(
            totais=totais,
            decomposicao=decomposicao,
            regra=state["representacao_regra"],
            competencias=state.get("competencias") or list(decomposicao.get("competencia", {})),
            meta_venda=None if meta_venda is None else Decimal(meta_venda),
        )
        prompt = montar_prompt_explicacao(
            veredito=state.get("veredito"), regra=state["representacao_regra"], citaveis=citaveis
        )

        prompt_id: UUID | None = None
        explicacao_id: UUID | None = None
        resposta = await _chamar_modelo(prompt)
        if resposta is None:
            desfecho = "provedor_indisponivel"
        else:
            conteudo, finish_reason, consumo = resposta
            if not conteudo.strip() or finish_reason != _FINISH_REASON_ACEITO:
                desfecho = "sem_resposta"
                conferida = None
            else:
                conferida = narrativa_confere(conteudo, citaveis)
                desfecho = "conferida" if conferida else "reprovada"
            prompt_id, explicacao_id = await gravar_chamada_e_explicacao(
                sessoes,
                job_id=job_id,
                resultado_id=resultado_id,
                no=ETAPA,
                prompt=prompt,
                modelo=get_model_metadata("explanation"),
                resposta=conteudo,
                consumo_tokens=consumo,
                conferida=conferida,
            )
        # Contado quando o processamento terminou e foi gravado, antes da publicação: se ela
        # falhar, a reentrega acha a linha e republica sem contar de novo.
        explicacoes.labels(desfecho=desfecho).inc()
        await _publicar(
            config,
            job_id=job_id,
            regra_id=regra_id,
            resultado_id=resultado_id,
            desfecho=desfecho,
            prompt_id=prompt_id,
            explicacao_id=explicacao_id,
        )
        # Só o desfecho: o texto, a resposta e os números citados ficam no banco.
        logger.info("explanation finished", extra={"desfecho": desfecho})
        return {}
    except BaseException:
        job_failures.labels(job_name=NOME_DO_NO).inc()
        raise
    finally:
        job_duration.labels(job_name=NOME_DO_NO).observe(perf_counter() - inicio)
        no_ctx.reset(token)


async def _chamar_modelo(prompt: str) -> tuple[str, str | None, dict[str, Any] | None] | None:
    """Uma chamada ao modelo; None quando ela falha, qualquer que seja o motivo.

    A etapa não pode falhar o ciclo, então toda falha da chamada vira `provedor_indisponivel`, a
    mais próxima do vocabulário do contrato. Só o tipo da exceção vai para o log: a mensagem do
    provedor pode carregar o prompt.
    """
    try:
        response = await get_model("explanation").ainvoke([HumanMessage(content=prompt)])
    except Exception as erro:
        logger.warning(
            "explanation model call failed",
            extra={
                "tipo_do_erro": type(erro).__name__,
                "provedor_indisponivel": e_indisponibilidade_do_provedor(erro),
            },
        )
        return None
    conteudo, finish_reason = extrair_resposta(response)
    return conteudo, finish_reason, _consumo_de_tokens(response)


def _consumo_de_tokens(response: BaseMessage) -> dict[str, Any] | None:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return None
    tokens_in = usage.get("input_tokens")
    tokens_out = usage.get("output_tokens")
    if tokens_in is None or tokens_out is None:
        return None
    return {"tokens_in": tokens_in, "tokens_out": tokens_out}


async def _publicar(
    config: RunnableConfig,
    *,
    job_id: UUID,
    regra_id: UUID,
    resultado_id: UUID,
    desfecho: DesfechoExplicacao,
    prompt_id: UUID | None,
    explicacao_id: UUID | None,
) -> None:
    """Publica o `no-concluido` da etapa; o `evento_id` vem do resultado, então não duplica.

    A referência que a etapa não produziu fica fora do evento: o contrato aceita o campo ausente,
    e a serialização envia como `null` o que for passado como None.
    """
    referencias: dict[str, UUID] = {}
    if prompt_id is not None:
        referencias["prompt_id"] = prompt_id
    if explicacao_id is not None:
        referencias["explicacao_id"] = explicacao_id
    await config["configurable"]["producers"].no_concluido(
        NoConcluido(
            evento_id=id_do_evento_de_trilha(job_id, ETAPA, resultado_id),
            job_id=job_id,
            no=ETAPA,
            concluido_em=datetime.now(UTC),
            conclusao=ConclusaoDaTrilha(resumo=RESUMOS[desfecho], desfecho_explicacao=desfecho),
            regra_id=regra_id,
            resultado_id=resultado_id,
            **referencias,
        )
    )
