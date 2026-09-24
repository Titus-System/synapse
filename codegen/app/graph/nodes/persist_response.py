"""`persist_response` node: records the generation prompt and the model's verbatim reply.

Runs before `extract_code`, so a reply the code cannot be extracted from stays auditable.
"""

from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.core.logger import get_logger
from app.graph.core.state import AgentState
from app.graph.nodes.code_generation import NO_GERACAO_CODIGO
from app.repositorio.artefatos import gravar_prompt_e_resposta

logger = get_logger("app.graph.nodes.persist_response")


async def persist_response(state: AgentState, config: RunnableConfig) -> AgentState:
    """Insert `prompts` and `respostas_modelo` and store both ids in the state."""
    sessoes = config["configurable"]["sessoes"]
    prompt_id, resposta_id = await gravar_prompt_e_resposta(
        sessoes,
        job_id=UUID(state["job_id"]),
        no=NO_GERACAO_CODIGO,
        prompt=state["prompt_enviado"],
        modelo=state["modelo"],
        resposta=state["resposta_bruta"],
        consumo_tokens=state.get("consumo_tokens"),
    )
    logger.info(
        "model response persisted",
        extra={"prompt_id": str(prompt_id), "resposta_id": str(resposta_id)},
    )
    return {"prompt_id": str(prompt_id), "resposta_id": str(resposta_id)}
