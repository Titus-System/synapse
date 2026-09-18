from langchain_core.messages import AIMessage

from app.graph.core.engine import route_after_calculator
from app.graph.core.state import AgentState


def test_routes_to_tools_when_the_last_message_requested_a_tool_call() -> None:
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"a": 1, "b": 2}, "id": "call_1"}],
            )
        ]
    }

    assert route_after_calculator(state) == "continue"


def test_routes_to_end_when_the_last_message_has_no_tool_call() -> None:
    state: AgentState = {"messages": [AIMessage(content="the answer is 3")]}

    assert route_after_calculator(state) == "end"
