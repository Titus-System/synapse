"""StateGraph assembly: every edge and conditional-edge/routing function lives here.

A node's position in the pipeline is graph-topology knowledge, not something
the node itself should encode — see `.agents/skills/graph/SKILL.md`.
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


def build_graph(
    checkpointer: BaseCheckpointSaver[str],
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Assemble and compile the graph.

    Only one node calls the tool node today, so the edge back from it is
    fixed. If a second tool-using node is added, that edge becomes
    conditional on the calling node's identity carried in state — see the
    "shared tool-execution node" rule in `.agents/skills/graph/SKILL.md`.
    """
    graph = StateGraph(AgentState)

    graph.add_node("calculator", calculator_node)
    graph.add_node("tools", get_tool_node())

    graph.add_edge(START, "calculator")
    graph.add_conditional_edges(
        "calculator",
        route_after_calculator,
        {"continue": "tools", "end": END},
    )
    graph.add_edge("tools", "calculator")

    return graph.compile(checkpointer=checkpointer)
