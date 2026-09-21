import hashlib
import json
import os
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

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
async def codigo_gerado_seed(settings: "Settings") -> AsyncGenerator[dict[str, object], None]:
    """Uma linha real de codigos_gerados, com a cadeia de FKs que ela exige
    (usuario -> job -> regra -> prompt). O worker só tem SELECT nessa tabela, então a
    escrita usa o dono do schema, como o script de seed de deploy/scripts/seed.py.
    """
    import asyncpg

    conexao = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=os.environ.get("POSTGRES_OWNER_USER", "postgres"),
        password=os.environ.get("POSTGRES_OWNER_PASSWORD", "postgres"),
    )
    try:
        usuario_id: UUID = await conexao.fetchval(
            """
            INSERT INTO usuarios (login, senha_hash, nome, papel, criado_em)
            VALUES ($1, 'hash-de-teste', 'Usuário de teste', 'profissional_rh', now())
            RETURNING id
            """,
            f"teste-worker-{uuid4()}@synapse.local",
        )
        job_id: UUID = await conexao.fetchval(
            """
            INSERT INTO jobs (status, usuario_id, competencias, orcamento, criado_em)
            VALUES ('simulando', $1, $2, $3, now())
            RETURNING id
            """,
            usuario_id,
            ["2025-08"],
            100000.0,
        )
        nucleo = {"vigencia": {"inicio": "2025-08", "fim": "2025-08"}}
        regra_id: UUID = await conexao.fetchval(
            """
            INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
            VALUES ($1, 1, 'confirmacao_usuario', $2::jsonb, $3::jsonb, $4, now())
            RETURNING id
            """,
            job_id,
            json.dumps(nucleo),
            json.dumps([]),
            hashlib.sha256(json.dumps(nucleo).encode("utf-8")).hexdigest(),
        )
        prompt_id: UUID = await conexao.fetchval(
            """
            INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
            VALUES ($1, 'geracao_codigo', 'prompt de teste', $2::jsonb, now())
            RETURNING id
            """,
            job_id,
            json.dumps({"provedor": "teste", "modelo": "teste"}),
        )
        fonte = "def calcular(): return []"
        codigo_gerado_id: UUID = await conexao.fetchval(
            """
            INSERT INTO codigos_gerados (job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
            VALUES ($1, $2, 'python', $3, $4, now())
            RETURNING id
            """,
            job_id,
            regra_id,
            fonte,
            prompt_id,
        )

        yield {
            "id": codigo_gerado_id,
            "job_id": job_id,
            "linguagem": "python",
            "fonte": fonte,
        }

        await conexao.execute("DELETE FROM codigos_gerados WHERE id = $1", codigo_gerado_id)
        await conexao.execute("DELETE FROM prompts WHERE id = $1", prompt_id)
        await conexao.execute("DELETE FROM regras WHERE id = $1", regra_id)
        await conexao.execute("DELETE FROM jobs WHERE id = $1", job_id)
        await conexao.execute("DELETE FROM usuarios WHERE id = $1", usuario_id)
    finally:
        await conexao.close()


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
