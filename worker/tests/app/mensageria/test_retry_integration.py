"""Retry/DLQ no RabbitMQ do deploy, em vhost isolado e sem banco ou API."""

import asyncio
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aio_pika import DeliveryMode, Message

from app.config import Settings
from app.mensageria import broker as modulo_broker
from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker, conectar, desconectar
from tests.app.mensageria.test_consumidor import _corpo_comando, _SessionmakerFalso

pytestmark = pytest.mark.rabbitmq
COMPOSE = Path(__file__).resolve().parents[4] / "deploy" / "docker-compose.yml"


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


@pytest.mark.parametrize(
    "contador,permanente", [(None, False), (1, False), (2, False), (None, True)]
)
async def test_republicacao_real_preserva_corpo_e_remove_original(
    broker_real: ConexaoBroker,
    monkeypatch: pytest.MonkeyPatch,
    contador: int | None,
    permanente: bool,
) -> None:
    monkeypatch.setattr(consumidor, "get_sessionmaker", lambda: _SessionmakerFalso())
    monkeypatch.setattr(consumidor, "buscar_codigo", AsyncMock(side_effect=ConnectionError()))
    corpo = b"{}" if permanente else _corpo_comando()
    headers = {"traceparent": "contexto"}
    if contador is not None:
        headers["synapse_retry_count"] = contador
    await broker_real.canal.default_exchange.publish(
        Message(
            body=corpo,
            headers=headers,
            content_type="application/json",
            correlation_id="correlacao",
            message_id="mensagem",
            type="executar-codigo",
            delivery_mode=DeliveryMode.PERSISTENT,
        ),
        routing_key=broker_real.fila.name,
        mandatory=True,
    )
    original = await broker_real.fila.get(timeout=5)

    await consumidor._processar(original, broker_real)
    # Fechar o canal devolve qualquer original sem ACK antes de verificar as filas.
    await broker_real.canal.close()
    canal = await broker_real.conexao.channel()
    fila = await canal.declare_queue("executar-codigo", passive=True)
    dlq = await canal.declare_queue("executar-codigo.dlq", passive=True)
    terminal = permanente or contador == 2
    destino, vazia = (dlq, fila) if terminal else (fila, dlq)
    assert destino.declaration_result.message_count == 1
    assert vazia.declaration_result.message_count == 0
    copia = await destino.get(timeout=5)
    assert copia.body == corpo
    assert copia.headers == (
        headers if terminal else {**headers, "synapse_retry_count": (contador or 0) + 1}
    )
    assert copia.delivery_mode == DeliveryMode.PERSISTENT
    assert copia.content_type == "application/json"
    assert copia.correlation_id == "correlacao"
    assert copia.message_id == "mensagem"
    assert copia.type == "executar-codigo"
    await copia.ack()


async def test_destino_inexistente_devolve_original_ao_broker(broker_real: ConexaoBroker) -> None:
    dlq = await broker_real.canal.get_queue("executar-codigo.dlq")
    await dlq.delete()
    await broker_real.canal.default_exchange.publish(
        Message(body=b"{}", delivery_mode=DeliveryMode.PERSISTENT),
        routing_key=broker_real.fila.name,
        mandatory=True,
    )
    original = await broker_real.fila.get(timeout=5)

    await consumidor._processar(original, broker_real)
    await broker_real.canal.close()
    canal = await broker_real.conexao.channel()
    fila = await canal.declare_queue("executar-codigo", passive=True)

    assert fila.declaration_result.message_count == 1
    reentregue = await fila.get(timeout=5)
    assert reentregue.body == b"{}"
    assert reentregue.redelivered
    await reentregue.ack()
