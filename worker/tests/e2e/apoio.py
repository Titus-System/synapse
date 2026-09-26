"""Apoio dos e2e do ciclo de vida do worker: o processo real, e o RabbitMQ e o banco vistos de
fora, como um operador os veria.

O worker roda como `uvicorn app.main:create_app --factory`, o mesmo comando do container, em
subprocesso, apontado para um vhost novo do RabbitMQ (as filas do compose não são tocadas), para
o Postgres e o daemon Docker reais e para a imagem do sandbox construída pelos testes. Os testes
o tratam como caixa-preta: publicam o comando, esperam o evento, conferem banco, filas,
containers e log. Nada do worker é importado nem substituído.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import docker
import httpx
from aio_pika import ExchangeType, Message, connect
from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractQueue

from app.config import Settings, get_settings
from app.execucao.container import ROTULO_JOB
from tests.rabbitmqctl import ContagemDaFila, contagens_das_filas
from tests.semente import apagar_semente, semear_codigo

RAIZ_DO_WORKER = Path(__file__).resolve().parents[2]
FILA_COMANDO = "executar-codigo"
FILA_DLQ = "executar-codigo.dlq"
EXCHANGE = "simulacao-concluida"
FILA_API = "simulacao-concluida.api"
FILA_CODEGEN = "simulacao-concluida.codegen"
COMPETENCIAS = ["2025-11"]
ORCAMENTO_PADRAO = 485000.0


def _porta_livre() -> int:
    with socket.socket() as soquete:
        soquete.bind(("127.0.0.1", 0))
        return int(soquete.getsockname()[1])


async def esperar_ate(
    condicao: Callable[[], bool], descricao: str, prazo: float = 30.0, passo: float = 0.25
) -> None:
    """Espera `condicao()` ficar verdadeira, ou falha dizendo o que não aconteceu."""
    limite = time.monotonic() + prazo
    while time.monotonic() < limite:
        if condicao():
            return
        await asyncio.sleep(passo)
    raise AssertionError(f"não aconteceu em {prazo} s: {descricao}")


class Worker:
    """O processo do worker, com o log capturado."""

    def __init__(self, env: dict[str, str], pasta: Path, nome: str) -> None:
        self.porta = _porta_livre()
        self._env = env
        self._pasta = pasta
        self._arquivo_de_log = pasta / f"{nome}.log"
        self._processo: subprocess.Popen[bytes] | None = None

    def iniciar(self) -> None:
        # A pasta de trabalho é a do teste: o worker grava `logs/app.json` relativo a ela.
        with self._arquivo_de_log.open("wb") as log:
            self._processo = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.porta),
                ],
                cwd=self._pasta,
                env=self._env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

    @property
    def vivo(self) -> bool:
        return self._processo is not None and self._processo.poll() is None

    @property
    def codigo_de_saida(self) -> int | None:
        return None if self._processo is None else self._processo.poll()

    def sinalizar(self, sinal: signal.Signals) -> None:
        assert self._processo is not None
        self._processo.send_signal(sinal)

    def matar(self) -> None:
        if self._processo is not None and self._processo.poll() is None:
            self._processo.kill()
            self._processo.wait(timeout=30)

    async def aguardar_saida(self, prazo: float) -> int:
        assert self._processo is not None
        limite = time.monotonic() + prazo
        while time.monotonic() < limite:
            codigo = self._processo.poll()
            if codigo is not None:
                return codigo
            await asyncio.sleep(0.1)
        raise AssertionError(f"o worker não encerrou em {prazo} s\n{self.cauda()}")

    async def saude(self, prazo: float = 5.0) -> tuple[int, float]:
        """`GET /health`: o código HTTP e quanto a resposta levou."""
        inicio = time.monotonic()
        async with httpx.AsyncClient(timeout=prazo) as cliente:
            resposta = await cliente.get(f"http://127.0.0.1:{self.porta}/health")
        return resposta.status_code, time.monotonic() - inicio

    async def aguardar_pronto(self, prazo: float = 60.0) -> None:
        """Pronto é responder `/health`: o uvicorn só atende depois de a subida terminar (daemon,
        contratos, baselines, broker e consumidor)."""
        limite = time.monotonic() + prazo
        while time.monotonic() < limite:
            assert (
                self.vivo
            ), f"o worker morreu na subida (saída {self.codigo_de_saida})\n{self.cauda()}"
            try:
                codigo, _ = await self.saude(prazo=2.0)
            except httpx.HTTPError:
                await asyncio.sleep(0.25)
                continue
            if codigo == 200:
                return
        raise AssertionError(f"o worker não ficou pronto em {prazo} s\n{self.cauda()}")

    def texto_do_log(self) -> str:
        return self._arquivo_de_log.read_text(encoding="utf-8", errors="replace")

    def cauda(self, caracteres: int = 4000) -> str:
        return f"--- log do worker ---\n{self.texto_do_log()[-caracteres:]}"

    def registros(self) -> list[dict[str, Any]]:
        """As linhas de log JSON do worker (o resto é saída do uvicorn)."""
        registros: list[dict[str, Any]] = []
        for linha in self.texto_do_log().splitlines():
            if linha.startswith("{"):
                try:
                    registros.append(json.loads(linha))
                except ValueError:
                    continue
        return registros

    def mensagens(self, mensagem: str) -> list[dict[str, Any]]:
        return [r for r in self.registros() if r.get("message") == mensagem]

    def do_job(self, job_id: UUID) -> list[dict[str, Any]]:
        """Os registros emitidos durante o processamento deste job."""
        return [r for r in self.registros() if r.get("job_id") == str(job_id)]


class Corretor:
    """O RabbitMQ do vhost isolado, do lado de quem envia o comando e consome o evento: declara as
    filas que a api e o codegen declaram ao subir, e as lê."""

    def __init__(self, vhost: str, settings: Settings) -> None:
        self.vhost = vhost
        self._url = settings.model_copy(update={"RABBITMQ_VHOST": vhost}).rabbitmq_url
        self._conexao: AbstractConnection | None = None
        self._canal: AbstractChannel | None = None
        self.comando: AbstractQueue
        self.dlq: AbstractQueue
        self.api: AbstractQueue
        self.codegen: AbstractQueue

    async def abrir(self) -> None:
        self._conexao = await connect(self._url)
        canal = self._canal = await self._conexao.channel()
        exchange = await canal.declare_exchange(EXCHANGE, ExchangeType.FANOUT, durable=True)
        self.comando = await canal.declare_queue(FILA_COMANDO, durable=True)
        self.dlq = await canal.declare_queue(FILA_DLQ, durable=True)
        self.api = await canal.declare_queue(FILA_API, durable=True)
        self.codegen = await canal.declare_queue(FILA_CODEGEN, durable=True)
        await self.api.bind(exchange, routing_key="")
        await self.codegen.bind(exchange, routing_key="")

    async def fechar(self) -> None:
        if self._conexao is not None:
            await self._conexao.close()

    async def publicar(self, corpo: bytes) -> None:
        assert self._canal is not None
        await self._canal.default_exchange.publish(Message(body=corpo), routing_key=FILA_COMANDO)

    async def publicar_comando(self, semente: dict[str, Any], orcamento: float) -> None:
        await self.publicar(
            json.dumps(
                {
                    "job_id": str(semente["job_id"]),
                    "codigo_gerado_id": str(semente["id"]),
                    "competencias": COMPETENCIAS,
                    "orcamento": orcamento,
                }
            ).encode("utf-8")
        )

    async def esperar(self, fila: AbstractQueue, prazo: float = 90.0) -> Message | None:
        """A próxima mensagem da fila, confirmada, ou `None` se nada chega no prazo."""
        limite = time.monotonic() + prazo
        while time.monotonic() < limite:
            mensagem = await fila.get(fail=False, timeout=5)
            if mensagem is not None:
                await mensagem.ack()
                return mensagem  # type: ignore[return-value]
            await asyncio.sleep(0.25)
        return None

    async def evento(self, fila: AbstractQueue, prazo: float = 90.0) -> dict[str, Any]:
        mensagem = await self.esperar(fila, prazo)
        assert mensagem is not None, f"nenhum evento em {fila.name} em {prazo} s"
        corpo: dict[str, Any] = json.loads(mensagem.body)
        return corpo

    async def retirar_tudo(self, fila: AbstractQueue) -> list[Message]:
        retiradas: list[Message] = []
        while (mensagem := await fila.get(fail=False, timeout=5)) is not None:
            await mensagem.ack()
            retiradas.append(mensagem)  # type: ignore[arg-type]
        return retiradas

    def contagens(self) -> dict[str, ContagemDaFila]:
        return contagens_das_filas(self.vhost)

    async def esperar_fila(
        self, nome: str, condicao: Callable[[ContagemDaFila], bool], prazo: float = 30.0
    ) -> ContagemDaFila:
        """Espera a fila `nome` chegar a um estado, e o devolve. Falha com o último visto."""
        limite = time.monotonic() + prazo
        ultima = ContagemDaFila(-1, -1, -1)
        while time.monotonic() < limite:
            todas = await asyncio.to_thread(self.contagens)
            ultima = todas.get(nome, ultima)
            if condicao(ultima):
                return ultima
            await asyncio.sleep(0.5)
        raise AssertionError(f"{nome} não chegou ao estado esperado em {prazo} s: {ultima}")

    async def esperar_comando_concluido(self, prazo: float = 30.0) -> ContagemDaFila:
        """A fila do comando sem nada pronto nem em mãos de um consumidor sem `ack`: o worker
        terminou de fato o que recebeu."""
        return await self.esperar_fila(FILA_COMANDO, lambda c: c.vazia, prazo)


class Ambiente:
    """Tudo de um teste: o vhost, o corretor, as sementes do banco e os workers, e a limpeza."""

    def __init__(
        self,
        settings: Settings,
        corretor: Corretor,
        conexao_dono: Any,
        imagem: str,
        pasta: Path,
    ) -> None:
        self.settings = settings
        self.corretor = corretor
        self.conexao_dono = conexao_dono
        self.imagem = imagem
        self._pasta = pasta
        self._sementes: list[dict[str, Any]] = []
        self._workers: list[Worker] = []

    async def semear(
        self,
        fonte: str,
        *,
        orcamento: float = ORCAMENTO_PADRAO,
        competencias: list[str] | None = None,
    ) -> dict[str, Any]:
        semente = await semear_codigo(
            self.conexao_dono,
            fonte=fonte,
            competencias=competencias or COMPETENCIAS,
            orcamento=orcamento,
        )
        self._sementes.append(semente)
        return semente

    async def iniciar_worker(self, *, esperar_pronto: bool = True, **env: str) -> Worker:
        ambiente = {
            **os.environ,
            "PYTHONPATH": str(RAIZ_DO_WORKER),
            "RABBITMQ_VHOST": self.corretor.vhost,
            "SANDBOX_IMAGE": self.imagem,
            "LOG_LEVEL": "INFO",
            "LOG_FORMAT": "json",
            "ENVIRONMENT": "e2e",
            **env,
        }
        worker = Worker(ambiente, self._pasta, f"worker-{len(self._workers) + 1}")
        self._workers.append(worker)
        worker.iniciar()
        if esperar_pronto:
            await worker.aguardar_pronto()
        return worker

    async def linhas(self, job_id: UUID) -> list[Any]:
        return list(
            await self.conexao_dono.fetch(
                "SELECT * FROM resultados_simulacao WHERE job_id = $1 ORDER BY criado_em, id",
                job_id,
            )
        )

    def conteineres_do_job(self, job_id: UUID) -> list[str]:
        cliente = docker.DockerClient(base_url=get_settings().DOCKER_HOST)
        try:
            achados = cliente.containers.list(all=True, filters={"label": f"{ROTULO_JOB}={job_id}"})
            return [str(c.name) for c in achados]
        finally:
            cliente.close()

    async def encerrar(self) -> None:
        """Workers primeiro (nada mais escreve), depois o broker, os containers que um kill possa
        ter deixado, e por fim as linhas do banco."""
        for worker in self._workers:
            worker.matar()
        await self.corretor.fechar()
        cliente = docker.DockerClient(base_url=get_settings().DOCKER_HOST)
        try:
            for semente in self._sementes:
                for container in cliente.containers.list(
                    all=True, filters={"label": f"{ROTULO_JOB}={semente['job_id']}"}
                ):
                    container.remove(force=True)
        finally:
            cliente.close()
        for semente in self._sementes:
            await apagar_semente(self.conexao_dono, semente)
