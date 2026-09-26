"""Loop consumidor de executar-codigo.

Lê o código pela referência do comando, prepara o payload, o executa no container efêmero
(`app.execucao.container`), classifica o desfecho (`app.execucao.coleta`), o julga contra o
baseline congelado e o orçamento do comando (`app.execucao.veredito`), **grava** a linha em
`resultados_simulacao` e **só depois** publica `simulacao-concluida` (T-067): um evento que
referencia uma linha inexistente é pior que um evento perdido. O `ack` vem por último.

Se o comando já tem resultado gravado (voltou depois de a publicação falhar, ou de uma queda antes
do `ack`), o container não sobe de novo: o evento da linha existente é republicado.
"""

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress

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
from app.execucao.baseline import carregar_baselines
from app.execucao.coleta import classificar
from app.execucao.container import SaidaBruta, SandboxInfraError, executar_no_sandbox
from app.execucao.preparo import PayloadContainer, preparar_execucao
from app.execucao.registro import evento_de, linha_do_julgamento
from app.execucao.veredito import Julgamento, julgamento_de_infra, julgar
from app.mensageria.broker import ConexaoBroker
from app.mensageria.contracts import ExecutarCodigo
from app.mensageria.publicador import PublicacaoError, publicar_simulacao_concluida
from app.mensageria.retry import enviar_dlq, repetir_erro_infra, ultima_tentativa
from app.repositorio.codigos_gerados import CodigoNaoEncontradoError, buscar_codigo
from app.repositorio.resultados import ResultadoGravado, buscar_resultado, gravar_resultado

logger = get_logger("app.mensageria.consumidor")


class _InfraBancoError(Exception):
    """Falha de acesso ao banco que permite repetir o comando."""


class _CodigoDeOutroJobError(Exception):
    """O `job_id` do comando não é o do job que gerou o código: o par é incoerente."""


@contextmanager
def _falhas_de_banco() -> Iterator[None]:
    """Converte as falhas transitórias de acesso ao banco em `_InfraBancoError`, o que o retry da
    DEC-091 repete. Qualquer outra (integridade, permissão, SQL) segue como veio e vai à DLQ."""
    try:
        yield
    except (
        OSError,
        TimeoutError,
        PoolTimeoutError,
        OperationalError,
        PostgresConnectionError,
        CannotConnectNowError,
        TooManyConnectionsError,
    ) as erro:
        raise _InfraBancoError from erro
    except DBAPIError as erro:
        if not erro.connection_invalidated:
            raise
        raise _InfraBancoError from erro


async def consumir_fila_execucao(broker: ConexaoBroker) -> None:
    """Processa um comando de cada vez, na ordem em que chegam (`prefetch` 1)."""
    async with broker.fila.iterator() as mensagens:
        async for mensagem in mensagens:
            await _processar(mensagem, broker)


def _registrar_julgamento(julgamento: Julgamento) -> None:
    """Só a classe, o motivo, o veredito e onde o schema falhou: nunca stdout, stderr nem a
    mensagem de erro da regra, que são texto não confiável, e nem os números do resultado, que
    são artefato e vivem no Postgres (T-067)."""
    extra: dict[str, object] = {
        "classe": julgamento.classe,
        "motivo": julgamento.motivo,
        "veredito": julgamento.veredito,
    }
    desfecho = julgamento.desfecho
    if desfecho is not None and desfecho.saida is not None:
        extra["codigo_saida"] = desfecho.saida.codigo_saida
    if desfecho is not None and desfecho.problemas:
        extra["problemas"] = list(desfecho.problemas)
    registrar = logger.warning if julgamento.classe == "erro_infra" else logger.info
    registrar("execução julgada", extra=extra)


async def _executar_no_container(payload: PayloadContainer) -> SaidaBruta:
    """Executa o container numa thread, e o encerramento do worker o interrompe.

    O container é síncrono e leva até o prazo de 60 s: numa thread, o loop segue atendendo o
    heartbeat do RabbitMQ. Uma thread não se cancela, então, se esta tarefa for cancelada (o
    desligamento do worker), o pedido de cancelamento vai à thread, que mata e remove o
    container, e só depois o cancelamento segue. Sem isso o processo sairia antes de a thread
    limpar, e o container ficaria rodando sem quem lhe imponha o prazo.

    O comando não é confirmado nem rejeitado: o broker o devolve quando a conexão fecha.
    """
    cancelar = threading.Event()
    execucao = asyncio.ensure_future(
        asyncio.to_thread(executar_no_sandbox, payload, cancelar=cancelar)
    )
    try:
        return await asyncio.shield(execucao)
    except asyncio.CancelledError:
        cancelar.set()
        # Nada aqui pode trocar o cancelamento por outra exceção: o worker está saindo.
        with suppress(Exception):
            await execucao
        raise


