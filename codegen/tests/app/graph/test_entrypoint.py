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


def _pausing_graph_builder(recebido: list[Any]) -> Build:
    """Graph that pauses in `await_execution`, like the real one."""

    async def await_execution(state: AgentState, config: RunnableConfig) -> AgentState:
        recebido.append(interrupt({"job_id": state.get("job_id", "")}))
        return {}

    def build(checkpointer: Any) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
        graph = StateGraph(AgentState)
        graph.add_node("await_execution", await_execution)
        graph.add_edge(START, "await_execution")
        graph.add_edge("await_execution", END)
        return graph.compile(checkpointer=checkpointer)

    return build


async def test_resume_delivers_the_value_to_the_paused_node(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    recebido: list[Any] = []
    monkeypatch.setattr(entrypoint, "build_graph", _pausing_graph_builder(recebido))
    sessoes, producers = MagicMock(), MagicMock()
    await entrypoint.run_to_completion(
        "job-1", {"job_id": "job-1"}, sessoes=sessoes, producers=producers
    )

    desfecho = await entrypoint.resume_to_completion(
        "job-1", {"resultado_id": "r-1", "status": "sucesso"}, sessoes=sessoes, producers=producers
    )

    assert desfecho is entrypoint.ResumeOutcome.RESUMED
    assert recebido == [{"resultado_id": "r-1", "status": "sucesso"}]


async def test_resume_reports_a_job_without_checkpoint(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resultado de um job que este serviço nunca viu: reentregar não o faria aparecer."""
    monkeypatch.setattr(entrypoint, "build_graph", _pausing_graph_builder([]))

    desfecho = await entrypoint.resume_to_completion(
        "job-desconhecido", {"resultado_id": "r-1"}, sessoes=MagicMock(), producers=MagicMock()
    )

    assert desfecho is entrypoint.ResumeOutcome.NO_CHECKPOINT


async def test_resume_reports_a_graph_that_has_not_paused_yet(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O worker pode publicar antes de o checkpoint da pausa existir - é transitório."""
    falhas = iter([True, False])

    async def first(state: AgentState, config: RunnableConfig) -> AgentState:
        return {"regra_id": "r-1"}

    async def boom(state: AgentState, config: RunnableConfig) -> AgentState:
        if next(falhas):
            raise RuntimeError("transient")
        return {}

    def build(checkpointer: Any) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
        graph = StateGraph(AgentState)
        graph.add_node("first", first)
        graph.add_node("boom", boom)
        graph.add_edge(START, "first")
        graph.add_edge("first", "boom")
        graph.add_edge("boom", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(entrypoint, "build_graph", build)
    with pytest.raises(RuntimeError):
        await entrypoint.run_to_completion("job-1", {}, sessoes=MagicMock(), producers=MagicMock())

    desfecho = await entrypoint.resume_to_completion(
        "job-1", {"resultado_id": "r-1"}, sessoes=MagicMock(), producers=MagicMock()
    )

    assert desfecho is entrypoint.ResumeOutcome.NOT_PAUSED_YET


async def test_resume_reports_a_run_that_already_finished(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reentrega do mesmo resultado não retoma nada de novo."""
    recebido: list[Any] = []
    monkeypatch.setattr(entrypoint, "build_graph", _pausing_graph_builder(recebido))
    sessoes, producers = MagicMock(), MagicMock()
    await entrypoint.run_to_completion("job-1", {}, sessoes=sessoes, producers=producers)
    await entrypoint.resume_to_completion(
        "job-1", {"resultado_id": "r-1"}, sessoes=sessoes, producers=producers
    )

    desfecho = await entrypoint.resume_to_completion(
        "job-1", {"resultado_id": "r-1"}, sessoes=sessoes, producers=producers
    )

    assert desfecho is entrypoint.ResumeOutcome.ALREADY_FINISHED
    assert len(recebido) == 1


async def test_resume_retries_failure_after_the_interrupt_without_losing_result(
    saver: InMemorySaver, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[str] = []

    async def pause(state: AgentState) -> AgentState:
        value = interrupt({"job_id": state["job_id"]})
        return {"resultado_id": value["resultado_id"]}

    async def suggest(state: AgentState) -> AgentState:
        attempts.append(state["resultado_id"])
        if len(attempts) == 1:
            raise RuntimeError("broker unavailable")
        return {}

    def build(checkpointer: Any) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
        graph = StateGraph(AgentState)
        graph.add_node("await_execution", pause)
        graph.add_node("suggest", suggest)
        graph.add_edge(START, "await_execution")
        graph.add_edge("await_execution", "suggest")
        graph.add_edge("suggest", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(entrypoint, "build_graph", build)
    sessoes, producers = MagicMock(), MagicMock()
    await entrypoint.run_to_completion(
        "cycle", {"job_id": "job"}, sessoes=sessoes, producers=producers
    )
    with pytest.raises(RuntimeError, match="broker unavailable"):
        await entrypoint.resume_to_completion(
            "cycle", {"resultado_id": "result"}, sessoes=sessoes, producers=producers
        )
    outcome = await entrypoint.resume_to_completion(
        "cycle", {"resultado_id": "result"}, sessoes=sessoes, producers=producers
    )
    assert outcome is entrypoint.ResumeOutcome.RESUMED
    assert attempts == ["result", "result"]
