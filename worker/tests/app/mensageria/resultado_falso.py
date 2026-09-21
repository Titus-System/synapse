"""O banco de resultados e a exchange trocados por fakes nos testes que só provam a fiação do
consumidor (T-067). A gravação real e a publicação real têm os seus próprios testes contra
Postgres e RabbitMQ."""

from typing import Any
from uuid import UUID, uuid4

from aio_pika import Message
from pamqp.commands import Basic

from app.repositorio.resultados import ResultadoGravado

# A sequência do que aconteceu, na ordem: "gravar", "publicar", "ack". Um teste de ordem lê
# daqui, e o autouse de `conftest.py` o zera a cada teste.
DIARIO: list[str] = []


class ExchangeFalsa:
    """Ocupa o lugar da exchange fanout: registra o que foi publicado, e como."""

    def __init__(self) -> None:
        self.publicadas: list[Message] = []
        self.chamadas: list[dict[str, Any]] = []
        self.erro: Exception | None = None
        self.confirmacao: object = Basic.Ack()

    async def publish(
        self, mensagem: Message, routing_key: str = "", *, mandatory: bool = False, **_: Any
    ) -> object:
        DIARIO.append("publicar")
        self.chamadas.append({"routing_key": routing_key, "mandatory": mandatory})
        if self.erro is not None:
            raise self.erro
        self.publicadas.append(mensagem)
        return self.confirmacao


class BancoDeResultadosFalso:
    """Ocupa o lugar de `gravar_resultado` e `buscar_resultado`."""

    def __init__(self) -> None:
        self.gravados: list[dict[str, Any]] = []
        self.retornados: list[ResultadoGravado] = []
        self.consultas: list[tuple[UUID, UUID]] = []
        self.existente: ResultadoGravado | None = None
        self.erro_gravacao: Exception | None = None
        self.erro_consulta: Exception | None = None

    async def buscar(
        self, sessao: object, job_id: UUID, codigo_gerado_id: UUID
    ) -> ResultadoGravado | None:
        self.consultas.append((job_id, codigo_gerado_id))
        if self.erro_consulta is not None:
            raise self.erro_consulta
        return self.existente

    async def gravar(self, sessao: object, **campos: Any) -> ResultadoGravado:
        DIARIO.append("gravar")
        if self.erro_gravacao is not None:
            raise self.erro_gravacao
        self.gravados.append(campos)
        gravado = ResultadoGravado(
            id=uuid4(),
            job_id=campos["job_id"],
            status=campos["status"],
            veredito=campos["veredito"],
            totais=campos["totais"],
        )
        self.retornados.append(gravado)
        return gravado
