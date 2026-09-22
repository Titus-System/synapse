from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import criar_engine, criar_sessionmaker


def test_criar_engine_uses_the_asyncpg_database_url(configuracoes: Settings) -> None:
    engine = criar_engine(configuracoes)

    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.username == configuracoes.SYNAPSE_CODEGEN_DB_USER
    assert engine.url.password == configuracoes.SYNAPSE_CODEGEN_DB_PASSWORD
    assert engine.url.host == configuracoes.POSTGRES_HOST
    assert engine.url.port == configuracoes.POSTGRES_PORT
    assert engine.url.database == configuracoes.POSTGRES_DB


def test_criar_sessionmaker_returns_a_sessionmaker_bound_to_the_engine(
    configuracoes: Settings,
) -> None:
    engine = criar_engine(configuracoes)

    sessoes = criar_sessionmaker(engine)

    assert isinstance(sessoes, async_sessionmaker)
    sessao = sessoes()
    assert isinstance(sessao, AsyncSession)
    assert sessao.bind is engine
