"""
AsyncPostgresSaver wiring. It opens a database connection for the duration of a graph run.

Uses `psycopg` (v3), not `asyncpg` - see `.agents/skills/graph/SKILL.md`.
`setup()` creates LangGraph's own checkpoint tables and only needs to run once;
it is not called on every graph run here.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings


@asynccontextmanager
async def get_checkpointer() -> AsyncGenerator[AsyncPostgresSaver, None]:
    """Open the checkpointer connection for the lifetime of one graph run."""

    settings = get_settings()
    db_url = settings.checkpointer_database_url
    async with AsyncPostgresSaver.from_conn_string(db_url) as checkpointer:
        yield checkpointer
