"""Loop consumidor de executar-codigo.

Lê o código pela referência do comando, prepara o payload, o executa no container efêmero
(`app.execucao.container`), classifica o desfecho (`app.execucao.coleta`), o julga contra o
baseline do worker e o orçamento do comando, quando ele o traz (`app.execucao.veredito`), **grava**
a linha em `resultados_simulacao` e **só depois** publica `simulacao-concluida` (T-067): um evento
que referencia uma linha inexistente é pior que um evento perdido. O `ack` vem por último.

Com meta de venda, o worker reapura o baseline na meta por conta própria antes de subir o
container (`app.execucao.bases`, T-270): é esse total que confere o baseline devolvido. Uma meta
que não se aplica às vendas do período leva o comando à DLQ sem executar, porque a falha não é
da regra.

Se o comando já tem resultado gravado (voltou depois de a publicação falhar, ou de uma queda antes
do `ack`), o container não sobe de novo: o evento da linha existente é republicado. O mesmo
comando é o mesmo código, na mesma meta e com o mesmo propósito.
"""

import asyncio
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from decimal import Decimal

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
from app.core.metrics.global_metrics import (
    duracao_do_baseline_na_meta,
    execucoes_com_cobertura_incompleta,
    execucoes_julgadas,
    execucoes_na_meta,
)
from app.db.engine import get_sessionmaker
from app.execucao.baseline import carregar_baselines
from app.execucao.bases import ReapuracaoNaMetaError, carregar_bases
from app.execucao.coleta import classificar
from app.execucao.container import SaidaBruta, SandboxInfraError, executar_no_sandbox
from app.execucao.preparo import ExecucaoPreparada, PayloadContainer, preparar_execucao
from app.execucao.registro import (
    DiagnosticoForaDoContratoError,
    evento_de,
    linha_do_julgamento,
)
from app.execucao.schema import Problema
from app.execucao.veredito import (
    Julgamento,
    desfecho_da_execucao,
    julgamento_de_infra,
    julgar,
)
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


def _problemas_no_log(problemas: Iterable[Problema]) -> list[str]:
    """Cada problema como `<caminho>: <palavra-chave>`, sem o valor que o schema reprovou."""
    return [f"{problema['caminho']}: {problema['palavra_chave']}" for problema in problemas]


def _registrar_julgamento(julgamento: Julgamento, comando: ExecutarCodigo) -> None:
    """Só a classe, o motivo, o veredito, onde o schema falhou e o que reprovou a cobertura:
    nunca stdout, stderr nem a mensagem de erro da regra, que são texto não confiável, e nem os
    números do resultado, que são artefato e vivem no Postgres (T-067). Da meta, só se houve
    meta, nunca o valor (T-270).

    Toda execução julgada é contada pelo desfecho, e a cobertura incompleta também, uma vez por
    execução julgada (T-241). Um sucesso de job sem orçamento sai com veredito nulo e desfecho
    `sem_orcamento` (T-281). A execução na meta conta também por propósito (T-270)."""
    desfecho_da_metrica = desfecho_da_execucao(julgamento)
    com_meta_venda = comando.meta_venda is not None
    extra: dict[str, object] = {
        "classe": julgamento.classe,
        "motivo": julgamento.motivo,
        "veredito": julgamento.veredito,
        "desfecho": desfecho_da_metrica,
        "com_meta_venda": com_meta_venda,
        "proposito": comando.proposito,
    }
    desfecho = julgamento.desfecho
    if desfecho is not None and desfecho.saida is not None:
        extra["codigo_saida"] = desfecho.saida.codigo_saida
    if desfecho is not None and desfecho.problemas:
        extra["problemas"] = _problemas_no_log(desfecho.problemas)
    if julgamento.cobertura is not None:
        # As ausentes vêm do comando. As fora da regra vêm do código gerado: o schema do resultado
        # as restringe ao padrão de elemento_ref, mas não em tamanho nem em quantidade, então o
        # log leva só quantas são, e a lista fica no diagnóstico da linha.
        extra["elementos_ausentes"] = list(julgamento.cobertura.ausentes)
        extra["quantidade_fora_da_regra"] = len(julgamento.cobertura.fora_da_regra)
        execucoes_com_cobertura_incompleta.inc()
    execucoes_julgadas.labels(desfecho=desfecho_da_metrica).inc()
    if com_meta_venda:
        execucoes_na_meta.labels(proposito=comando.proposito, desfecho=desfecho_da_metrica).inc()
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


