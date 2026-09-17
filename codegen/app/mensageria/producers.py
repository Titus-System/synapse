import simplejson
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractChannel

from app.contratos.mensagens import (
    EtapaAlterada,
    ExecutarCodigo,
    NoConcluido,
)
from app.contratos.serializacao import serializar
from app.contratos.validacao import validar

type Saida = ExecutarCodigo | EtapaAlterada | NoConcluido


class ProdutorError(Exception):
    pass


class Producers:
    def __init__(self, canal: AbstractChannel) -> None:
        self._canal = canal

    async def _publicar(self, dto: Saida, nome: str) -> None:
        try:
            corpo = serializar(dto)
            validar(nome, simplejson.loads(corpo, use_decimal=True))
        except (ValueError, TypeError):
            raise ProdutorError("Payload inválido; publicação recusada") from None
        await self._canal.default_exchange.publish(
            Message(
                body=corpo,
                content_type="application/json",
                content_encoding="utf-8",
                delivery_mode=DeliveryMode.PERSISTENT,
                correlation_id=str(dto.job_id),
                message_id=str(dto.evento_id) if isinstance(dto, NoConcluido) else None,
                type=nome,
            ),
            routing_key=nome,
            mandatory=True,
        )

    async def executar_codigo(self, dto: ExecutarCodigo) -> None:
        await self._publicar(dto, "executar-codigo")

    async def etapa_alterada(self, dto: EtapaAlterada) -> None:
        await self._publicar(dto, "etapa-alterada")

    async def no_concluido(self, dto: NoConcluido) -> None:
        await self._publicar(dto, "no-concluido")
