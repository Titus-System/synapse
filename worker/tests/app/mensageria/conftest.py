import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from app.config import Settings
from app.mensageria import broker as modulo_broker
from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker, conectar, desconectar
from tests.app.mensageria import resultado_falso
from tests.app.mensageria.resultado_falso import BancoDeResultadosFalso
from tests.app.mensageria.sandbox_falso import SandboxFalso
from tests.rabbitmqctl import rabbitmqctl


@pytest.fixture(autouse=True)
def sandbox(monkeypatch: pytest.MonkeyPatch) -> SandboxFalso:
    """Autouse: um teste do consumidor que esquecesse de substituir o executor subiria um
    container de verdade, e sem a imagem construída o comando iria para o retry."""
    falso = SandboxFalso()
    monkeypatch.setattr(consumidor, "executar_no_sandbox", falso)
    return falso


@pytest.fixture(autouse=True)
def banco(monkeypatch: pytest.MonkeyPatch) -> BancoDeResultadosFalso:
    """Autouse: um teste do consumidor que esquecesse de substituir o banco de resultados
    gravaria uma linha de verdade, e uma que a suíte não saberia apagar (o worker só tem INSERT)."""
    resultado_falso.DIARIO.clear()
    falso = BancoDeResultadosFalso()
    monkeypatch.setattr(consumidor, "buscar_resultado", falso.buscar)
    monkeypatch.setattr(consumidor, "gravar_resultado", falso.gravar)
    return falso


@pytest.fixture
async def broker_real(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> AsyncIterator[ConexaoBroker]:
    """Um vhost novo por teste: as filas do teste não tocam as do deploy."""
    vhost = f"t049-worker-{uuid4().hex}"
    config = settings.model_copy(update={"RABBITMQ_VHOST": vhost})
    await asyncio.to_thread(rabbitmqctl, "add_vhost", vhost)
    try:
        await asyncio.to_thread(
            rabbitmqctl, "set_permissions", "-p", vhost, config.RABBITMQ_USER, ".*", ".*", ".*"
        )
        monkeypatch.setattr(modulo_broker, "get_settings", lambda: config)
        broker = await conectar()
        try:
            yield broker
        finally:
            await desconectar(broker)
    finally:
        await asyncio.to_thread(rabbitmqctl, "delete_vhost", vhost)
