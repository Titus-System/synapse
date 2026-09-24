"""
The graph's public interface - the only thing meant to be imported from outside `app/graph/`.
Everything under `app/graph/core/` is internal.
"""

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logger import get_logger
from app.graph.core.checkpointer import get_checkpointer
from app.graph.core.engine import build_graph
from app.graph.core.state import AgentState
from app.mensageria.producers import Producers

logger = get_logger("app.graph.entrypoint")


async def run(
    job_id: str,
    initial_state: AgentState,
    *,
    sessoes: async_sessionmaker[AsyncSession],
    producers: Producers,
) -> AsyncIterator[tuple[str, Any]]:
    """Run the graph for `job_id`, yielding `(node_name, update)` as each node finishes.

    `job_id` is used as the LangGraph `thread_id`: if a checkpoint already exists under it,
    the graph resumes from that point and `initial_state` is ignored; otherwise the graph
    starts fresh from it. When the run pauses, the last item is `("__interrupt__", ...)`
    carrying the `interrupt()` value, and the iteration ends.

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
        # LangGraph starts a new run from START for any non-None input, even on a thread that
        # already has checkpoints. `None` continues from the last one instead: after a
        # redelivery, the nodes that already finished (model call, inserts) do not run again.
        existing = await graph.aget_state(config)
        graph_input = None if existing.values else initial_state
        async for stream_mode, chunk in graph.astream(
            graph_input, config, stream_mode=["updates", "custom"]
        ):
            if stream_mode == "updates" and isinstance(chunk, dict):
                for node_name, update in chunk.items():
                    logger.info("graph node finished", extra={"node": node_name})
                    yield node_name, update


async def run_to_completion(
    job_id: str,
    initial_state: AgentState,
    *,
    sessoes: async_sessionmaker[AsyncSession],
    producers: Producers,
) -> None:
    """Drive `run` until the graph finishes or pauses, discarding the per-node updates.

    Meant to be called from the message-router boundary, never directly from a message
    handler.
    """
    async for _ in run(job_id, initial_state, sessoes=sessoes, producers=producers):
        pass
