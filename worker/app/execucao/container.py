"""Execução do código gerado num container efêmero e isolado (T-064).

A T-033 define o que existe **dentro** da imagem (dados, motor, bibliotecas, usuário
não-root); aqui está **como** ela é executada: um container novo por job, sem rede, com o
sistema de arquivos somente leitura, sem capabilities, com limites de CPU, memória e PIDs,
prazo de parede com morte por SIGKILL e remoção garantida.

O módulo devolve fatos (``SaidaBruta``), não veredito: classificar a execução em
``sucesso``, ``erro_codigo``, ``assercao_violada``, timeout ou ``erro_infra`` é da T-065,
pelo mapa registrado em ``docs/t033-imagem-sandbox.md``.

As flags e os limites são constantes deste módulo, e não configuração: um ambiente que
pudesse afrouxá-los deixaria de conter o raio de dano justamente onde ele importa. Só o
nome da imagem vem do ambiente (``SANDBOX_IMAGE``).
"""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

import docker
from docker import DockerClient
from docker.errors import DockerException
from docker.models.containers import Container
from docker.types import LogConfig

from app.config import get_settings
from app.core.logger import get_logger
from app.execucao.preparo import PayloadContainer

logger = get_logger("app.execucao.container")

# Rótulos do container: é por eles que o watchdog da T-068 reconhece um órfão deixado
# por uma queda do próprio worker.
ROTULO_SANDBOX = "synapse.sandbox"
ROTULO_JOB = "synapse.job_id"
PREFIXO_NOME = "sbx-"


class SoqueteDeAnexo(Protocol):
    """O que o executor usa do socket devolvido por ``Container.attach_socket``.

    ``_sock`` é privado do SDK, e é o único caminho para meio-fechar o stdin. Declará-lo
    aqui é o que torna `sendall` e `shutdown` de fato verificados: `docker` não publica
    ``py.typed``, então tudo que vem de lá chega como ``Any`` (ver a nota no
    ``pyproject.toml``), e os tipos do SDK abaixo servem para quem lê, não para o mypy.
    """

    _sock: socket.socket

    def close(self) -> None: ...


class SandboxInfraError(RuntimeError):
    """O container não pôde ser criado, iniciado ou inspecionado.

    É falha nossa ou do daemon, nunca do código gerado: quem recebe isto classifica
    como ``erro_infra`` (T-065), que é repetível, em vez de culpar a regra.
    """


class SandboxCanceladoError(Exception):
    """A execução foi cancelada de fora (o worker está encerrando): o container em curso foi
    morto e removido, e não houve desfecho. Não é falha do código gerado nem da infraestrutura, e
    por isso não é `SandboxInfraError`: o comando não deve ser classificado nem repetido por ela.
    """


# De quanto em quanto tempo a espera olha o pedido de cancelamento. É o tempo máximo que um
# encerramento espera até o SIGKILL sair, e tem de caber no prazo do `docker stop` (10 s).
PASSO_DA_ESPERA_S = 0.5


@dataclass(frozen=True)
class Limites:
    """Os números da contenção.

    Medidos contra a imagem real com o exemplo do contrato sobre as cinco competências:
    1,2 s de execução e 90 MiB de pico (``memory.peak`` do cgroup); abaixo de 96 MiB o
    container morre por memória. Daí 256 MiB (2,8x o pico, com folga para a regra
    trabalhar sobre um dataset de 4,5 MB) e 60 s (50x a duração medida). Apertar mais
    trocaria regra legítima por timeout intermitente, que é o defeito mais caro de
    depurar deste fluxo.
    """

    timeout_s: float = 60.0
    memoria: str = "256m"
    cpus: float = 1.0
    pids: int = 64
    # Tetos de leitura da saída: o envelope tem ~2 KB e o stderr do harness é curto, mas
    # quem escreve neles é código não confiável, e o worker não pode ser derrubado por
    # memória por um despejo de gigabytes.
    teto_stdout: int = 1 << 20
    teto_stderr: int = 1 << 16
    # Depois do SIGKILL o container morre em fração de segundo; se não morrer, o daemon
    # é que está doente.
    prazo_de_morte_s: float = 30.0


