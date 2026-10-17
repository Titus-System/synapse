import asyncio
from contextlib import suppress
from typing import Literal
from uuid import UUID

import simplejson
from aio_pika.abc import AbstractIncomingMessage

from app.contratos.mensagens import (
    JobEncerrado,
    ParametrosConfirmados,
    RegraSubmetida,
    SimulacaoConcluida,
)
from app.contratos.validacao import validar
from app.core.logger import get_logger, job_id_ctx
from app.core.metrics.global_metrics import parametros_confirmados
from app.falhas import FalhaDoJobError
from app.mensageria.roteamento import (
    ContextoAusenteError,
    JobDesconhecidoError,
    JobEncerradoError,
    RetomadaIndisponivelError,
    RoteadorGrafo,
)

logger = get_logger("app.mensageria.consumers")

type CausaDescarte = Literal[
    "contrato_invalido", "contexto_ausente", "job_desconhecido", "job_encerrado", "falha_do_job"
]


class Consumer:
    def __init__(
        self,
        modelo: type[RegraSubmetida | ParametrosConfirmados | SimulacaoConcluida | JobEncerrado],
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
        regra_id: UUID | None = None
        try:
            try:
                payload = simplejson.loads(mensagem.body, use_decimal=True)
                if isinstance(payload, dict) and isinstance(payload.get("job_id"), str):
                    with suppress(ValueError):
                        job_id_ctx.set(str(UUID(payload["job_id"])))
                if isinstance(payload, dict) and isinstance(payload.get("regra_id"), str):
                    with suppress(ValueError):
                        regra_id = UUID(payload["regra_id"])
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
                        **self._descarte("contrato_invalido", regra_id),
                        "decisao": "reject_sem_requeue",
                    },
                )
                await mensagem.reject(requeue=False)
                return

            job_id_ctx.set(str(dto.job_id))
            try:
                await self.roteador.entregar(dto.job_id, dto)
            except ContextoAusenteError:
                logger.warning(
                    "confirmação sem contexto descartada",
                    extra={
                        **self._descarte("contexto_ausente", regra_id),
                        "decisao": "reject_sem_requeue",
                    },
                )
                await mensagem.reject(requeue=False)
            except JobDesconhecidoError:
                logger.warning(
                    "job sem grafo correspondente",
                    extra={
                        **self._descarte("job_desconhecido", regra_id),
                        "decisao": "reject_sem_requeue",
                    },
                )
                await mensagem.reject(requeue=False)
            except JobEncerradoError:
                # Mensagem antiga de um job que a `api` encerrou: confirmar é o que a tira da
                # fila sem recomeçar a geração, reenviar execução ou duplicar auditoria.
                logger.info(
                    "mensagem de job encerrado descartada",
                    extra={
                        **self._descarte("job_encerrado", regra_id),
                        "decisao": "ack_sem_processar",
                    },
                )
                await mensagem.ack()
            except RetomadaIndisponivelError:
                # O grafo ainda não gravou a pausa. Rejeitar aqui perderia o resultado de uma
                # simulação que já aconteceu; a reentrega chega depois do checkpoint.
                logger.warning(
                    "grafo do job ainda não está pausado",
                    extra={
                        "tipo_mensagem": self.nome,
                        "causa": "retomada_indisponivel",
                        "decisao": "nack_com_requeue",
                    },
                )
                await mensagem.nack(requeue=True)
            except FalhaDoJobError as falha:
                # Falha permanente: reentregar não a corrige, então a rejeição não usa
                # requeue. O roteador já avisou a `api` por `etapa-alterada`, e o job termina
                # em erro. A etapa entra no log; a mensagem da exceção nunca, porque pode
                # carregar regra, prompt, resposta ou código.
                logger.warning(
                    "processamento do job falhou de forma permanente",
                    extra={
                        **self._descarte("falha_do_job", regra_id),
                        "etapa": falha.etapa,
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

    def _descarte(self, causa: CausaDescarte, regra_id: UUID | None) -> dict[str, str]:
        extra = {"tipo_mensagem": self.nome, "causa": causa}
        if self.modelo is ParametrosConfirmados:
            parametros_confirmados.labels(resultado="descartada").inc()
            extra["resultado"] = "descartada"
            if regra_id is not None:
                extra["regra_id"] = str(regra_id)
        return extra
