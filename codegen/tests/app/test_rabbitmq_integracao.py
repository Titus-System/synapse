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
from aio_pika.abc import AbstractIncomingMessage
from aiormq.exceptions import ChannelNotFoundEntity

from app.config import Settings
from app.contratos.mensagens import (
    JobEncerrado,
    ModeloContrato,
    RegraSubmetida,
    SimulacaoConcluida,
)
from app.contratos.serializacao import serializar
from app.graph.nodes.dispatch_execution import dispatch_execution
from app.mensageria.broker import (
    EXCHANGE_SIMULACAO,
    FILA_SIMULACAO,
    ConexaoBroker,
    conectar,
)
from app.mensageria.consumers import Consumer
from app.mensageria.roteamento import Entrada
from tests.app.confirmacao_falsa import ConfirmacaoFalsa
from tests.app.test_mensageria import SAIDAS, exemplo, oficial, sugestao_do_exemplo

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


async def test_encerramento_da_api_chega_ao_codegen_pela_fila_propria(
    broker_real: ConexaoBroker,
) -> None:
    """A `api` publica `job-encerrado` na fila de mesmo nome (DEC-089), e só o codegen a lê."""
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    payload = exemplo("job-encerrado")
    corpo = simplejson.dumps(payload).encode()

    await broker_real.canal.default_exchange.publish(
        Message(body=corpo, content_type="application/json"), routing_key="job-encerrado"
    )
    job_id, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)

    assert isinstance(dto, JobEncerrado)
    assert str(job_id) == payload["job_id"]
    assert str(dto.evento_id) == payload["evento_id"]


async def test_resultado_do_worker_chega_ao_codegen_pelo_fanout(
    broker_real: ConexaoBroker,
) -> None:
    """O resultado publicado pelo worker é entregue ao roteador, que retoma o grafo."""
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    payload = exemplo("simulacao-concluida")
    corpo = simplejson.dumps(payload, use_decimal=True).encode()
    exchange = await broker_real.canal.get_exchange(EXCHANGE_SIMULACAO)
    assert broker_real.filas[FILA_SIMULACAO].name == "simulacao-concluida.codegen"

    await exchange.publish(Message(body=corpo, content_type="application/json"), routing_key="")

    job_id, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)
    assert isinstance(dto, SimulacaoConcluida)
    assert str(job_id) == payload["job_id"]
    assert simplejson.loads(serializar(dto), use_decimal=True) == payload


