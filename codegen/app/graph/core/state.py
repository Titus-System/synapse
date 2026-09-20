"""The one shared state schema every node in the graph reads and writes."""

from collections.abc import Sequence
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Shared graph state.

    `add_messages` is the reducer: a node's return value is merged into
    `messages` (appended) rather than replacing it outright.
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]
