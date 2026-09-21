import os
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from app.config import Settings

# get_settings is cached at first import, so the environment has to be set before any app import.
load_dotenv(Path(__file__).resolve().parents[1] / ".env.test", override=True)
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("LOG_LEVEL", "CRITICAL")


@pytest.fixture(scope="session")
def settings() -> "Settings":
    from app.config import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def api() -> FastAPI:
    """Named ``api`` so it does not shadow the ``app`` package inside test modules."""
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(api: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Driving the lifespan per test would stop the logging listener for the whole session."""
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as http_client:
        yield http_client


@pytest.fixture(autouse=True)
async def _engine_de_banco_por_teste() -> AsyncGenerator[None, None]:
    """`get_engine`/`get_sessionmaker` são `lru_cache`: sem isto, o engine criado por
    um teste sobrevive para o próximo com um event loop diferente (`asyncio_mode`
    cria um por função) e todo uso subsequente quebra com "attached to a different
    loop". Cada teste começa com o cache limpo e o engine, se criado, é descartado.
    """
    from app.db.engine import get_engine, get_sessionmaker

    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    yield
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture
async def conexao_dono(settings: "Settings") -> AsyncGenerator[Any, None]:
    """Conexão com o dono do schema: lê o que o worker gravou, e limpa o que ele não pode apagar."""
    import asyncpg

    conexao = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=os.environ.get("POSTGRES_OWNER_USER", "postgres"),
        password=os.environ.get("POSTGRES_OWNER_PASSWORD", "postgres"),
    )
    try:
        yield conexao
    finally:
        await conexao.close()


@pytest.fixture
def fonte_do_codigo_seed() -> str:
    """Um teste que precisa de uma regra executável sobrescreve esta fixture."""
    return "def calcular(): return []"


@pytest.fixture
async def codigo_gerado_seed(
    conexao_dono: Any, fonte_do_codigo_seed: str
) -> AsyncGenerator[dict[str, object], None]:
    """Uma linha real de codigos_gerados, com a cadeia de FKs que ela exige
    (usuario -> job -> regra -> prompt). O worker só tem SELECT nessa tabela, então a
    escrita usa o dono do schema (`tests/semente.py`).
    """
    from tests.semente import apagar_semente, semear_codigo

    semente = await semear_codigo(conexao_dono, fonte=fonte_do_codigo_seed)
    try:
        yield {chave: semente[chave] for chave in ("id", "job_id", "linguagem", "fonte")}
    finally:
        await apagar_semente(conexao_dono, semente)


def exige_docker(ambiente: Mapping[str, str] | None = None) -> bool:
    """Em CI, teste marcado `docker` não pode ser pulado.

    São eles que provam o isolamento do sandbox (T-033, T-064). Pulados em silêncio, o
    gate de segurança do componente passa verde sem nunca ter rodado — o risco que a
    T-014 registra. Na máquina do desenvolvedor sem daemon o pulo continua valendo;
    `EXIGIR_DOCKER=1` reproduz localmente o comportamento do CI.
    """
    ambiente = os.environ if ambiente is None else ambiente
    return ambiente.get("CI") == "true" or ambiente.get("EXIGIR_DOCKER") == "1"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
    desfecho = yield
    relatorio = desfecho.get_result()
    if relatorio.skipped and exige_docker() and item.get_closest_marker("docker") is not None:
        relatorio.outcome = "failed"
        relatorio.longrepr = (
            f"{item.nodeid} foi pulado, e em CI um teste marcado 'docker' pulado é falha: "
            "sem ele o isolamento do sandbox não foi verificado."
        )
