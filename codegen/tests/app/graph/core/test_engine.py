from collections.abc import Callable, Iterable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.core.engine import build_graph, route_after_calculator
from app.graph.core.state import AgentState
from tests.app.graph.conftest import FakeChatModel

ScriptedModel = Callable[[Iterable[AIMessage]], FakeChatModel]


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


def _run_graph(question: str) -> Any:
    graph = build_graph(InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "test"}}
    return graph.ainvoke({"messages": [HumanMessage(content=question)]}, config)


async def test_graph_executes_the_requested_tool_and_hands_the_result_back_to_the_calculator(
    scripted_model: ScriptedModel,
) -> None:
    model = scripted_model(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "add", "args": {"a": 1, "b": 2}, "id": "call_1"}],
            ),
            AIMessage(content="the answer is 3"),
        ]
    )

    result = await _run_graph("1 + 2?")

    tool_message = result["messages"][2]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.content == "3"
    assert result["messages"][-1].content == "the answer is 3"
    assert tool_message in model.seen_messages[1]


async def test_graph_ends_after_one_model_call_when_no_tool_is_requested(
    scripted_model: ScriptedModel,
) -> None:
    model = scripted_model([AIMessage(content="nothing to compute")])

    result = await _run_graph("hello")

    assert [m.content for m in result["messages"]] == ["hello", "nothing to compute"]
    assert len(model.seen_messages) == 1
