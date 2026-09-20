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
from app.graph.nodes.calculator import calculator_node


def route_after_calculator(state: AgentState) -> Literal["continue", "end"]:
    """Send the run to the shared tool node if the last message requested a tool call."""
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "continue"
    return "end"


def load_nodes(graph: StateGraph[AgentState]) -> None:
    """Load all nodes into the graph."""
    graph.add_node("calculator", calculator_node)
    graph.add_node("tools", get_tool_node())


def load_edges(graph: StateGraph[AgentState]) -> None:
    """Load all edges into the graph."""
    graph.add_edge(START, "calculator")
    graph.add_conditional_edges(
        "calculator",
        route_after_calculator,
        {
            "continue": "tools",
            "end": END,
        },
    )
    graph.add_edge("tools", "calculator")


def build_graph(
    checkpointer: BaseCheckpointSaver[str],
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """
    Assemble and compile the graph.

    see the "shared tool-execution node" rule in `.agents/skills/graph/SKILL.md`.
    """
    graph = StateGraph(AgentState)
    load_nodes(graph)
    load_edges(graph)

    return graph.compile(checkpointer=checkpointer)
