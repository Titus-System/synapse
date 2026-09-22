"""`load_rule` node: reads the confirmed rule from `regras` and validates its contract."""

from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.graph.core.state import AgentState
from app.repositorio.regras import RegraInvalidaError, buscar_regra


async def load_rule(state: AgentState, config: RunnableConfig) -> AgentState:
    """Load `state["regra_id"]` and store its `RepresentacaoRegra` back into the state.

    Raises `RegraInvalidaError` when `regra_id` is missing from the state, the row does not
    exist for `job_id`, or it fails `RepresentacaoRegra`'s validation - any of these fails the
    node, never a partial result (AGENTS.md - "a regra deve ser simulada integralmente").
    """
    regra_id = state.get("regra_id")
    job_id = state.get("job_id")
    if regra_id is None or job_id is None:
        raise RegraInvalidaError("regra_id or job_id missing from the initial state") from None

    sessoes = config["configurable"]["sessoes"]
    regra = await buscar_regra(sessoes, UUID(job_id), UUID(regra_id))
    return {"representacao_regra": regra.para_contrato()}
