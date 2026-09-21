"""
The graph's public interface - the only thing meant to be imported from outside `app/graph/`.
Everything under `app/graph/core/` is internal.
"""

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.graph.core.checkpointer import get_checkpointer
from app.graph.core.engine import build_graph
from app.graph.core.state import AgentState


async def run(job_id: str, prompt: str) -> AsyncIterator[Any]:
    """Run the graph for `job_id`, streaming progress as it goes.
    This is an async generator.

    `job_id` is used as the LangGraph `thread_id` which will be used to track the conversation.
    If a checkpoint already exists for `job_id`, the graph will resume from that point.
    In this case, `prompt` is appended to the accumulated message history.
    If a checkpoint does not exist for `job_id`, the graph will start fresh.

    See `.agents/skills/graph/SKILL.md`.
    """
    config: RunnableConfig = {"configurable": {"thread_id": job_id}}
    inputs: AgentState = {"messages": [HumanMessage(content=prompt)]}

    async with get_checkpointer() as checkpointer:
        graph = build_graph(checkpointer)
        async for chunk in graph.astream(inputs, config, stream_mode=["updates", "custom"]):
            yield chunk