LIMITES = Limites()


@dataclass(frozen=True)
class SaidaBruta:
    """O que o container produziu, sem interpretação.

    ``codigo_saida`` só é veredito do código gerado quando ``estourou_timeout`` é falso e
    ``oom_killed`` também: 137 e 143 são morte por sinal, e o envelope, quando existe,
    está em ``stdout``.
    """

    container_id: str
    codigo_saida: int
    oom_killed: bool
    estourou_timeout: bool
    stdout: bytes
    stderr: bytes
    stdout_truncado: bool
    stderr_truncado: bool
    duracao_s: float


def serializar_payload(payload: PayloadContainer) -> bytes:
    """O JSON de uma linha que vai para o stdin, conforme o contrato da T-034.

    Sem ``orcamento``: o critério que julga o número não entra onde o número é produzido
    (T-066). O executor recusa campo desconhecido ou faltante, então uma divergência
    falha alto em vez de rodar com o payload errado.
    """
    corpo = {
        "job_id": str(payload.job_id),
        "codigo_gerado_id": str(payload.codigo_gerado_id),
        "linguagem": payload.linguagem,
        "fonte": payload.fonte,
        "competencias": list(payload.competencias),
    }
    return json.dumps(corpo, ensure_ascii=False).encode("utf-8")


def opcoes_de_isolamento(nome: str, rotulos: dict[str, str], limites: Limites) -> dict[str, Any]:
    """As flags com que o container é criado. Cada uma impede uma coisa:

    - ``network_mode``/``network_disabled``: exfiltrar dado, baixar código, alcançar o
      Postgres ou o RabbitMQ;
    - ``read_only``: persistir qualquer coisa, adulterar o motor, o baseline ou a si mesmo;
    - ``ipc_mode``: escrever em ``/dev/shm``, que o Docker monta ``1777`` mesmo com
      ``--read-only``, e que seria o único diretório gravável do container;
    - ``cap_drop`` e ``no-new-privileges``: montar, mudar dono, abrir socket raw, escalar
      por binário setuid;
    - ``mem_limit`` com ``memswap_limit`` igual: consumir a memória do host (sem swap,
      quem mata é o cgroup);
    - ``nano_cpus`` e ``pids_limit``: tomar a CPU do host, fork/thread bomb;
    - ``environment`` vazio e nenhum volume: receber credencial, orçamento ou o socket do
      Docker — é o que separa o worker, que fala com o daemon, do container, que não;
    - ``log_config``: encher o disco do host pelo stdout, e garantir o driver que
      ``logs()`` sabe ler, qualquer que seja o padrão do daemon.

    O usuário não-root não aparece aqui de propósito: ele vem da imagem (T-033), e os
    testes provam que continua valendo.
    """
    return {
        "name": nome,
        "labels": rotulos,
        # Sem isto o executor não recebe o payload: ele lê o stdin até o EOF.
        "stdin_open": True,
        "network_mode": "none",
        "network_disabled": True,
        "read_only": True,
        "ipc_mode": "none",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "privileged": False,
        "mem_limit": limites.memoria,
        "memswap_limit": limites.memoria,
        "nano_cpus": int(limites.cpus * 1_000_000_000),
        "pids_limit": limites.pids,
        "environment": {},
        "volumes": {},
        "log_config": LogConfig(
            type=LogConfig.types.JSON, config={"max-size": "8m", "max-file": "1"}
        ),
    }


