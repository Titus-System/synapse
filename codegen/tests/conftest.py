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