async def _baseline_na_meta(execucao: ExecucaoPreparada) -> Decimal | None:
    """O baseline na meta reapurado pelo worker, ou None numa execução sobre as vendas
    históricas, que é conferida contra o congelado.

    Roda numa thread, como o container, para o loop seguir atendendo o heartbeat do RabbitMQ. A
    duração é medida também quando a reapuração falha; um cancelamento (o desligamento do worker)
    não é falha e não é medido.
    """
    meta_venda = execucao.payload.meta_venda
    if meta_venda is None:
        return None
    inicio = time.monotonic()
    try:
        total = await asyncio.to_thread(
            carregar_bases().baseline_na_meta, execucao.payload.competencias, meta_venda
        )
    except Exception:
        duracao_do_baseline_na_meta.labels(resultado="falha").observe(time.monotonic() - inicio)
        raise
    duracao = time.monotonic() - inicio
    duracao_do_baseline_na_meta.labels(resultado="ok").observe(duracao)
    logger.info("baseline na meta reapurado", extra={"duracao_s": round(duracao, 3)})
    return total


async def _gravar(comando: ExecutarCodigo, julgamento: Julgamento) -> ResultadoGravado:
    """Insere a linha numa transação que **confirma antes** de esta função devolver: só depois o
    evento pode ser publicado. O diagnóstico de um `erro_codigo` vai na mesma linha, então um
    evento nunca referencia um diagnóstico que não foi confirmado."""
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
                diagnostico=linha.diagnostico,
                linhas=linha.linhas,
                meta_venda=comando.meta_venda,
                proposito=comando.proposito,
            )
    logger.info(
        "resultado gravado",
        extra={
            "resultado_id": str(gravado.id),
            "status": gravado.status,
            "com_diagnostico": linha.diagnostico is not None,
            "competencias_detalhadas": len(linha.linhas or {}),
            "linhas_detalhadas": sum(len(mes) for mes in (linha.linhas or {}).values()),
            "com_meta_venda": gravado.meta_venda is not None,
            "proposito": gravado.proposito,
        },
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
                        sessao,
                        comando.job_id,
                        comando.codigo_gerado_id,
                        meta_venda=comando.meta_venda,
                        proposito=comando.proposito,
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
                        # Nulo quando o comando não os trouxe e a cobertura não será conferida.
                        "elementos_exigidos": execucao.elementos_exigidos,
                        # Se haverá veredito, nunca o valor do orçamento.
                        "com_orcamento": execucao.orcamento is not None,
                        # Se as vendas serão escaladas, nunca o valor da meta.
                        "com_meta_venda": execucao.payload.meta_venda is not None,
                        "proposito": execucao.proposito,
                    },
                )
                baseline_na_meta = await _baseline_na_meta(execucao)
                saida = await _executar_no_container(execucao.payload)
                # Numa thread, como o container: conferir o envelope contra os schemas é CPU
                # pura e cresce com o detalhamento (perto de 1 s no período inteiro, contra 22 ms
                # do resultado sozinho), e no loop pararia o heartbeat do RabbitMQ e o `/metrics`
                # por todo esse tempo. O contexto do job acompanha a thread, então o log da
                # recusa continua correlacionado.
                desfecho = await asyncio.to_thread(
                    classificar, saida, execucao.payload, execucao.orcamento
                )
                # Aqui, no processo do worker: nem o orçamento nem os elementos exigidos entraram
                # no container.
                julgamento = julgar(
                    desfecho,
                    execucao.payload.competencias,
                    execucao.orcamento,
                    carregar_baselines(),
                    elementos_exigidos=execucao.elementos_exigidos,
                    bases=carregar_bases(),
                    baseline_na_meta=baseline_na_meta,
                )
                _registrar_julgamento(julgamento, comando)
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
            _registrar_julgamento(julgamento, comando)
            if ultima_tentativa(mensagem):
                await _registrar_esgotamento(comando, broker, julgamento)
            await repetir_erro_infra(mensagem, broker)
        except ValidationError:
            logger.error("comando ou artefato inválido; encaminhando para DLQ")
            await enviar_dlq(mensagem, broker)
        except ReapuracaoNaMetaError as erro:
            # Repetir daria o mesmo, e a regra nem rodou: não há resultado a gravar em nome dela.
            # Só a classe da falha, que é o que a exceção carrega.
            logger.error(
                "baseline na meta não reapurado; encaminhando para DLQ",
                extra={"erro": str(erro)},
            )
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
        except DiagnosticoForaDoContratoError as erro:
            # Erro do worker ao montar o diagnóstico: repetir daria o mesmo, e gravar sem ele
            # perderia o que o diagnóstico existe para guardar.
            logger.error(
                "diagnóstico fora do contrato; encaminhando para DLQ",
                extra={"problemas": _problemas_no_log(erro.problemas)},
            )
            await enviar_dlq(mensagem, broker)
        except Exception:
            logger.error("falha não recuperável no processamento; encaminhando para DLQ")
            await enviar_dlq(mensagem, broker)
        else:
            await mensagem.ack()
    finally:
        job_id_ctx.reset(token)
