"""Terminate a cycle whose rule has domain conflicts."""

from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState


class RegraComConflitoError(FalhaDoJobError):
    etapa = "validacao_dominio"

    def __init__(self) -> None:
        super().__init__("Rule rejected by domain validation")


async def reject_rule(state: AgentState) -> AgentState:
    raise RegraComConflitoError()
