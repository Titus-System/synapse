from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.config import Settings
from app.graph.core import checkpointer as module


class FakeSaver:
    """Stands in for `AsyncPostgresSaver`; Postgres is not owned by this test."""

    opened_with: list[str] = []
    closed = False

    @classmethod
    @asynccontextmanager
    async def from_conn_string(cls, url: str) -> AsyncIterator["FakeSaver"]:
        cls.opened_with.append(url)
        try:
            yield cls()
        finally:
            cls.closed = True


@pytest.fixture(autouse=True)
def fake_saver(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSaver.opened_with = []
    FakeSaver.closed = False
    monkeypatch.setattr(module, "AsyncPostgresSaver", FakeSaver)


async def test_get_checkpointer_opens_the_connection_from_settings(settings: Settings) -> None:
    async with module.get_checkpointer() as saver:
        assert isinstance(saver, FakeSaver)

    assert FakeSaver.opened_with == [settings.checkpointer_database_url]


async def test_get_checkpointer_closes_the_connection_when_the_run_fails() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with module.get_checkpointer():
            raise RuntimeError("boom")

    assert FakeSaver.closed is True


def test_checkpointer_url_uses_the_psycopg_scheme_on_the_same_database(settings: Settings) -> None:
    """The checkpointer speaks psycopg, which rejects SQLAlchemy's `+asyncpg` driver suffix."""
    url: Any = settings.checkpointer_database_url

    assert url == settings.database_url.replace("+asyncpg", "")
    assert url.startswith("postgresql://")
