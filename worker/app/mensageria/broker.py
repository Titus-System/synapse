from dataclasses import dataclass

from aio_pika import connect_robust
from aio_pika.abc import AbstractChannel, AbstractQueue, AbstractRobustConnection

from app.config import get_settings
from app.core.logger import get_logger

logger = get_logger("app.mensageria.broker")


@dataclass(frozen=True)
class ConexaoBroker:
    """Handles abertos do broker, mantidos pelo lifespan até o encerramento."""

    conexao: AbstractRobustConnection
    canal: AbstractChannel
    fila: AbstractQueue


async def conectar() -> ConexaoBroker:
    settings = get_settings()

    conexao = await connect_robust(settings.rabbitmq_url)
    canal = await conexao.channel(publisher_confirms=True, on_return_raises=True)
    await canal.set_qos(prefetch_count=settings.RABBITMQ_PREFETCH)
    fila = await canal.declare_queue(settings.RABBITMQ_FILA_EXECUCAO, durable=True)
    await canal.declare_queue(
        f"{settings.RABBITMQ_FILA_EXECUCAO}.dlq",
        durable=True,
        exclusive=False,
        auto_delete=False,
    )

    logger.info(
        "fila de execução declarada",
        extra={
            "broker_host": settings.RABBITMQ_HOST,
            "broker_port": settings.RABBITMQ_PORT,
            "fila": settings.RABBITMQ_FILA_EXECUCAO,
            "prefetch": settings.RABBITMQ_PREFETCH,
        },
    )

    return ConexaoBroker(conexao=conexao, canal=canal, fila=fila)


async def desconectar(broker: ConexaoBroker) -> None:
    await broker.conexao.close()
    logger.info("conexão com o broker encerrada")
