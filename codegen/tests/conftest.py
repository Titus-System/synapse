import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from app.config import Settings

# get_settings usa cache após a primeira importação; por isso, o ambiente é definido antes dela.
load_dotenv(Path(__file__).resolve().parents[1] / ".env.test", override=True)
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("LOG_LEVEL", "CRITICAL")


@pytest.fixture(scope="session")
def configuracoes() -> "Settings":
    from app.config import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def aplicacao() -> FastAPI:
    """Evita sombrear o pacote ``app`` dentro dos módulos de teste."""
    from app.main import criar_aplicacao

    return criar_aplicacao()


@pytest.fixture
async def cliente(aplicacao: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """O ciclo de vida é compartilhado para não encerrar o ouvinte de logs entre testes."""
    async with AsyncClient(
        transport=ASGITransport(app=aplicacao), base_url="http://test"
    ) as cliente_http:
        yield cliente_http