async def _gravar(comando: ExecutarCodigo, julgamento: Julgamento) -> ResultadoGravado:
    """Insere a linha numa transação que **confirma antes** de esta função devolver: só depois o
    evento pode ser publicado."""
    linha = linha_do_julgamento(julgamento)
    with _falhas_de_banco():
        async with get_sessionmaker()() as sessao, sessao.begin():
            gravado = await gravar_resultado(
                sessao,
                job_id=comando.job_id,
                codigo_gerado_id=comando.codigo_gerado_id,
                status=linha.status,
                veredito=linha.veredito,
                totais=linha.totais,
                assercoes=linha.assercoes,
                decomposicao=linha.decomposicao,
            )
    logger.info(
        "resultado gravado",
        extra={"resultado_id": str(gravado.id), "status": gravado.status},
    )
    return gravado


async def _registrar_esgotamento(
    comando: ExecutarCodigo, broker: ConexaoBroker, julgamento: Julgamento
) -> None:
    """Um `erro_infra` que esgotou as tentativas vai para a DLQ, que não muda o job: sem isto ele
    ficaria em `simulando` para sempre (DEC-094). Grava e publica antes de o comando ir para lá.

    Nada aqui pode reter o comando: se o banco ou o broker também estiverem fora, a falha é
    registrada e a DLQ segue.
    """
    try:
        gravado = await _gravar(comando, julgamento)
        await publicar_simulacao_concluida(broker, evento_de(gravado))
    except Exception:
        logger.error("erro_infra não registrado; o comando segue para a DLQ")


async def _processar(mensagem: AbstractIncomingMessage, broker: ConexaoBroker) -> None:
    token = job_id_ctx.set(None)
    comando: ExecutarCodigo
    try:
        try:
            comando = ExecutarCodigo.model_validate_json(mensagem.body)
            job_id_ctx.set(str(comando.job_id))
            logger.info(
                "comando executar-codigo recebido",
                extra={"codigo_gerado_id": str(comando.codigo_gerado_id)},
            )
            with _falhas_de_banco():
                async with get_sessionmaker()() as sessao:
                    codigo = await buscar_codigo(sessao, comando.codigo_gerado_id)
                    if codigo.job_id != comando.job_id:
                        raise _CodigoDeOutroJobError
                    existente = await buscar_resultado(
                        sessao, comando.job_id, comando.codigo_gerado_id
                    )

            if existente is not None:
                # O resultado já foi gravado: executar de novo gravaria uma segunda linha, que a
                # primeira não teria como remover (o worker só tem INSERT).
                logger.info(
                    "resultado já gravado; o evento será republicado sem executar de novo",
                    extra={"resultado_id": str(existente.id)},
                )
                await publicar_simulacao_concluida(broker, evento_de(existente))
            else:
                execucao = preparar_execucao(comando, codigo)
                logger.info(
                    "execução preparada",
                    extra={
                        "codigo_gerado_id": str(execucao.payload.codigo_gerado_id),
                        "competencias": execucao.payload.competencias,
                    },
                )
                saida = await _executar_no_container(execucao.payload)
                desfecho = classificar(saida, execucao.payload, execucao.orcamento)
                # Aqui, no processo do worker: o orçamento nunca entrou no container.
                julgamento = julgar(
                    desfecho,
                    execucao.payload.competencias,
                    execucao.orcamento,
                    carregar_baselines(),
                )
                _registrar_julgamento(julgamento)
                gravado = await _gravar(comando, julgamento)
                await publicar_simulacao_concluida(broker, evento_de(gravado))
        except _InfraBancoError:
            logger.warning("falha de infraestrutura no acesso ao banco")
            await repetir_erro_infra(mensagem, broker)
        except PublicacaoError:
            # A linha já está gravada; a próxima tentativa a encontra e só republica.
            logger.warning("falha ao publicar simulacao-concluida")
            await repetir_erro_infra(mensagem, broker)
        except SandboxInfraError:
            julgamento = julgamento_de_infra()
            _registrar_julgamento(julgamento)
            if ultima_tentativa(mensagem):
                await _registrar_esgotamento(comando, broker, julgamento)
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
        except _CodigoDeOutroJobError:
            logger.error("o código gerado é de outro job; encaminhando para DLQ")
            await enviar_dlq(mensagem, broker)
        except Exception:
            logger.error("falha não recuperável no processamento; encaminhando para DLQ")
            await enviar_dlq(mensagem, broker)
        else:
            await mensagem.ack()
    finally:
        job_id_ctx.reset(token)
