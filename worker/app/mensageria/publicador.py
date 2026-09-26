"""Publicação de `simulacao-concluida` na exchange fanout (T-067).

O evento leva a referência da linha e os poucos agregados do schema, nunca o conteúdo (claim-check,
ARCHITECTURE.md §6.1): quem precisa da decomposição ou das asserções lê a linha.

A publicação é `mandatory` e espera a confirmação do broker. Uma exchange fanout sem nenhuma fila
ligada **descarta a mensagem em silêncio**, e é o que acontece se o worker publicar antes de a api
e o codegen declararem as suas filas (DEC-089: cada um declara o próprio lado). Com `mandatory`
isso vira uma falha visível, e o comando segue para o retry: a linha já está gravada, e a próxima
tentativa a encontra e só republica.
"""

from aio_pika import DeliveryMode, Message
from pamqp.commands import Basic

from app.config import get_settings
from app.core.logger import get_logger
from app.mensageria.broker import ConexaoBroker
from app.mensageria.contracts import SimulacaoConcluida

logger = get_logger("app.mensageria.publicador")


class PublicacaoError(Exception):
    """O broker não confirmou a entrega: recusa, mensagem sem rota, canal ou conexão caídos."""


def mensagem_do_evento(evento: SimulacaoConcluida) -> Message:
    return Message(
        body=evento.model_dump_json(exclude_none=True).encode("utf-8"),
        content_type="application/json",
        content_encoding="utf-8",
        delivery_mode=DeliveryMode.PERSISTENT,
        type="simulacao-concluida",
        # Estável entre republicações do mesmo resultado: quem quiser deduplicar tem por onde.
        message_id=str(evento.resultado_id),
        correlation_id=str(evento.job_id),
        app_id=get_settings().SERVICE_NAME,
    )


async def publicar_simulacao_concluida(broker: ConexaoBroker, evento: SimulacaoConcluida) -> None:
    """Publica e espera a confirmação; qualquer outra coisa é `PublicacaoError`."""
    try:
        confirmacao = await broker.exchange.publish(
            mensagem_do_evento(evento), routing_key="", mandatory=True
        )
    except Exception as erro:
        raise PublicacaoError("publicação de simulacao-concluida falhou") from erro
    if not isinstance(confirmacao, Basic.Ack):
        raise PublicacaoError("publicação de simulacao-concluida sem confirmação positiva")
    logger.info(
        "simulacao-concluida publicada",
        extra={"resultado_id": str(evento.resultado_id), "status": evento.status},
    )
