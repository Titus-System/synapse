"""A exchange fanout de `simulacao-concluida` num RabbitMQ real (T-067), em vhost isolado.

Cada consumidor declara a própria fila e a liga à exchange (DEC-089), então os testes fazem o
mesmo que a api (`simulacao-concluida.api`) e o codegen (`simulacao-concluida.codegen`) fazem.
"Consumidor desligado" é a fila existir, durável, sem ninguém lendo dela: as mensagens ficam
esperando, e é isso que o outro lado não pode notar.
"""

import json
from typing import Any
from uuid import uuid4

import pytest
from aio_pika import DeliveryMode, ExchangeType
from aio_pika.abc import AbstractQueue
from aio_pika.exceptions import ChannelPreconditionFailed

from app.mensageria.broker import EXCHANGE_SIMULACAO_CONCLUIDA, ConexaoBroker
from app.mensageria.contracts import SimulacaoConcluida
from app.mensageria.publicador import PublicacaoError, publicar_simulacao_concluida
from tests.app.esquemas import erros_do_evento

pytestmark = pytest.mark.rabbitmq

FILA_API = "simulacao-concluida.api"
FILA_CODEGEN = "simulacao-concluida.codegen"

EVENTO = SimulacaoConcluida(
    job_id=uuid4(),
    resultado_id=uuid4(),
    status="sucesso",
    veredito="viavel",
    total_baseline=480312.0,
    total_simulado=482000.0,
    diferenca_abs=1688.0,
    diferenca_pct=0.0035,
)


async def declarar_fila(broker: ConexaoBroker, nome: str) -> AbstractQueue:
    """O que um consumidor faz ao subir: declara a fila durável e a liga à exchange."""
    canal = await broker.conexao.channel()
    fila = await canal.declare_queue(nome, durable=True)
    exchange = await canal.declare_exchange(
        EXCHANGE_SIMULACAO_CONCLUIDA, ExchangeType.FANOUT, durable=True
    )
    await fila.bind(exchange, routing_key="")
    return fila


async def retirar(fila: AbstractQueue) -> Any:
    """Lê de verdade o que está pronto na fila, ou `None` se ela está vazia."""
    mensagem = await fila.get(fail=False, timeout=5)
    if mensagem is None:
        return None
    await mensagem.ack()
    return mensagem


async def test_api_e_codegen_recebem_o_mesmo_evento_cada_um_pela_sua_fila(
    broker_real: ConexaoBroker,
) -> None:
    api = await declarar_fila(broker_real, FILA_API)
    codegen = await declarar_fila(broker_real, FILA_CODEGEN)

    await publicar_simulacao_concluida(broker_real, EVENTO)

    da_api, do_codegen = await retirar(api), await retirar(codegen)
    assert da_api is not None and do_codegen is not None
    assert da_api.body == do_codegen.body
    corpo = json.loads(da_api.body)
    assert corpo["resultado_id"] == str(EVENTO.resultado_id)
    assert erros_do_evento("simulacao-concluida", corpo) == []
    assert da_api.content_type == "application/json"
    assert da_api.delivery_mode == DeliveryMode.PERSISTENT
    assert da_api.message_id == str(EVENTO.resultado_id)
    assert await retirar(api) is None and await retirar(codegen) is None


async def test_com_a_api_desligada_o_codegen_continua_recebendo(
    broker_real: ConexaoBroker,
) -> None:
    api = await declarar_fila(broker_real, FILA_API)  # existe, mas ninguém lê dela
    codegen = await declarar_fila(broker_real, FILA_CODEGEN)

    await publicar_simulacao_concluida(broker_real, EVENTO)

    assert await retirar(codegen) is not None
    # A api, ao voltar, encontra o evento esperando: desligada, não perdeu nada.
    assert await retirar(api) is not None


async def test_com_o_codegen_desligado_a_api_continua_recebendo(
    broker_real: ConexaoBroker,
) -> None:
    api = await declarar_fila(broker_real, FILA_API)
    codegen = await declarar_fila(broker_real, FILA_CODEGEN)  # existe, mas ninguém lê dela

    await publicar_simulacao_concluida(broker_real, EVENTO)

    assert await retirar(api) is not None
    assert await retirar(codegen) is not None


async def test_fila_que_nunca_foi_declarada_nao_impede_a_outra(
    broker_real: ConexaoBroker,
) -> None:
    codegen = await declarar_fila(broker_real, FILA_CODEGEN)

    await publicar_simulacao_concluida(broker_real, EVENTO)

    assert await retirar(codegen) is not None


async def test_sem_nenhuma_fila_ligada_a_publicacao_falha_em_vez_de_sumir(
    broker_real: ConexaoBroker,
) -> None:
    """Fanout sem fila descarta em silêncio. Com `mandatory` o broker devolve a mensagem, e o
    worker sabe que o evento não chegou a ninguém."""
    with pytest.raises(PublicacaoError):
        await publicar_simulacao_concluida(broker_real, EVENTO)


async def test_o_canal_continua_utilizavel_depois_de_uma_publicacao_sem_rota(
    broker_real: ConexaoBroker,
) -> None:
    """A tentativa seguinte do mesmo comando publica no mesmo canal: uma devolução não pode
    deixá-lo quebrado."""
    with pytest.raises(PublicacaoError):
        await publicar_simulacao_concluida(broker_real, EVENTO)
    codegen = await declarar_fila(broker_real, FILA_CODEGEN)

    await publicar_simulacao_concluida(broker_real, EVENTO)

    assert await retirar(codegen) is not None


async def test_o_evento_publicado_antes_de_alguma_fila_existir_nao_aparece_depois(
    broker_real: ConexaoBroker,
) -> None:
    """O evento não é retido pela exchange: quem liga a fila depois não recebe o que passou.
    É por isso que a linha é a fonte de verdade e o evento, o aviso (reconciliável pelo banco)."""
    with pytest.raises(PublicacaoError):
        await publicar_simulacao_concluida(broker_real, EVENTO)

    codegen = await declarar_fila(broker_real, FILA_CODEGEN)

    assert await retirar(codegen) is None


async def test_a_exchange_e_fanout_duravel_e_sem_argumentos(
    broker_real: ConexaoBroker,
) -> None:
    """A declaração do worker é a mesma que a da api e a do codegen: redeclarar igual passa, e
    redeclarar diferente é rejeitado com 406 (DEC-089), e não perde mensagem em silêncio."""
    canal = await broker_real.conexao.channel()
    await canal.declare_exchange(EXCHANGE_SIMULACAO_CONCLUIDA, ExchangeType.FANOUT, durable=True)

    canal_diferente = await broker_real.conexao.channel()
    with pytest.raises(ChannelPreconditionFailed):
        await canal_diferente.declare_exchange(
            EXCHANGE_SIMULACAO_CONCLUIDA, ExchangeType.DIRECT, durable=True
        )
