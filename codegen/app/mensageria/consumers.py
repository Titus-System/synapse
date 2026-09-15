import asyncio
from contextlib import suppress
from uuid import UUID

import simplejson
from aio_pika.abc import AbstractIncomingMessage

from app.core.logger import get_logger, job_id_ctx
from app.mensageria.contratos import Entrada, validar
from app.mensageria.roteamento import JobDesconhecidoError, RoteadorGrafo

logger = get_logger("app.mensageria.consumers")


class Consumer:
    def __init__(self, modelo: type[Entrada], roteador: RoteadorGrafo) -> None:
        self.modelo = modelo
        self.roteador = roteador
        self._ativos: set[asyncio.Task[None]] = set()

    async def aguardar(self) -> None:
        if self._ativos:
            await asyncio.gather(*self._ativos, return_exceptions=True)

    async def receber(self, mensagem: AbstractIncomingMessage) -> None:
        tarefa = asyncio.current_task()
        if tarefa is not None:
            self._ativos.add(tarefa)
        token = job_id_ctx.set(None)
        try:
            try:
                payload = simplejson.loads(mensagem.body, use_decimal=True)
                if isinstance(payload, dict) and isinstance(payload.get("job_id"), str):
                    with suppress(ValueError):
                        job_id_ctx.set(str(UUID(payload["job_id"])))
                validar(self.modelo.nome, payload)
                dto = self.modelo.model_validate(payload)
            except ValueError:
                logger.warning(
                    "mensagem inválida rejeitada",
                    extra={
                        "tipo_mensagem": self.modelo.nome,
                        "causa": "contrato_invalido",
                        "decisao": "reject_sem_requeue",
                    },
                )
                await mensagem.reject(requeue=False)
                return

            job_id_ctx.set(str(dto.job_id))
            try:
                await self.roteador.entregar(dto.job_id, dto)
            except JobDesconhecidoError:
                logger.warning(
                    "job sem grafo correspondente",
                    extra={
                        "tipo_mensagem": self.modelo.nome,
                        "causa": "job_desconhecido",
                        "decisao": "reject_sem_requeue",
                    },
                )
                await mensagem.reject(requeue=False)
            except Exception:
                # Texto e traceback podem carregar artefatos ou credenciais do processador.
                logger.error(
                    "processamento da mensagem falhou",
                    extra={
                        "tipo_mensagem": self.modelo.nome,
                        "causa": "processamento_falhou",
                        "decisao": "nack_com_requeue",
                    },
                )
                await mensagem.nack(requeue=True)
            else:
                await mensagem.ack()
        finally:
            job_id_ctx.reset(token)
            if tarefa is not None:
                self._ativos.discard(tarefa)
