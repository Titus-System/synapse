from langgraph.checkpoint.memory import InMemorySaver

from app.graph.core.engine import build_graph


def test_build_graph_wires_load_rule_into_code_generation() -> None:
    graph = build_graph(InMemorySaver())

    drawable = graph.get_graph()
    assert set(drawable.nodes) >= {"__start__", "load_rule", "code_generation", "__end__"}
    edges = {(edge.source, edge.target) for edge in drawable.edges}
    assert ("__start__", "load_rule") in edges
    assert ("load_rule", "code_generation") in edges
    assert ("code_generation", "__end__") in edges
