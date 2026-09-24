import asyncio
from contextlib import suppress
from uuid import UUID

import simplejson
from aio_pika.abc import AbstractIncomingMessage

from app.codigo_gerado import CodigoInvalidoError
from app.contratos.mensagens import ParametrosConfirmados, RegraSubmetida, SimulacaoConcluida
from app.contratos.validacao import validar
from app.core.logger import get_logger, job_id_ctx
from app.mensageria.roteamento import JobDesconhecidoError, RoteadorGrafo
from app.repositorio.regras import RegraInvalidaError

logger = get_logger("app.mensageria.consumers")


class Consumer:
    def __init__(
        self,
        modelo: type[RegraSubmetida | ParametrosConfirmados | SimulacaoConcluida],
        nome: str,
        roteador: RoteadorGrafo,
    ) -> None:
        self.modelo = modelo
        self.nome = nome
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
                validar(self.nome, payload)
                # O schema já verificou os tipos. Decimal como texto intermediário evita
                # a conversão para float no parser JSON do Pydantic, mantendo strict=True.
                dto = self.modelo.model_validate_json(
                    simplejson.dumps(payload, use_decimal=False, default=str)
                )
            except ValueError:
                logger.warning(
                    "mensagem inválida rejeitada",
                    extra={
                        "tipo_mensagem": self.nome,
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
                        "tipo_mensagem": self.nome,
                        "causa": "job_desconhecido",
                        "decisao": "reject_sem_requeue",
                    },
                )
                await mensagem.reject(requeue=False)
            except RegraInvalidaError:
                # Regra inexistente ou inválida é uma condição permanente: reentregar não a
                # torna válida, então esta rejeição não usa requeue.
                logger.warning(
                    "regra inexistente ou inválida",
                    extra={
                        "tipo_mensagem": self.nome,
                        "causa": "regra_invalida",
                        "decisao": "reject_sem_requeue",
                    },
                )
                await mensagem.reject(requeue=False)
            except CodigoInvalidoError:
                # A redelivery resumes from the recorded reply, which stays invalid: this
                # failure is permanent, like an invalid rule.
                logger.warning(
                    "código gerado inválido",
                    extra={
                        "tipo_mensagem": self.nome,
                        "causa": "codigo_invalido",
                        "decisao": "reject_sem_requeue",
                    },
                )
                await mensagem.reject(requeue=False)
            except Exception:
                # Texto e traceback podem carregar artefatos ou credenciais do processador.
                logger.error(
                    "processamento da mensagem falhou",
                    extra={
                        "tipo_mensagem": self.nome,
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
