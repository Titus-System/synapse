"""Retry de erro_infra e entrega terminal do comando, conforme DEC-091."""

from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractIncomingMessage
from pamqp.commands import Basic

from app.core.logger import get_logger
from app.mensageria.broker import ConexaoBroker

logger = get_logger("app.mensageria.retry")
HEADER_RETRY = "synapse_retry_count"
MAX_REPUBLICACOES = 2


async def repetir_erro_infra(mensagem: AbstractIncomingMessage, broker: ConexaoBroker) -> None:
    """Recebe apenas falhas já classificadas como infraestrutura pelo chamador."""
    contador = mensagem.headers.get(HEADER_RETRY, 0)
    # Metadata inválida não pode reiniciar o limite de tentativas.
    if type(contador) is not int or contador < 0 or contador >= MAX_REPUBLICACOES:
        await enviar_dlq(mensagem, broker)
        return
    await _republicar(mensagem, broker, broker.fila.name, contador + 1)


async def enviar_dlq(mensagem: AbstractIncomingMessage, broker: ConexaoBroker) -> None:
    await _republicar(mensagem, broker, f"{broker.fila.name}.dlq")


async def _republicar(
    mensagem: AbstractIncomingMessage,
    broker: ConexaoBroker,
    destino: str,
    contador: int | None = None,
) -> None:
    headers = dict(mensagem.headers)
    if contador is not None:
        headers[HEADER_RETRY] = contador
    try:
        copia = Message(
            body=mensagem.body,
            headers=headers,
            content_type=mensagem.content_type,
            content_encoding=mensagem.content_encoding,
            correlation_id=mensagem.correlation_id,
            message_id=mensagem.message_id,
            type=mensagem.type,
            app_id=mensagem.app_id,
            reply_to=mensagem.reply_to,
            priority=mensagem.priority,
            timestamp=mensagem.timestamp,
            delivery_mode=DeliveryMode.PERSISTENT,
        )
        confirmacao = await broker.canal.default_exchange.publish(
            copia, routing_key=destino, mandatory=True
        )
        if not isinstance(confirmacao, Basic.Ack):
            raise RuntimeError("republicação sem confirmação positiva")
    except Exception:
        logger.error("republicação falhou; original será reentregue", extra={"fila": destino})
        await mensagem.nack(requeue=True)
        return
    await mensagem.ack()
