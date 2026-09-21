from langchain_core.messages import AIMessage
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode

from app.graph.core.state import AgentState
from app.graph.core.tool_dispatch import ALLOWED_TOOLS, get_tool_node


def test_allowed_tools_is_exactly_the_arithmetic_set() -> None:
    """AGENTS.md Security: the tools a node can call are a fixed allowlist declared in code."""
    assert {t.name for t in ALLOWED_TOOLS} == {"add", "subtract", "multiply"}


def test_get_tool_node_returns_a_tool_node_over_the_allowlist() -> None:
    node = get_tool_node()

    assert isinstance(node, ToolNode)
    assert set(node.tools_by_name) == {t.name for t in ALLOWED_TOOLS}


async def test_tool_node_refuses_a_tool_that_is_not_in_the_allowlist() -> None:
    """AGENTS.md Security: the model's output never adds to what is dispatchable."""
    builder = StateGraph(AgentState)
    builder.add_node("tools", get_tool_node())
    builder.add_edge(START, "tools")
    requested = AIMessage(
        content="", tool_calls=[{"name": "not_allowlisted", "args": {}, "id": "call_1"}]
    )

    result = await builder.compile().ainvoke({"messages": [requested]})

    reply = result["messages"][-1]
    assert reply.status == "error"
