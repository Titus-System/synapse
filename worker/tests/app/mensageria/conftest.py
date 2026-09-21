import asyncio
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import Settings
from app.mensageria import broker as modulo_broker
from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker, conectar, desconectar
from tests.app.mensageria.sandbox_falso import SandboxFalso

COMPOSE = Path(__file__).resolve().parents[4] / "deploy" / "docker-compose.yml"


@pytest.fixture(autouse=True)
def sandbox(monkeypatch: pytest.MonkeyPatch) -> SandboxFalso:
    """Autouse: um teste do consumidor que esquecesse de substituir o executor subiria um
    container de verdade, e sem a imagem construída o comando iria para o retry."""
    falso = SandboxFalso()
    monkeypatch.setattr(consumidor, "executar_no_sandbox", falso)
    return falso


def _rabbitmqctl(*argumentos: str) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "exec",
            "-T",
            "rabbitmq",
            "rabbitmqctl",
            *argumentos,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture
async def broker_real(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> AsyncIterator[ConexaoBroker]:
    """Um vhost novo por teste: as filas do teste não tocam as do deploy."""
    vhost = f"t049-worker-{uuid4().hex}"
    config = settings.model_copy(update={"RABBITMQ_VHOST": vhost})
    await asyncio.to_thread(_rabbitmqctl, "add_vhost", vhost)
    try:
        await asyncio.to_thread(
            _rabbitmqctl, "set_permissions", "-p", vhost, config.RABBITMQ_USER, ".*", ".*", ".*"
        )
        monkeypatch.setattr(modulo_broker, "get_settings", lambda: config)
        broker = await conectar()
        try:
            yield broker
        finally:
            await desconectar(broker)
    finally:
        await asyncio.to_thread(_rabbitmqctl, "delete_vhost", vhost)
