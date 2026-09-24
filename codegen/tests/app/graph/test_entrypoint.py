from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from app.graph import entrypoint
from app.graph.core.state import AgentState

Build = Callable[[Any], CompiledStateGraph[AgentState, None, AgentState, AgentState]]


def _fake_graph_builder(calls: list[dict[str, Any]]) -> Build:
    async def record(state: AgentState, config: RunnableConfig) -> AgentState:
        calls.append(dict(config["configurable"]))
        return {"regra_id": state.get("regra_id", "")}

    def build(checkpointer: Any) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
        graph = StateGraph(AgentState)
        graph.add_node("record", record)
        graph.add_edge(START, "record")
        graph.add_edge("record", END)
        return graph.compile(checkpointer=checkpointer)

    return build


@pytest.fixture
def saver(monkeypatch: pytest.MonkeyPatch) -> InMemorySaver:
    """In-memory checkpointer in place of Postgres, shared by every run in the test."""
    shared = InMemorySaver()

    @asynccontextmanager
    async def get_checkpointer() -> AsyncIterator[InMemorySaver]:
        yield shared

    monkeypatch.setattr(entrypoint, "get_checkpointer", get_checkpointer)
    return shared


async def test_run_to_completion_uses_the_id_as_thread_id(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(entrypoint, "build_graph", _fake_graph_builder(calls))
    sessoes, producers = MagicMock(), MagicMock()

    await entrypoint.run_to_completion(
        "job-1", {"regra_id": "r-1"}, sessoes=sessoes, producers=producers
    )

    assert calls[-1]["thread_id"] == "job-1"


async def test_run_to_completion_passes_sessoes_and_producers_to_the_nodes(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(entrypoint, "build_graph", _fake_graph_builder(calls))
    sessoes, producers = MagicMock(), MagicMock()

    await entrypoint.run_to_completion(
        "job-1", {"regra_id": "r-1"}, sessoes=sessoes, producers=producers
    )

    assert calls[-1]["sessoes"] is sessoes
    assert calls[-1]["producers"] is producers


async def test_run_to_completion_resumes_the_same_thread_id(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(entrypoint, "build_graph", _fake_graph_builder(calls))
    sessoes, producers = MagicMock(), MagicMock()

    await entrypoint.run_to_completion(
        "job-1", {"regra_id": "first"}, sessoes=sessoes, producers=producers
    )
    await entrypoint.run_to_completion(
        "job-1", {"regra_id": "second"}, sessoes=sessoes, producers=producers
    )

    saved = saver.get_tuple({"configurable": {"thread_id": "job-1"}})
    assert saved is not None
    assert saved.checkpoint["channel_values"]["regra_id"] == "first"
    assert len(calls) == 1


async def test_run_yields_each_finished_node_and_the_pause(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def pause(state: AgentState, config: RunnableConfig) -> AgentState:
        interrupt({"job_id": "job-1"})
        return {}

    def build(checkpointer: Any) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
        graph = StateGraph(AgentState)
        graph.add_node("first", lambda state: {"regra_id": "r-1"})
        graph.add_node("pause", pause)
        graph.add_edge(START, "first")
        graph.add_edge("first", "pause")
        graph.add_edge("pause", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(entrypoint, "build_graph", build)

    items = [
        item
        async for item in entrypoint.run("job-1", {}, sessoes=MagicMock(), producers=MagicMock())
    ]

    assert [name for name, _ in items] == ["first", "__interrupt__"]
    assert items[0][1] == {"regra_id": "r-1"}
    assert items[1][1][0].value == {"job_id": "job-1"}


async def test_run_continues_a_failed_run_without_repeating_finished_nodes(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    executed: list[str] = []
    failures = iter([True, False])

    async def first(state: AgentState, config: RunnableConfig) -> AgentState:
        executed.append("first")
        return {}

    async def flaky(state: AgentState, config: RunnableConfig) -> AgentState:
        executed.append("flaky")
        if next(failures):
            raise RuntimeError("transient")
        return {}

    def build(checkpointer: Any) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
        graph = StateGraph(AgentState)
        graph.add_node("first", first)
        graph.add_node("flaky", flaky)
        graph.add_edge(START, "first")
        graph.add_edge("first", "flaky")
        graph.add_edge("flaky", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(entrypoint, "build_graph", build)
    with pytest.raises(RuntimeError):
        await entrypoint.run_to_completion("job-1", {}, sessoes=MagicMock(), producers=MagicMock())

    await entrypoint.run_to_completion("job-1", {}, sessoes=MagicMock(), producers=MagicMock())

    assert executed == ["first", "flaky", "flaky"]
