from dataclasses import dataclass, field

from aio_pika import ExchangeType, connect_robust
from aio_pika.abc import AbstractChannel, AbstractQueue, AbstractRobustConnection

from app.config import Settings
from app.contratos.mensagens import ParametrosConfirmados, RegraSubmetida, SimulacaoConcluida
from app.core.logger import get_logger
from app.mensageria.consumers import Consumer
from app.mensageria.producers import Producers
from app.mensageria.roteamento import RoteadorGrafo

logger = get_logger("app.mensageria.broker")
FILAS_SIMPLES = (
    "regra-submetida",
    "parametros-confirmados",
    "executar-codigo",
    "etapa-alterada",
    "no-concluido",
)
EXCHANGE_SIMULACAO = "simulacao-concluida"
FILA_SIMULACAO = "simulacao-concluida.codegen"


async def declarar_topologia(canal: AbstractChannel) -> dict[str, AbstractQueue]:
    filas = {nome: await canal.declare_queue(nome, durable=True) for nome in FILAS_SIMPLES}
    exchange = await canal.declare_exchange(EXCHANGE_SIMULACAO, ExchangeType.FANOUT, durable=True)
    fila = await canal.declare_queue(FILA_SIMULACAO, durable=True)
    await fila.bind(exchange, routing_key="")
    filas[FILA_SIMULACAO] = fila
    return filas


@dataclass
class ConexaoBroker:
    conexao: AbstractRobustConnection
    canal: AbstractChannel
    filas: dict[str, AbstractQueue]
    producers: Producers
    consumidores: list[tuple[AbstractQueue, str, Consumer]] = field(default_factory=list)

    async def iniciar_consumers(self, roteador: RoteadorGrafo) -> None:
        if self.consumidores:
            raise RuntimeError("Consumers já iniciados")
        for modelo, nome, nome_fila in (
            (RegraSubmetida, "regra-submetida", "regra-submetida"),
            (ParametrosConfirmados, "parametros-confirmados", "parametros-confirmados"),
            (SimulacaoConcluida, EXCHANGE_SIMULACAO, FILA_SIMULACAO),
        ):
            consumer = Consumer(modelo, nome, roteador)
            fila = self.filas[nome_fila]
            tag = await fila.consume(consumer.receber, no_ack=False)
            self.consumidores.append((fila, tag, consumer))

    async def fechar(self) -> None:
        try:
            for fila, tag, _ in self.consumidores:
                await fila.cancel(tag)
            for _, _, consumer in self.consumidores:
                await consumer.aguardar()
        finally:
            await self.conexao.close()


async def conectar(configuracoes: Settings) -> ConexaoBroker:
    conexao = await connect_robust(configuracoes.rabbitmq_url)
    try:
        canal = await conexao.channel(publisher_confirms=True, on_return_raises=True)
        await canal.set_qos(prefetch_count=configuracoes.RABBITMQ_PREFETCH)
        filas = await declarar_topologia(canal)
        logger.info("topologia RabbitMQ declarada")
        return ConexaoBroker(conexao, canal, filas, Producers(canal))
    except BaseException:
        await conexao.close()
        raise
