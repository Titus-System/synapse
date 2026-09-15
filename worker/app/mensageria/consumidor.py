"""Loop consumidor de executar-codigo.

Lê o código pela referência do comando e prepara o payload de execução. Subir o
container efêmero e executar o payload é responsabilidade de outro módulo.
"""

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from app.core.logger import get_logger, job_id_ctx
from app.db.engine import get_sessionmaker
from app.execucao.preparo import preparar_execucao
from app.mensageria.broker import ConexaoBroker
from app.mensageria.contracts import ExecutarCodigo
from app.repositorio.codigos_gerados import CodigoNaoEncontradoError, buscar_codigo

logger = get_logger("app.mensageria.consumidor")


async def consumir_fila_execucao(broker: ConexaoBroker) -> None:
    """Processa um comando de cada vez, na ordem em que chegam (`prefetch` 1)."""
    async with broker.fila.iterator() as mensagens:
        async for mensagem in mensagens:
            await _processar(mensagem)


async def _processar(mensagem: AbstractIncomingMessage) -> None:
    # requeue=False: comando tem semântica de retry própria, distinta da redelivery
    # automática do broker. Reentregar sem classificar o erro criaria um loop; a
    # política de retry por tipo de falha é decidida depois de classificar o erro.
    #
    # As duas exceções abaixo são capturadas aqui, e não deixadas propagar por
    # `consumir`, para que uma mensagem recusada não interrompa o processamento
    # das próximas.
    try:
        async with mensagem.process(requeue=False):
            comando = ExecutarCodigo.model_validate_json(mensagem.body)

            token = job_id_ctx.set(str(comando.job_id))
            try:
                logger.info(
                    "comando executar-codigo recebido",
                    extra={"codigo_gerado_id": str(comando.codigo_gerado_id)},
                )

                sessionmaker = get_sessionmaker()
                async with sessionmaker() as sessao:
                    codigo = await buscar_codigo(sessao, comando.codigo_gerado_id)

                execucao = preparar_execucao(comando, codigo)
                logger.info(
                    "execução preparada",
                    extra={
                        "codigo_gerado_id": str(execucao.payload.codigo_gerado_id),
                        "competencias": execucao.payload.competencias,
                    },
                )
            finally:
                job_id_ctx.reset(token)
    except ValidationError:
        logger.exception("comando executar-codigo inválido, descartado")
    except CodigoNaoEncontradoError as erro:
        logger.exception(
            "código gerado não encontrado para o comando",
            extra={"codigo_gerado_id": str(erro.codigo_gerado_id)},
        )
