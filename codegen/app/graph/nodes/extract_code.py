"""`extract_code` node: extracts `regra.py` from the recorded reply and records it.

Concludes the `geracao_codigo` stage - prompt, resposta e código gravados -, e é por isso
que é daqui que sai o `no-concluido` desse nó.
"""

from datetime import UTC, datetime
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.codigo_gerado import CodigoInvalidoError, extrair_codigo
from app.contratos.mensagens import ConclusaoDaTrilha, NoConcluido
from app.core.logger import get_logger
from app.graph.core.state import AgentState
from app.graph.nodes.code_generation import NO_GERACAO_CODIGO
from app.repositorio.artefatos import gravar_codigo, id_do_evento_de_trilha

logger = get_logger("app.graph.nodes.extract_code")

# O que este nó concluiu, em texto legível por pessoa (US04). Descreve as verificações, não
# o código: o conteúdo do artefato fica no banco, e o evento leva só referências (ADR-001).
RESUMO_DA_TRILHA = (
    "Código Python gerado para a regra confirmada e validado: um único bloco, sintaxe "
    "válida e a função aplicar_regra com a assinatura do contrato."
)


async def extract_code(state: AgentState, config: RunnableConfig) -> AgentState:
    """Extract and validate the code, record it, and announce the node's conclusion.

    Raises `CodigoInvalidoError` when the reply has no valid `regra.py`; nothing is recorded
    in `codigos_gerados` and nothing is published in that case.
    """
    try:
        fonte = extrair_codigo(state["resposta_bruta"])
    except CodigoInvalidoError:
        logger.error("generated code rejected", extra={"prompt_id": state.get("prompt_id")})
        raise

    job_id = UUID(state["job_id"])
    regra_id = UUID(state["regra_id"])
    prompt_id = UUID(state["prompt_id"])
    sessoes = config["configurable"]["sessoes"]
    codigo_gerado_id = await gravar_codigo(
        sessoes, job_id=job_id, regra_id=regra_id, prompt_id=prompt_id, fonte=fonte
    )
    logger.info("generated code persisted", extra={"codigo_gerado_id": str(codigo_gerado_id)})

    # Publicado depois da gravação e antes de `executar-codigo`, não por conveniência: é a
    # linha de `simulacoes` que a api cria a partir deste evento que liga o job ao resultado
    # do worker. Se o resultado chegasse primeiro, ela não teria o que amarrar e o cliente
    # nunca receberia o evento SSE `resultado`.
    producers = config["configurable"]["producers"]
    await producers.no_concluido(
        NoConcluido(
            evento_id=id_do_evento_de_trilha(job_id, NO_GERACAO_CODIGO, codigo_gerado_id),
            job_id=job_id,
            no=NO_GERACAO_CODIGO,
            concluido_em=datetime.now(UTC),
            conclusao=ConclusaoDaTrilha(resumo=RESUMO_DA_TRILHA),
            regra_id=regra_id,
            prompt_id=prompt_id,
            codigo_gerado_id=codigo_gerado_id,
        )
    )
    logger.info("node conclusion published", extra={"no": NO_GERACAO_CODIGO})
    return {"codigo_fonte": fonte, "codigo_gerado_id": str(codigo_gerado_id)}
