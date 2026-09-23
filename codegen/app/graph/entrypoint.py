"""
The graph's public interface - the only thing meant to be imported from outside `app/graph/`.
Everything under `app/graph/core/` is internal.
"""

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logger import get_logger
from app.graph.core.checkpointer import get_checkpointer
from app.graph.core.engine import build_graph
from app.graph.core.state import AgentState
from app.mensageria.producers import Producers

logger = get_logger("app.graph.entrypoint")


async def run_to_completion(
    job_id: str,
    initial_state: AgentState,
    *,
    sessoes: async_sessionmaker[AsyncSession],
    producers: Producers,
) -> None:
    """Run the graph for `job_id` to completion, or until it pauses.

    Meant to be called from the message-router boundary, never directly from a message
    handler. `job_id` is used as the LangGraph `thread_id`: if a
    checkpoint already exists under it, the graph resumes from that point and
    `initial_state` is ignored; otherwise the graph starts fresh from it.

    `sessoes` and `producers` reach every node through `config["configurable"]`, as agreed
    across T-094/T-096/T-097 - see `.agents/skills/graph/SKILL.md`.
    """
    config: RunnableConfig = {
        "configurable": {
            "thread_id": job_id,
            "sessoes": sessoes,
            "producers": producers,
        }
    }

    async with get_checkpointer() as checkpointer:
        graph = build_graph(checkpointer)
        async for stream_mode, chunk in graph.astream(
            initial_state, config, stream_mode=["updates", "custom"]
        ):
            if stream_mode == "updates":
                for node_name in chunk:
                    logger.info("graph node finished", extra={"node": node_name})
