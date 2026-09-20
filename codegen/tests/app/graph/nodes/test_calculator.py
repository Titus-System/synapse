from collections.abc import Callable, Iterable

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes.calculator import calculator_node
from app.graph.prompts.calculator import SYSTEM_PROMPT
from app.graph.tools.arithmetic import ARITHMETIC_TOOLS
from tests.app.graph.conftest import FakeChatModel

ScriptedModel = Callable[[Iterable[AIMessage]], FakeChatModel]


def test_calculator_node_returns_the_model_response_as_the_new_message(
    scripted_model: ScriptedModel,
) -> None:
    scripted_model([AIMessage(content="the answer is 3")])

    update = calculator_node({"messages": [HumanMessage(content="1 + 2?")]})

    assert [m.content for m in update["messages"]] == ["the answer is 3"]


def test_calculator_node_binds_exactly_the_arithmetic_tools(scripted_model: ScriptedModel) -> None:
    model = scripted_model([AIMessage(content="ok")])

    calculator_node({"messages": [HumanMessage(content="1 + 2?")]})

    assert model.bound_tools == ARITHMETIC_TOOLS


def test_calculator_node_sends_the_system_prompt_first_then_the_history(
    scripted_model: ScriptedModel,
) -> None:
    model = scripted_model([AIMessage(content="ok")])
    question = HumanMessage(content="1 + 2?")

    calculator_node({"messages": [question]})

    assert model.seen_messages == [[SYSTEM_PROMPT, question]]
