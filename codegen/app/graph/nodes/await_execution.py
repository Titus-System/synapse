"""`await_execution` node: pauses the graph until the worker's result arrives.

Nothing but `interrupt()` belongs here: on resume the node re-runs from its first line. See
`docs/retomada-apos-execucao.md` for how the resume works.
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.graph.core.state import AgentState


async def await_execution(state: AgentState, config: RunnableConfig) -> AgentState:
    """Pause with the references the resume needs; the result itself stays in the database."""
    retomada: dict[str, Any] = interrupt(
        {"job_id": state["job_id"], "codigo_gerado_id": state["codigo_gerado_id"]}
    )
    atualizacao: AgentState = {
        "resultado_id": str(retomada["resultado_id"]),
        "status_simulacao": str(retomada["status"]),
    }
    veredito = retomada.get("veredito")
    # Ausente fora de `sucesso`, pelo contrato de `simulacao-concluida`.
    if veredito is not None:
        atualizacao["veredito"] = str(veredito)
    return atualizacao