def executar_no_sandbox(
    payload: PayloadContainer,
    *,
    imagem: str | None = None,
    limites: Limites = LIMITES,
    cancelar: threading.Event | None = None,
) -> SaidaBruta:
    """Sobe um container efêmero, entrega o código, espera e devolve a saída bruta.

    Síncrono de ponta a ponta: quem chama de dentro do loop assíncrono entra por
    ``asyncio.to_thread``, como ``app/sandbox/daemon.py`` faz. Uma thread não se interrompe
    de fora, então o cancelamento é cooperativo: quem quiser encerrar antes do prazo (o
    desligamento do worker) marca ``cancelar``; a espera o vê em até ``PASSO_DA_ESPERA_S``, a
    remoção forçada mata o container e o remove, e a chamada levanta ``SandboxCanceladoError``.
    """
    imagem = imagem or get_settings().SANDBOX_IMAGE
    nome = f"{PREFIXO_NOME}{str(payload.job_id)[:8]}-{uuid.uuid4().hex[:8]}"
    rotulos = {ROTULO_SANDBOX: "1", ROTULO_JOB: str(payload.job_id)}

    cliente = _abrir_cliente()
    try:
        opcoes = opcoes_de_isolamento(nome, rotulos, limites)
        with container_efemero(cliente, imagem, opcoes) as (container, soquete):
            saida = conduzir(container, soquete, serializar_payload(payload), limites, cancelar)
    finally:
        cliente.close()

    logger.info(
        "execução no sandbox concluída",
        extra={
            "container": saida.container_id[:12],
            "codigo_saida": saida.codigo_saida,
            "oom_killed": saida.oom_killed,
            "estourou_timeout": saida.estourou_timeout,
            "duracao_s": round(saida.duracao_s, 3),
            "bytes_stdout": len(saida.stdout),
            "bytes_stderr": len(saida.stderr),
        },
    )
    return saida


@contextmanager
def container_efemero(
    cliente: DockerClient, imagem: str, opcoes: dict[str, Any]
) -> Iterator[tuple[Container, SoqueteDeAnexo]]:
    """Cria o container e o remove no fim, aconteça o que acontecer.

    O socket é anexado **antes** de o container iniciar: anexar depois perderia os bytes
    escritos enquanto o executor já lia o stdin.
    """
    try:
        container = cliente.containers.create(imagem, **opcoes)
    except DockerException as erro:
        raise SandboxInfraError(f"não foi possível criar o container de {imagem}") from erro

    soquete = None
    try:
        soquete = container.attach_socket(params={"stdin": 1, "stream": 1})
        yield container, soquete
    finally:
        if soquete is not None:
            try:
                soquete.close()
            except OSError:
                logger.warning("o socket do sandbox já estava fechado")
        try:
            container.remove(force=True)
        except DockerException:
            # Não mascara o desfecho da execução: fica o log, e o órfão é do watchdog (T-068).
            logger.exception("falha ao remover o container do sandbox")


def conduzir(
    container: Container,
    soquete: SoqueteDeAnexo,
    payload: bytes,
    limites: Limites,
    cancelar: threading.Event | None = None,
) -> SaidaBruta:
    """Inicia, entrega o payload, espera o prazo e coleta. Não remove: quem remove é
    ``container_efemero``."""
    inicio = time.monotonic()
    try:
        container.start()
    except DockerException as erro:
        raise SandboxInfraError("não foi possível iniciar o container do sandbox") from erro

    _entregar(soquete, payload)
    # Cancelado, nada é lido nem classificado: a exceção sobe, e o `finally` de
    # ``container_efemero`` mata (SIGKILL) e remove numa chamada só, com ``remove(force=True)``.
    estourou_timeout = not _esperar(container, limites.timeout_s, inicio, cancelar)
    if estourou_timeout:
        _matar(container, limites)
    duracao = time.monotonic() - inicio

    codigo_saida, oom_killed = _desfecho(container)
    stdout, stdout_truncado = _ler_log(container, limites.teto_stdout, stdout=True)
    stderr, stderr_truncado = _ler_log(container, limites.teto_stderr, stdout=False)

    return SaidaBruta(
        container_id=str(container.id),
        codigo_saida=codigo_saida,
        oom_killed=oom_killed,
        estourou_timeout=estourou_timeout,
        stdout=stdout,
        stderr=stderr,
        stdout_truncado=stdout_truncado,
        stderr_truncado=stderr_truncado,
        duracao_s=duracao,
    )


def _abrir_cliente() -> DockerClient:
    settings = get_settings()
    try:
        return docker.DockerClient(base_url=settings.DOCKER_HOST)
    except DockerException as erro:
        raise SandboxInfraError(f"sem acesso ao daemon em {settings.DOCKER_HOST}") from erro


