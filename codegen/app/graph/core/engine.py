"""StateGraph assembly: every edge and conditional-edge lives here.

A node's position in the pipeline is graph-topology knowledge, not something
the node itself should encode - see `.agents/skills/graph/SKILL.md`.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.core.state import AgentState
from app.graph.nodes.code_generation import code_generation
from app.graph.nodes.load_rule import load_rule


def load_nodes(graph: StateGraph[AgentState]) -> None:
    """Load all nodes into the graph."""
    graph.add_node("load_rule", load_rule)
    graph.add_node("code_generation", code_generation)


def load_edges(graph: StateGraph[AgentState]) -> None:
    """Load all edges into the graph.

    `code_generation` leads straight to `END` for now - `persist_response` (T-097) is not
    implemented yet; see `Attention.md`.
    """
    graph.add_edge(START, "load_rule")
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
