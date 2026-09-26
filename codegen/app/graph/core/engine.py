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
from app.graph.nodes.load_rule import load_rule
from app.graph.nodes.persist_response import persist_response
from app.graph.nodes.suggest_adaptation import suggest_adaptation

#: Nó em que o grafo pausa à espera do worker. Quem retoma confere que a pausa é esta antes de
#: entregar o resultado - ver `app/graph/entrypoint.py::resume_to_completion`.
AWAIT_EXECUTION = "await_execution"
SUGGEST_ADAPTATION = "suggest_adaptation"


def load_nodes(graph: StateGraph[AgentState]) -> None:
    """Load all nodes into the graph."""
    graph.add_node("load_rule", load_rule)
    graph.add_node("code_generation", code_generation)
    graph.add_node("persist_response", persist_response)
    graph.add_node("extract_code", extract_code)
    graph.add_node("dispatch_execution", dispatch_execution)
    graph.add_node(AWAIT_EXECUTION, await_execution)
    graph.add_node("decision", decision)
    graph.add_node(SUGGEST_ADAPTATION, suggest_adaptation)


def _apos_a_decisao(state: AgentState) -> str:
    """Única ramificação do grafo, e ela lê só o campo que o nó de decisão validou.

    O veredito vem do worker e chega ao estado pela retomada; nada que um modelo escreveu
    entra nesta escolha (AGENTS.md - Security).
    """
    if state.get("encaminhamento") == ENCAMINHAMENTO_SUGESTAO:
        return SUGGEST_ADAPTATION
    return END


def load_edges(graph: StateGraph[AgentState]) -> None:
    """Load all edges into the graph.

    Uma linha reta até a pausa, e uma ramificação depois dela: o grafo pausa dentro de
    `await_execution` até o resultado do worker retomá-lo, `decision` encaminha conforme o
    veredito apurado, e a adaptação volta a `END` porque a alternativa é gravada e
    re-simulada pela `api`, não por um laço interno.
    """
    graph.add_edge(START, "load_rule")
    graph.add_edge("load_rule", "code_generation")
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
