import asyncio
import os
import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import simplejson
from aio_pika import Message
from aiormq.exceptions import ChannelNotFoundEntity

from app.config import Settings
from app.mensageria.broker import EXCHANGE_SIMULACAO, FILA_SIMULACAO, ConexaoBroker, conectar
from app.mensageria.contratos import (
    Entrada,
    Mensagem,
    ParametrosConfirmados,
    RegraSubmetida,
    SimulacaoConcluida,
)
from tests.app.test_mensageria import SAIDAS, exemplo, oficial

pytestmark = [
    pytest.mark.rabbitmq,
    pytest.mark.skipif(
        os.getenv("RUN_RABBITMQ_INTEGRATION") != "1",
        reason="Requer RabbitMQ real do deploy/docker-compose.yml; RUN_RABBITMQ_INTEGRATION=1",
    ),
]
COMPOSE = Path(__file__).resolve().parents[3] / "deploy" / "docker-compose.yml"


def rabbitmqctl(*argumentos: str) -> None:
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
async def broker_real() -> AsyncGenerator[ConexaoBroker, None]:
    # Vhost próprio evita consumir ou apagar mensagens do ambiente de desenvolvimento.
    vhost = f"t049-{uuid4()}"
    config = Settings(RABBITMQ_VHOST=vhost)
    await asyncio.to_thread(rabbitmqctl, "add_vhost", vhost)
    try:
        await asyncio.to_thread(
            rabbitmqctl, "set_permissions", "-p", vhost, config.RABBITMQ_USER, ".*", ".*", ".*"
        )
        broker = await conectar(config)
        try:
            yield broker
        finally:
            await broker.fechar()
    finally:
        await asyncio.to_thread(rabbitmqctl, "delete_vhost", vhost)


class RoteadorTeste:
    def __init__(self) -> None:
        self.entregas: asyncio.Queue[tuple[UUID, Entrada]] = asyncio.Queue()

    async def entregar(self, job_id: UUID, mensagem: Entrada) -> None:
        await self.entregas.put((job_id, mensagem))


@pytest.mark.parametrize("modelo", [RegraSubmetida, ParametrosConfirmados, SimulacaoConcluida])
async def test_broker_real_entrega_ao_codegen_sem_api(
    broker_real: ConexaoBroker,
    modelo: type[Entrada],
) -> None:
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    canal_verificacao = await broker_real.conexao.channel()
    try:
        with pytest.raises(ChannelNotFoundEntity):
            await canal_verificacao.declare_queue("simulacao-concluida.api", passive=True)
    finally:
        if not canal_verificacao.is_closed:
            await canal_verificacao.close()
    payload = exemplo(modelo.nome)
    corpo = simplejson.dumps(payload, use_decimal=True).encode()
    if modelo is SimulacaoConcluida:
        exchange = await broker_real.canal.get_exchange(EXCHANGE_SIMULACAO)
        rota = ""
        assert broker_real.filas[FILA_SIMULACAO].name == "simulacao-concluida.codegen"
    else:
        exchange = broker_real.canal.default_exchange
        rota = modelo.nome

    await exchange.publish(Message(body=corpo, content_type="application/json"), routing_key=rota)
    job_id, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)

    assert isinstance(dto, modelo)
    assert str(job_id) == payload["job_id"]
    assert simplejson.loads(dto.serializar(), use_decimal=True) == payload


async def test_fanout_mantem_copia_na_fila_api_sem_consumer(broker_real: ConexaoBroker) -> None:
    exchange = await broker_real.canal.get_exchange(EXCHANGE_SIMULACAO)
    fila_api = await broker_real.canal.declare_queue("simulacao-concluida.api", durable=True)
    await fila_api.bind(exchange, routing_key="")
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    corpo = simplejson.dumps(exemplo("simulacao-concluida")).encode()

    await exchange.publish(Message(body=corpo), routing_key="")
    _, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)
    copia_api = await fila_api.get(timeout=10)

    assert isinstance(dto, SimulacaoConcluida)
    assert copia_api.body == corpo
    await copia_api.ack()


@pytest.mark.parametrize("modelo,metodo", SAIDAS)
async def test_producer_real_entrega_payload_oficial_na_fila(
    broker_real: ConexaoBroker,
    modelo: type[Mensagem],
    metodo: str,
) -> None:
    dto = modelo.model_validate(exemplo(modelo.nome))

    await getattr(broker_real.producers, metodo)(dto)
    recebido = await broker_real.filas[modelo.nome].get(timeout=10)

    payload = simplejson.loads(recebido.body, use_decimal=True)
    oficial(modelo.nome).validate(payload)
    assert payload == exemplo(modelo.nome)
    assert recebido.exchange == ""
    assert recebido.routing_key == modelo.nome
    await recebido.ack()