def _entregar(soquete: SoqueteDeAnexo, payload: bytes) -> None:
    """Escreve o payload e fecha **só a escrita** do socket.

    O EOF é o que faz o executor começar: sem ele o ``read()`` do stdin bloqueia e o
    container espera para sempre. ``_sock`` é privado, mas é o único caminho do SDK para
    meio-fechar; o teste de EOF é o que avisa se isso mudar.
    """
    try:
        bruto = soquete._sock
        bruto.sendall(payload)
        bruto.shutdown(socket.SHUT_WR)
    except OSError:
        # O container pode ter morrido antes de ler tudo. O desfecho vem do código de
        # saída e dos logs; falhar aqui atribuiria à infraestrutura o que pode ser a regra.
        logger.warning("o sandbox não recebeu o payload inteiro")


def _esperar(
    container: Container,
    timeout_s: float,
    inicio: float,
    cancelar: threading.Event | None = None,
) -> bool:
    """Espera o container terminar dentro do prazo. Falso quando o prazo estourou;
    ``SandboxCanceladoError`` quando ``cancelar`` foi marcado antes.

    As exceções do cliente HTTP do SDK descendem de ``OSError``, então não é preciso
    importar ``requests`` para capturá-las; e quem decide se houve timeout é o relógio
    monotônico, não o tipo da exceção. Com ``cancelar``, a espera é em passos curtos, e o
    timeout de leitura de cada passo é o caminho normal, e não um erro.
    """
    restante = timeout_s
    while restante > 0:
        if cancelar is not None and cancelar.is_set():
            raise SandboxCanceladoError
        espera = restante if cancelar is None else min(restante, PASSO_DA_ESPERA_S)
        tentativa = time.monotonic()
        try:
            container.wait(timeout=espera)
            return True
        except OSError:
            # Um erro de conexão volta na hora, e sem esta pausa o laço giraria em falso
            # consumindo CPU até o fim do prazo. O timeout de leitura já gastou o tempo.
            if time.monotonic() - tentativa < 0.1:
                time.sleep(min(0.2, max(restante - 0.1, 0)))
        restante = timeout_s - (time.monotonic() - inicio)
    return False


def _matar(container: Container, limites: Limites) -> None:
    """SIGKILL: o prazo não pede cooperação ao código gerado, que pode ignorar SIGTERM."""
    try:
        container.kill()
    except DockerException:
        # Terminou sozinho entre o fim do prazo e o kill; nada a fazer.
        logger.info("o container já havia terminado quando o prazo estourou")

    inicio = time.monotonic()
    if not _esperar(container, limites.prazo_de_morte_s, inicio):
        raise SandboxInfraError("o container do sandbox não morreu depois do SIGKILL")


def _desfecho(container: Container) -> tuple[int, bool]:
    try:
        container.reload()
        estado = container.attrs["State"]
        return int(estado["ExitCode"]), bool(estado["OOMKilled"])
    except (DockerException, KeyError, TypeError, ValueError) as erro:
        raise SandboxInfraError("não foi possível inspecionar o container do sandbox") from erro


def _ler_log(container: Container, teto: int, *, stdout: bool) -> tuple[bytes, bool]:
    """Lê em fluxo e para no teto, em vez de trazer para a memória tudo que o container
    escreveu. O cliente é descartado logo depois, então a conexão interrompida no meio do
    fluxo não volta suja para o pool."""
    partes: list[bytes] = []
    lidos = 0
    try:
        fluxo = container.logs(stdout=stdout, stderr=not stdout, stream=True, follow=False)
    except DockerException as erro:
        raise SandboxInfraError("não foi possível ler a saída do container") from erro
    try:
        for pedaco in fluxo:
            partes.append(bytes(pedaco))
            lidos += len(pedaco)
            if lidos > teto:
                break
    except DockerException as erro:
        raise SandboxInfraError("não foi possível ler a saída do container") from erro
    finally:
        # Interromper a leitura no teto deixaria a conexão do fluxo pendurada.
        fechar = getattr(fluxo, "close", None)
        if callable(fechar):
            fechar()
    return b"".join(partes)[:teto], lidos > teto
