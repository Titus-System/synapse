"""`load_rule` node: reads the confirmed rule from `regras` and validates its contract.

Announces domain validation before reading the rule, so a failed read has stage progress.
"""

from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import EtapaAlterada
from app.graph.core.state import AgentState
from app.graph.nodes.validate_domain import ETAPA
from app.repositorio.regras import RegraInvalidaError, buscar_regra


async def load_rule(state: AgentState, config: RunnableConfig) -> AgentState:
    """Announce the stage, then load `state["regra_id"]` into the state.

    Raises `RegraInvalidaError` when `regra_id` is missing from the state, the row does not
    exist for `job_id`, or it fails `RepresentacaoRegra`'s validation - any of these fails the
    node, never a partial result (AGENTS.md - "a regra deve ser simulada integralmente").
    """
    regra_id = state.get("regra_id")
    job_id = state.get("job_id")
    if regra_id is None or job_id is None:
        raise RegraInvalidaError("regra_id or job_id missing from the initial state") from None

    producers = config["configurable"]["producers"]
    await producers.etapa_alterada(
        EtapaAlterada(job_id=UUID(job_id), etapa=ETAPA, status="iniciada")
    )

    sessoes = config["configurable"]["sessoes"]
    regra = await buscar_regra(sessoes, UUID(job_id), UUID(regra_id))
    return {"representacao_regra": regra.para_contrato()}
