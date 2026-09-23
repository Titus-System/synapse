import logging
from collections.abc import Callable, Iterable

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.graph.core.state import AgentState
from app.graph.nodes.greeting import greeting
from app.graph.prompts.greeting import GREETING_PROMPT
from app.graph.tools.greeting import GREETING_TOOLS
from tests.app.graph.conftest import FakeChatModel

ScriptedModel = Callable[[Iterable[AIMessage]], FakeChatModel]


def _tool_call(name: str = "Synapse") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": "say_hello", "args": {"name": name}, "id": "call_1"}]
    )


async def test_greeting_sends_exactly_the_greeting_prompt_on_the_first_call(
    scripted_model: ScriptedModel,
) -> None:
    model = scripted_model([_tool_call()])

    await greeting({}, {"configurable": {}})

    assert [m.content for m in model.seen_messages[0]] == [GREETING_PROMPT]


async def test_greeting_binds_exactly_the_greeting_tool(scripted_model: ScriptedModel) -> None:
    model = scripted_model([_tool_call()])

    await greeting({}, {"configurable": {}})

    assert model.bound_tools == GREETING_TOOLS


async def test_greeting_returns_the_prompt_and_the_tool_call_as_messages(
    scripted_model: ScriptedModel,
) -> None:
    scripted_model([_tool_call()])

    update = await greeting({}, {"configurable": {}})

    assert set(update) == {"messages"}
    assert [m.content for m in update["messages"]] == [GREETING_PROMPT, ""]
    assert update["messages"][-1].tool_calls[0]["name"] == "say_hello"


async def test_greeting_reuses_the_existing_history_after_a_tool_loop(
    scripted_model: ScriptedModel,
) -> None:
    model = scripted_model([AIMessage(content="Hello Synapse")])
    state: AgentState = {
        "messages": [
            HumanMessage(content=GREETING_PROMPT),
            _tool_call(),
            ToolMessage(content="Hello Synapse", tool_call_id="call_1"),
        ],
    }

    update = await greeting(state, {"configurable": {}})

    assert [m.content for m in model.seen_messages[0]] == [GREETING_PROMPT, "", "Hello Synapse"]
    assert [m.content for m in update["messages"]] == ["Hello Synapse"]


async def test_greeting_never_logs_the_prompt_or_the_reply(
    scripted_model: ScriptedModel, caplog: pytest.LogCaptureFixture
) -> None:
    scripted_model([AIMessage(content="Hello Synapse")])

    with caplog.at_level(logging.INFO, logger="app.graph.nodes.greeting"):
        await greeting({}, {"configurable": {}})

    texto = " ".join(registro.getMessage() for registro in caplog.records)
    assert GREETING_PROMPT not in texto
    assert "Hello Synapse" not in texto
