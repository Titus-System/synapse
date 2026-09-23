from collections.abc import Callable, Iterable
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.core.engine import build_graph, route_after_greeting
from app.graph.core.state import AgentState
from app.prompts.geracao_codigo import montar_prompt_geracao
from app.representacao_regra import RepresentacaoRegra
from tests.app.graph.conftest import FakeChatModel

ScriptedModel = Callable[[Iterable[AIMessage]], FakeChatModel]

_REGRA = RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": []})


def test_build_graph_registers_greeting_but_leaves_it_out_of_the_run() -> None:
    graph = build_graph(InMemorySaver())

    drawable = graph.get_graph()
    assert set(drawable.nodes) == {
        "__start__",
        "greeting",
        "tools",
        "load_rule",
        "code_generation",
        "__end__",
    }
    edges = {(edge.source, edge.target) for edge in drawable.edges}
    assert edges == {
        ("__start__", "load_rule"),
        ("load_rule", "code_generation"),
        ("code_generation", "__end__"),
    }


def test_routes_to_tools_when_the_last_message_requested_a_tool_call() -> None:
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "say_hello", "args": {"name": "x"}, "id": "call_1"}],
            )
        ]
    }

    assert route_after_greeting(state) == "continue"


def test_routes_on_when_the_last_message_has_no_tool_call() -> None:
    state: AgentState = {"messages": [AIMessage(content="Hello x")]}

    assert route_after_greeting(state) == "done"


def test_routes_on_when_there_are_no_messages_yet() -> None:
    assert route_after_greeting({}) == "done"


async def _run_graph(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr("app.graph.nodes.load_rule.buscar_regra", AsyncMock(return_value=_REGRA))

    graph = build_graph(InMemorySaver())
    config: RunnableConfig = {
        "configurable": {"thread_id": "test", "sessoes": object(), "producers": object()}
    }
    initial_state: AgentState = {
        "job_id": "d9cf3b9e-c99e-4c1e-9f9e-2e6e3a5b0a11",
        "regra_id": "d9cf3b9e-c99e-4c1e-9f9e-2e6e3a5b0a12",
    }
    return await graph.ainvoke(initial_state, config)


async def test_graph_runs_code_generation_without_calling_greeting(
    scripted_model: ScriptedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = scripted_model([AIMessage(content="```python\ndef aplicar_regra(): ...\n```")])

    result = await _run_graph(monkeypatch)

    assert [[m.content for m in sent] for sent in model.seen_messages] == [
        [montar_prompt_geracao(_REGRA)]
    ]
    assert result["resposta_bruta"] == "```python\ndef aplicar_regra(): ...\n```"
