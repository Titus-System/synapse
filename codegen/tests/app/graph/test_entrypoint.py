from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from contextlib import asynccontextmanager
from itertools import count
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.graph import entrypoint
from tests.app.graph.conftest import FakeChatModel

ScriptedModel = Callable[[Iterable[AIMessage]], FakeChatModel]


def _replies() -> Iterator[AIMessage]:
    return (AIMessage(content=f"reply {n}") for n in count())


@pytest.fixture
def saver(monkeypatch: pytest.MonkeyPatch, scripted_model: ScriptedModel) -> InMemorySaver:
    """In-memory checkpointer in place of Postgres, shared by every run in the test."""
    shared = InMemorySaver()

    @asynccontextmanager
    async def get_checkpointer() -> AsyncIterator[InMemorySaver]:
        yield shared

    monkeypatch.setattr(entrypoint, "get_checkpointer", get_checkpointer)
    scripted_model(_replies())
    return shared


def _human_messages(saver: InMemorySaver, thread_id: str) -> list[str]:
    saved = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    assert saved is not None
    history = saved.checkpoint["channel_values"]["messages"]
    return [str(m.content) for m in history if isinstance(m, HumanMessage)]


async def _run(thread_id: str, prompt: str) -> list[Any]:
    return [chunk async for chunk in entrypoint.run(thread_id, prompt)]


async def test_run_streams_one_update_per_finished_node(saver: InMemorySaver) -> None:
    chunks = await _run("job-1", "1 + 2?")

    assert [(mode, list(data)) for mode, data in chunks] == [("updates", ["calculator"])]


async def test_run_uses_the_id_as_thread_id_so_the_same_id_resumes(saver: InMemorySaver) -> None:
    await _run("job-1", "first")
    await _run("job-1", "second")

    assert _human_messages(saver, "job-1") == ["first", "second"]


async def test_run_starts_fresh_for_an_id_without_a_checkpoint(saver: InMemorySaver) -> None:
    await _run("job-1", "first")
    await _run("job-2", "other")

    assert _human_messages(saver, "job-2") == ["other"]
