"""Loop consumidor de executar-codigo.

Lê o código pela referência do comando, prepara o payload, o executa no container efêmero
(`app.execucao.container`) e classifica o desfecho (`app.execucao.coleta`). A classe vai ao
log e o comando recebe `ack`: julgar o resultado contra o orçamento (T-066), gravá-lo e
publicá-lo (T-067) são as próximas etapas do fluxo, e até lá o desfecho não sai do worker.
"""

import asyncio

from aio_pika.abc import AbstractIncomingMessage
from asyncpg import (  # type: ignore[import-untyped]
    CannotConnectNowError,
    PostgresConnectionError,
    TooManyConnectionsError,
)
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.logger import get_logger, job_id_ctx
from app.db.engine import get_sessionmaker
from app.execucao.coleta import DesfechoClassificado, classificar, classificar_falha_de_infra
from app.execucao.container import SandboxInfraError, executar_no_sandbox
from app.execucao.preparo import preparar_execucao
from app.mensageria.broker import ConexaoBroker
from app.mensageria.contracts import ExecutarCodigo
from app.mensageria.retry import enviar_dlq, repetir_erro_infra
from app.repositorio.codigos_gerados import CodigoNaoEncontradoError, buscar_codigo

logger = get_logger("app.mensageria.consumidor")


class _ConsultaInfraError(Exception):
    """Falha de acesso ao banco que permite repetir o comando."""


async def consumir_fila_execucao(broker: ConexaoBroker) -> None:
    """Processa um comando de cada vez, na ordem em que chegam (`prefetch` 1)."""
    async with broker.fila.iterator() as mensagens:
        async for mensagem in mensagens:
            await _processar(mensagem, broker)


def _registrar_desfecho(desfecho: DesfechoClassificado) -> None:
    """Só a classe, o motivo e onde o schema falhou: nunca stdout, stderr nem a mensagem de erro
    da regra, que são texto não confiável e não vão para log."""
    extra: dict[str, object] = {"classe": desfecho.classe, "motivo": desfecho.motivo}
    if desfecho.saida is not None:
        extra["codigo_saida"] = desfecho.saida.codigo_saida
    if desfecho.problemas:
        extra["problemas"] = list(desfecho.problemas)
    registrar = logger.warning if desfecho.classe == "erro_infra" else logger.info
    registrar("execução classificada", extra=extra)


async def _processar(mensagem: AbstractIncomingMessage, broker: ConexaoBroker) -> None:
    token = job_id_ctx.set(None)
    try:
        try:
            comando = ExecutarCodigo.model_validate_json(mensagem.body)
            job_id_ctx.set(str(comando.job_id))
            logger.info(
                "comando executar-codigo recebido",
                extra={"codigo_gerado_id": str(comando.codigo_gerado_id)},
            )
            try:
                sessionmaker = get_sessionmaker()
                async with sessionmaker() as sessao:
                    codigo = await buscar_codigo(sessao, comando.codigo_gerado_id)
            except (
                OSError,
                TimeoutError,
                PoolTimeoutError,
                OperationalError,
                PostgresConnectionError,
                CannotConnectNowError,
                TooManyConnectionsError,
            ) as erro:
                raise _ConsultaInfraError from erro
            except DBAPIError as erro:
                if not erro.connection_invalidated:
                    raise
                raise _ConsultaInfraError from erro

            execucao = preparar_execucao(comando, codigo)
            logger.info(
                "execução preparada",
                extra={
                    "codigo_gerado_id": str(execucao.payload.codigo_gerado_id),
                    "competencias": execucao.payload.competencias,
                },
            )
            # O container é síncrono e leva até o prazo de 60 s: numa thread, o loop segue
            # atendendo o heartbeat do RabbitMQ.
            saida = await asyncio.to_thread(executar_no_sandbox, execucao.payload)
            desfecho = classificar(saida, execucao.payload, execucao.orcamento)
            _registrar_desfecho(desfecho)
        except _ConsultaInfraError:
            logger.warning("falha de infraestrutura ao consultar código gerado")
            await repetir_erro_infra(mensagem, broker)
        except SandboxInfraError:
            _registrar_desfecho(classificar_falha_de_infra())
            await repetir_erro_infra(mensagem, broker)
        except ValidationError:
            logger.error("comando ou artefato inválido; encaminhando para DLQ")
            await enviar_dlq(mensagem, broker)
        except CodigoNaoEncontradoError as erro:
            logger.error(
                "código gerado não encontrado; encaminhando para DLQ",
                extra={"codigo_gerado_id": str(erro.codigo_gerado_id)},
            )
            await enviar_dlq(mensagem, broker)
        except Exception:
            logger.error("falha não recuperável no processamento; encaminhando para DLQ")
            await enviar_dlq(mensagem, broker)
        else:
            await mensagem.ack()
    finally:
        job_id_ctx.reset(token)
