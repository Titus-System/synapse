"""`await_execution` node: pauses the graph until the worker's result arrives.

Nothing but `interrupt()` belongs here: on resume the node re-runs from its first line. See
`docs/retomada-apos-execucao.md` for how the resume is expected to work.
"""

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.graph.core.state import AgentState


async def await_execution(state: AgentState, config: RunnableConfig) -> AgentState:
    """Pause with the references the resume needs; the result itself stays in the database."""
    interrupt({"job_id": state["job_id"], "codigo_gerado_id": state["codigo_gerado_id"]})
    return {}
