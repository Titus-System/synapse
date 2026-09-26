"""Fixtures dos e2e do ciclo de vida do worker (marcador `e2e`).

Pedem, juntos, o compose de pé (Postgres e RabbitMQ), o daemon Docker e a imagem do sandbox, que a
fixture `imagem` constrói uma vez por sessão. Cada teste ganha um vhost novo do RabbitMQ, então um
worker do compose de pé não vê nem rouba as mensagens.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.config import Settings
from tests.app.conftest import imagem  # noqa: F401  (fixture de sessão que constrói a imagem)
from tests.e2e.apoio import Ambiente, Corretor
from tests.rabbitmqctl import rabbitmqctl


@pytest.fixture
async def ambiente(
    settings: Settings,
    conexao_dono: Any,
    imagem: str,  # noqa: F811
    tmp_path: Path,
) -> AsyncIterator[Ambiente]:
    vhost = f"e2e-worker-{uuid4().hex}"
    await asyncio.to_thread(rabbitmqctl, "add_vhost", vhost)
    try:
        await asyncio.to_thread(
            rabbitmqctl, "set_permissions", "-p", vhost, settings.RABBITMQ_USER, ".*", ".*", ".*"
        )
        corretor = Corretor(vhost, settings)
        await corretor.abrir()
        ambiente = Ambiente(settings, corretor, conexao_dono, imagem, tmp_path)
        try:
            yield ambiente
        finally:
            await ambiente.encerrar()
    finally:
        await asyncio.to_thread(rabbitmqctl, "delete_vhost", vhost)
