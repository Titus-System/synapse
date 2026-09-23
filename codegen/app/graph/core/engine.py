"""StateGraph assembly: every edge and conditional-edge lives here.

A node's position in the pipeline is graph-topology knowledge, not something
the node itself should encode - see `.agents/skills/graph/SKILL.md`.
"""

from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.core.state import AgentState
from app.graph.core.tool_dispatch import get_tool_node
from app.graph.nodes.code_generation import code_generation
from app.graph.nodes.greeting import greeting
from app.graph.nodes.load_rule import load_rule


def route_after_greeting(state: AgentState) -> Literal["continue", "done"]:
    """Send the run to the shared tool node if the last message requested a tool call."""
    messages = state.get("messages") or []
    if not messages:
        return "done"
    last_message = messages[-1]
    if getattr(last_message, "tool_calls", None):
        return "continue"
    return "done"


def load_nodes(graph: StateGraph[AgentState]) -> None:
    """Load all nodes into the graph."""
    graph.add_node("greeting", greeting)
    graph.add_node("load_rule", load_rule)
    graph.add_node("code_generation", code_generation)
    graph.add_node("tools", get_tool_node())


def load_edges(graph: StateGraph[AgentState]) -> None:
    """Load all edges into the graph.

    `greeting` is the only node that calls tools, so `tools` always hands the result back to
    it. `code_generation` leads straight to `END` - `persist_response` (T-097) is not
    implemented yet.
    """
    # graph.add_edge(START, "greeting")
    graph.add_edge(START, "load_rule")
    graph.add_conditional_edges(
        "greeting",
        route_after_greeting,
        {
            "continue": "tools",
            "done": "load_rule",
        },
    )
    graph.add_edge("tools", "greeting")
    graph.add_edge("load_rule", "code_generation")
    graph.add_edge("code_generation", END)


def build_graph(
    checkpointer: BaseCheckpointSaver[str],
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Assemble and compile the graph."""
    graph = StateGraph(AgentState)
    load_nodes(graph)
    load_edges(graph)

    return graph.compile(checkpointer=checkpointer)
