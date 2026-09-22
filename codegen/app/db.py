"""Async SQLAlchemy engine/session wiring, shared by the app's lifespan and the graph's nodes.

Uses `asyncpg`, not `psycopg` - the checkpointer is the deliberate exception to that, see
`.agents/skills/graph/SKILL.md` and `app/graph/core/checkpointer.py`.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def criar_engine(configuracoes: Settings) -> AsyncEngine:
    """Build the async engine for `configuracoes.database_url`. Caller owns disposing it."""
    return create_async_engine(configuracoes.database_url)


def criar_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
