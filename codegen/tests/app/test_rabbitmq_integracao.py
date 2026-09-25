import asyncio
import os
import subprocess
from collections.abc import AsyncGenerator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import simplejson
from aio_pika import DeliveryMode, Message
from aiormq.exceptions import ChannelNotFoundEntity

from app.config import Settings
from app.contratos.mensagens import (
    ModeloContrato,
    RegraSubmetida,
)
from app.contratos.serializacao import serializar
from app.graph.nodes.dispatch_execution import dispatch_execution
from app.mensageria.broker import EXCHANGE_SIMULACAO, FILA_SIMULACAO, ConexaoBroker, conectar
from app.mensageria.roteamento import Entrada
from tests.app.test_mensageria import ENTRADAS, SAIDAS, exemplo, oficial

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


async def test_broker_real_entrega_ao_codegen_sem_api(broker_real: ConexaoBroker) -> None:
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    canal_verificacao = await broker_real.conexao.channel()
    try:
        with pytest.raises(ChannelNotFoundEntity):
            await canal_verificacao.declare_queue("simulacao-concluida.api", passive=True)
    finally:
        if not canal_verificacao.is_closed:
            await canal_verificacao.close()
    payload = exemplo("regra-submetida")
    corpo = simplejson.dumps(payload, use_decimal=True).encode()

    await broker_real.canal.default_exchange.publish(
        Message(body=corpo, content_type="application/json"), routing_key="regra-submetida"
    )
    job_id, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)

    assert isinstance(dto, RegraSubmetida)
    assert str(job_id) == payload["job_id"]
    assert simplejson.loads(serializar(dto), use_decimal=True) == payload


@pytest.mark.parametrize(
    "nome", [nome for _, nome in ENTRADAS if nome != "regra-submetida"], ids=str
)
async def test_filas_sem_consumer_preservam_as_mensagens(
    broker_real: ConexaoBroker, nome: str
) -> None:
    """`parametros-confirmados` e `simulacao-concluida` ficam retidas, não descartadas.

    Retomar um grafo pausado com `Command(resume=...)` ainda não existe, então
    `iniciar_consumers` sobe só `regra-submetida`. O que esta garantia protege é o
    resultado do worker: ele espera na fila até a retomada existir, sem perda.
    """
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    corpo = simplejson.dumps(exemplo(nome), use_decimal=True).encode()
    if nome == "simulacao-concluida":
        exchange = await broker_real.canal.get_exchange(EXCHANGE_SIMULACAO)
        rota = ""
        fila = broker_real.filas[FILA_SIMULACAO]
        assert fila.name == "simulacao-concluida.codegen"
    else:
        exchange = broker_real.canal.default_exchange
        rota = nome
        fila = broker_real.filas[nome]

    await exchange.publish(Message(body=corpo, content_type="application/json"), routing_key=rota)

    retida = await fila.get(timeout=10)
    assert retida.body == corpo
    await retida.ack()
    assert roteador.entregas.empty()


async def test_fanout_mantem_copia_na_fila_api_sem_consumer(broker_real: ConexaoBroker) -> None:
    """Uma publicação rende duas cópias: uma para o codegen e uma para a `api`.

    Nenhuma das duas é consumida aqui - o codegen ainda não sobe consumer nessa fila, e a
    `api` não tem consumer neste teste. O que se confere é a duplicação do fanout.
    """
    exchange = await broker_real.canal.get_exchange(EXCHANGE_SIMULACAO)
    fila_api = await broker_real.canal.declare_queue("simulacao-concluida.api", durable=True)
    await fila_api.bind(exchange, routing_key="")
    await broker_real.iniciar_consumers(RoteadorTeste())
    corpo = simplejson.dumps(exemplo("simulacao-concluida")).encode()

    await exchange.publish(Message(body=corpo), routing_key="")

    copia_codegen = await broker_real.filas[FILA_SIMULACAO].get(timeout=10)
    copia_api = await fila_api.get(timeout=10)
    assert copia_codegen.body == corpo
    assert copia_api.body == corpo
    await copia_codegen.ack()
    await copia_api.ack()


@pytest.mark.parametrize("modelo,nome,metodo", SAIDAS)
async def test_producer_real_entrega_payload_oficial_na_fila(
    broker_real: ConexaoBroker,
    modelo: type[ModeloContrato],
    nome: str,
    metodo: str,
) -> None:
    dto = modelo.model_validate_json(simplejson.dumps(exemplo(nome)))

    await getattr(broker_real.producers, metodo)(dto)
    recebido = await broker_real.filas[nome].get(timeout=10)

    payload = simplejson.loads(recebido.body, use_decimal=True)
    oficial(nome).validate(payload)
    assert payload == exemplo(nome)
    assert recebido.exchange == ""
    assert recebido.routing_key == nome
    await recebido.ack()


async def test_dispatch_execution_entrega_comando_persistente_e_valido(
    broker_real: ConexaoBroker,
) -> None:
    job_id, codigo_gerado_id = uuid4(), uuid4()
    estado = {
        "job_id": str(job_id),
        "codigo_gerado_id": str(codigo_gerado_id),
        "competencias": ["2025-11"],
        "orcamento": "485000.10",
        "codigo_fonte": "def aplicar_regra(bases, apuracao_base, competencias): ...",
    }

    await dispatch_execution(estado, {"configurable": {"producers": broker_real.producers}})
    recebido = await broker_real.filas["executar-codigo"].get(timeout=10)

    payload = simplejson.loads(recebido.body, use_decimal=True)
    oficial("executar-codigo").validate(payload)
    assert payload == {
        "job_id": str(job_id),
        "codigo_gerado_id": str(codigo_gerado_id),
        "competencias": ["2025-11"],
        "orcamento": Decimal("485000.10"),
    }
    assert recebido.delivery_mode == DeliveryMode.PERSISTENT
    await recebido.ack()
