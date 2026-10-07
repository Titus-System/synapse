"""StateGraph assembly: every edge and conditional-edge lives here.

A node's position in the pipeline is graph-topology knowledge, not something
the node itself should encode - see `.agents/skills/graph/SKILL.md`.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.core.state import AgentState
from app.graph.nodes.await_execution import await_execution
from app.graph.nodes.code_generation import code_generation
from app.graph.nodes.decision import ENCAMINHAMENTO_SUGESTAO, decision
from app.graph.nodes.dispatch_execution import dispatch_execution
from app.graph.nodes.extract_code import extract_code
from app.graph.nodes.extract_rule import extract_rule
from app.graph.nodes.load_rule import load_rule
from app.graph.nodes.persist_response import persist_response
from app.graph.nodes.reject_rule import reject_rule
from app.graph.nodes.suggest_adaptation import suggest_adaptation
from app.graph.nodes.validate_domain import validate_domain

#: Nó em que o grafo pausa à espera do worker. Quem retoma confere que a pausa é esta antes de
#: entregar o resultado - ver `app/graph/entrypoint.py::resume_to_completion`.
AWAIT_EXECUTION = "await_execution"
SUGGEST_ADAPTATION = "suggest_adaptation"


def load_nodes(graph: StateGraph[AgentState]) -> None:
    """Load all nodes into the graph."""
    graph.add_node("load_rule", load_rule)
    graph.add_node("extract_rule", extract_rule)
    graph.add_node("validate_domain", validate_domain)
    graph.add_node("reject_rule", reject_rule)
    graph.add_node("code_generation", code_generation)
    graph.add_node("persist_response", persist_response)
    graph.add_node("extract_code", extract_code)
    graph.add_node("dispatch_execution", dispatch_execution)
    graph.add_node(AWAIT_EXECUTION, await_execution)
    graph.add_node("decision", decision)
    graph.add_node(SUGGEST_ADAPTATION, suggest_adaptation)


def _apos_a_decisao(state: AgentState) -> str:
    """Encaminha pelo campo que o nó de decisão validou.

    O veredito vem do worker e chega ao estado pela retomada; nada que um modelo escreveu
    entra nesta escolha (AGENTS.md - Security).
    """
    if state.get("encaminhamento") == ENCAMINHAMENTO_SUGESTAO:
        return SUGGEST_ADAPTATION
    return END


def _entrada(state: AgentState) -> str:
    return "load_rule" if state.get("regra_id") is not None else "extract_rule"


def _apos_a_validacao(state: AgentState) -> str:
    return "code_generation" if state["regra_liberada"] else "reject_rule"


def load_edges(graph: StateGraph[AgentState]) -> None:
    """Extraction ends after publication; persisted rules continue to worker execution.

    The api owns rule versions and opens the next cycle after persisting a proposal.
    """
    graph.add_conditional_edges(
        START, _entrada, {"load_rule": "load_rule", "extract_rule": "extract_rule"}
    )
    graph.add_edge("extract_rule", END)
    graph.add_edge("load_rule", "validate_domain")
    graph.add_conditional_edges(
        "validate_domain",
        _apos_a_validacao,
        {"code_generation": "code_generation", "reject_rule": "reject_rule"},
    )
    graph.add_edge("reject_rule", END)
    graph.add_edge("code_generation", "persist_response")
    graph.add_edge("persist_response", "extract_code")
    graph.add_edge("extract_code", "dispatch_execution")
    graph.add_edge("dispatch_execution", AWAIT_EXECUTION)
    graph.add_edge(AWAIT_EXECUTION, "decision")
    graph.add_conditional_edges(
        "decision", _apos_a_decisao, {SUGGEST_ADAPTATION: SUGGEST_ADAPTATION, END: END}
    )
    graph.add_edge(SUGGEST_ADAPTATION, END)


def build_graph(
    checkpointer: BaseCheckpointSaver[str],
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Assemble and compile the graph."""
    graph = StateGraph(AgentState)
    load_nodes(graph)
    load_edges(graph)

    return graph.compile(checkpointer=checkpointer)
