from langgraph.prebuilt import ToolNode

from app.graph.core.tool_dispatch import ALLOWED_TOOLS, get_tool_node


def test_allowed_tools_is_exactly_the_arithmetic_set() -> None:
    """AGENTS.md Security: the tools a node can call are a fixed allowlist declared in code."""
    assert {t.name for t in ALLOWED_TOOLS} == {"add", "subtract", "multiply"}


def test_get_tool_node_returns_a_tool_node_over_the_allowlist() -> None:
    node = get_tool_node()

    assert isinstance(node, ToolNode)
    assert set(node.tools_by_name) == {t.name for t in ALLOWED_TOOLS}
