"""`extract_code` node: extracts `regra.py` from the recorded reply and records it."""

from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.codigo_gerado import CodigoInvalidoError, extrair_codigo
from app.core.logger import get_logger
from app.graph.core.state import AgentState
from app.repositorio.artefatos import gravar_codigo

logger = get_logger("app.graph.nodes.extract_code")


async def extract_code(state: AgentState, config: RunnableConfig) -> AgentState:
    """Extract and validate the code, then insert it into `codigos_gerados`.

    Raises `CodigoInvalidoError` when the reply has no valid `regra.py`; nothing is recorded
    in `codigos_gerados` in that case.
    """
    try:
        fonte = extrair_codigo(state["resposta_bruta"])
    except CodigoInvalidoError:
        logger.error("generated code rejected", extra={"prompt_id": state.get("prompt_id")})
        raise

    sessoes = config["configurable"]["sessoes"]
    codigo_gerado_id = await gravar_codigo(
        sessoes,
        job_id=UUID(state["job_id"]),
        regra_id=UUID(state["regra_id"]),
        prompt_id=UUID(state["prompt_id"]),
        fonte=fonte,
    )
    logger.info("generated code persisted", extra={"codigo_gerado_id": str(codigo_gerado_id)})
    return {"codigo_fonte": fonte, "codigo_gerado_id": str(codigo_gerado_id)}