async def test_parametros_confirmados_drena_validas_duplicadas_e_invalidas(
    broker_real: ConexaoBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Broker e consumer reais; só banco, modelo e produtores do grafo são falsos."""
    ambiente = ConfirmacaoFalsa(monkeypatch)
    assentadas: asyncio.Queue[None] = asyncio.Queue()
    receber = Consumer.receber

    async def acompanhar(self: Consumer, mensagem: AbstractIncomingMessage) -> None:
        await receber(self, mensagem)
        assentadas.put_nowait(None)

    monkeypatch.setattr(Consumer, "receber", acompanhar)
    await broker_real.iniciar_consumers(ambiente.roteador)
    nome = "parametros-confirmados"
    valida = exemplo(nome)
    antiga = {"job_id": valida["job_id"], "regra_id": str(uuid4())}
    invalida = valida | {"competencias": []}
    corpos = [
        simplejson.dumps(p, use_decimal=True).encode() for p in (valida, antiga, invalida, valida)
    ]
    corpos.append(b"{")
    for corpo in corpos:
        await broker_real.canal.default_exchange.publish(
            Message(body=corpo, content_type="application/json"), routing_key=nome
        )
    for _ in corpos:
        await asyncio.wait_for(assentadas.get(), timeout=10)

    # `broker_real.canal` já declarou essa fila antes do consumer existir; um `declare_queue`
    # passivo nele devolve o `AbstractQueue` cacheado, com o `declaration_result` daquele
    # instante. Um canal novo não tem esse cache e força a reconsulta ao broker.
    canal_verificacao = await broker_real.conexao.channel()
    try:
        fila = await canal_verificacao.declare_queue(nome, passive=True)
        assert fila.declaration_result.consumer_count == 1
        assert fila.declaration_result.message_count == 0
    finally:
        if not canal_verificacao.is_closed:
            await canal_verificacao.close()
    assert len(ambiente.modelo.seen_messages) == 1
    ambiente.producers.executar_codigo.assert_awaited_once()
    assert (await ambiente.estado(antiga)).values == {}
    assert all(p.get("status") != "erro" for _, p in ambiente.publicacoes)


async def test_fanout_mantem_copia_na_fila_api(broker_real: ConexaoBroker) -> None:
    """Uma publicação rende duas cópias: uma para o codegen e uma para a `api`.

    A do codegen é consumida e entregue ao roteador; a da `api` espera o consumer dela, que
    não existe neste teste. O que se confere é que uma cópia não come a outra.
    """
    exchange = await broker_real.canal.get_exchange(EXCHANGE_SIMULACAO)
    fila_api = await broker_real.canal.declare_queue("simulacao-concluida.api", durable=True)
    await fila_api.bind(exchange, routing_key="")
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    corpo = simplejson.dumps(exemplo("simulacao-concluida")).encode()

    await exchange.publish(Message(body=corpo), routing_key="")

    _, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)
    assert isinstance(dto, SimulacaoConcluida)
    copia_api = await fila_api.get(timeout=10)
    assert copia_api.body == corpo
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


async def test_producer_real_entrega_a_sugestao_na_fila(broker_real: ConexaoBroker) -> None:
    """Fora da parametrização porque este DTO não tem volta por texto JSON (ver o unitário)."""
    nome = "sugestao-adaptacao-proposta"

    await broker_real.producers.sugestao_adaptacao_proposta(sugestao_do_exemplo())
    recebido = await broker_real.filas[nome].get(timeout=10)

    payload = simplejson.loads(recebido.body, use_decimal=True)
    oficial(nome).validate(payload)
    assert payload == exemplo(nome)
    assert recebido.routing_key == nome
    await recebido.ack()


@pytest.mark.parametrize(
    ("parametros", "esperados"),
    [
        (
            {"orcamento": "485000.10", "meta_venda": "26000000.123456789012345"},
            {
                "orcamento": Decimal("485000.10"),
                "meta_venda": Decimal("26000000.123456789012345"),
            },
        ),
        # O job sem orçamento nem meta: o worker simula sobre o histórico, sem veredito (T-281).
        ({}, {}),
    ],
    ids=["com-orcamento-e-meta", "sem-orcamento-e-meta"],
)
async def test_dispatch_execution_entrega_comando_persistente_e_valido(
    broker_real: ConexaoBroker, parametros: dict[str, str], esperados: dict[str, Decimal]
) -> None:
    job_id, codigo_gerado_id, regra_id = uuid4(), uuid4(), uuid4()
    estado = {
        "job_id": str(job_id),
        "regra_id": str(regra_id),
        "codigo_gerado_id": str(codigo_gerado_id),
        "competencias": ["2025-11"],
        "representacao_regra": {"nucleo": {"percentual": Decimal("0.025")}, "especificacoes": []},
        "codigo_fonte": "def aplicar_regra(bases, apuracao_base, competencias): ...",
        **parametros,
    }

    await dispatch_execution(estado, {"configurable": {"producers": broker_real.producers}})
    recebido = await broker_real.filas["executar-codigo"].get(timeout=10)

    payload = simplejson.loads(recebido.body, use_decimal=True)
    oficial("executar-codigo").validate(payload)
    assert payload == {
        "job_id": str(job_id),
        "codigo_gerado_id": str(codigo_gerado_id),
        "competencias": ["2025-11"],
        "proposito": "simulacao",
        "elementos_exigidos": ["nucleo.percentual"],
        **esperados,
    }
    assert recebido.delivery_mode == DeliveryMode.PERSISTENT
    await recebido.ack()

    # Os outros dois eventos do nó chegam nas filas deles, válidos no contrato: o progresso
    # que move o job e a linha de trilha desta etapa.
    etapa = await broker_real.filas["etapa-alterada"].get(timeout=10)
    oficial("etapa-alterada").validate(simplejson.loads(etapa.body, use_decimal=True))
    await etapa.ack()

    trilha = await broker_real.filas["no-concluido"].get(timeout=10)
    conclusao = simplejson.loads(trilha.body, use_decimal=True)
    oficial("no-concluido").validate(conclusao)
    assert conclusao["no"] == "delegacao_worker"
    assert conclusao["regra_id"] == str(regra_id)
    assert "codigo_gerado_id" not in conclusao
    await trilha.ack()
