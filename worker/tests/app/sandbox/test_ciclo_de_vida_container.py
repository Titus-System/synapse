"""O container sobe, executa e morre: o ciclo de vida da imagem do sandbox (T-033).

Conduzido pelo SDK do Docker, que é o que o worker usa (``docker`` já é dependência). O
``ContainerDoSandbox`` abaixo é um cliente de referência, **só de teste**: a receita que a
T-064 vai precisar (anexar o stdin antes de iniciar, meio-fechar o socket para o EOF,
separar o stdout do stderr, remover aconteça o que acontecer), verificada contra a imagem
real. Não é código de produção, e a T-064 não é obrigada a copiá-lo.
"""

import json
import socket
import time
import uuid
from collections.abc import Iterator
from types import TracebackType
from typing import Any

import docker
import pytest
from requests.exceptions import ConnectionError as ConexaoInterrompida
from requests.exceptions import ReadTimeout

from app.config import get_settings
from app.sandbox.envelope import SAIDA_SIGTERM, SAIDA_SUCESSO
from tests.app.sandbox.test_executor import bytes_do, payload
from tests.app.sandbox.test_harness import EXEMPLO

pytestmark = pytest.mark.docker

PREFIXO = "sbx-teste-"
SAIDA_SIGKILL = 137

REGRA_QUE_NAO_TERMINA = """
import sys
import time

def aplicar_regra(bases, apuracao_base, competencias):
    print("regra-em-execucao", file=sys.stderr, flush=True)
    time.sleep(600)
"""

REGRA_QUE_ESTOURA_A_MEMORIA = """
def aplicar_regra(bases, apuracao_base, competencias):
    bloco = bytearray(1 << 30)
    for posicao in range(0, len(bloco), 4096):
        bloco[posicao] = 1
"""


class ContainerDoSandbox:
    """Um container da imagem, conduzido como o worker fará."""

    def __init__(self, cliente: Any, imagem: str, **limites: Any) -> None:
        self.nome = f"{PREFIXO}{uuid.uuid4().hex[:10]}"
        self.container = cliente.containers.create(
            imagem,
            name=self.nome,
            stdin_open=True,
            network_mode="none",
            read_only=True,
            **limites,
        )
        # Anexar ANTES de iniciar: assim nenhum byte escrito no stdin se perde.
        self._soquete = self.container.attach_socket(params={"stdin": 1, "stream": 1})

    def __enter__(self) -> "ContainerDoSandbox":
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        rastro: TracebackType | None,
    ) -> None:
        # Remoção garantida em qualquer desfecho: sucesso, erro ou timeout.
        try:
            self._soquete.close()
        finally:
            self.container.remove(force=True)

    def iniciar(self) -> None:
        self.container.start()

    def enviar(self, dados: bytes, *, fechar: bool = True) -> None:
        self._soquete._sock.sendall(dados)
        if fechar:
            self.fechar_stdin()

    def fechar_stdin(self) -> None:
        # Meio-fecha a escrita: o container recebe EOF e o socket segue aberto para leitura.
        self._soquete._sock.shutdown(socket.SHUT_WR)

    def esperar(self, timeout: float) -> int:
        return int(self.container.wait(timeout=timeout)["StatusCode"])

    def stdout(self) -> bytes:
        return bytes(self.container.logs(stdout=True, stderr=False))

    def stderr(self) -> bytes:
        return bytes(self.container.logs(stdout=False, stderr=True))

    def estado(self) -> dict[str, Any]:
        self.container.reload()
        return dict(self.container.attrs["State"])

    def esperar_a_regra_comecar(self, limite: float = 30.0) -> None:
        """Só depois disto o container está dentro da regra, e não ainda carregando dados."""
        inicio = time.monotonic()
        while b"regra-em-execucao" not in self.stderr():
            assert time.monotonic() - inicio < limite, "a regra não começou"
            time.sleep(0.1)


@pytest.fixture(scope="module")
def cliente() -> Iterator[Any]:
    cliente = docker.DockerClient(base_url=get_settings().DOCKER_HOST)
    yield cliente
    cliente.close()


def _restantes(cliente: Any) -> list[str]:
    return [c.name for c in cliente.containers.list(all=True, filters={"name": PREFIXO})]


@pytest.fixture(autouse=True)
def nenhum_container_sobra(cliente: Any) -> Iterator[None]:
    """Cada teste termina sem deixar container: é a limpeza garantida da arquitetura (§3.4)."""
    yield
    assert _restantes(cliente) == []


def test_o_container_sobe_espera_o_payload_executa_e_e_removido(cliente: Any, imagem: str) -> None:
    with ContainerDoSandbox(cliente, imagem) as sandbox:
        sandbox.iniciar()
        # Subiu e aguarda o payload: ainda não há EOF no stdin.
        assert sandbox.estado()["Status"] == "running"

        sandbox.enviar(bytes_do(payload(EXEMPLO, ("2025-11",))))
        codigo = sandbox.esperar(60)
        terminou = sandbox.estado()
        stdout, stderr = sandbox.stdout(), sandbox.stderr()

    assert codigo == SAIDA_SUCESSO and terminou["Status"] == "exited"
    envelope = json.loads(stdout)
    assert envelope["status"] == "sucesso"
    assert envelope["resultado"]["totais"]["baseline"] == 508382.32
    assert stderr == b""


def test_container_so_executa_quando_o_stdin_fecha(cliente: Any, imagem: str) -> None:
    """O payload termina no EOF. Sem fechar o stdin o container espera para sempre, e é
    a T-064 quem precisa fechá-lo."""
    with ContainerDoSandbox(cliente, imagem) as sandbox:
        sandbox.iniciar()
        sandbox.enviar(bytes_do(payload(EXEMPLO, ("2025-11",))), fechar=False)
        time.sleep(3)

        esperando = (sandbox.estado()["Status"], sandbox.stdout())
        sandbox.fechar_stdin()
        codigo = sandbox.esperar(60)
        stdout = sandbox.stdout()

    assert esperando == ("running", b"")
    assert codigo == SAIDA_SUCESSO and json.loads(stdout)["status"] == "sucesso"


def test_container_que_nao_termina_e_morto_por_timeout_e_removido(
    cliente: Any, imagem: str
) -> None:
    with ContainerDoSandbox(cliente, imagem) as sandbox:
        sandbox.iniciar()
        sandbox.enviar(bytes_do(payload(REGRA_QUE_NAO_TERMINA, ("2025-11",))))
        sandbox.esperar_a_regra_comecar()

        # O timeout de parede é do worker; esgotá-lo não mata o container por si só.
        with pytest.raises((ReadTimeout, ConexaoInterrompida)):
            sandbox.esperar(3)
        ainda_rodando = sandbox.estado()["Status"]

        sandbox.container.kill()
        codigo = sandbox.esperar(30)
        stdout = sandbox.stdout()

    assert ainda_rodando == "running"
    assert codigo == SAIDA_SIGKILL
    assert stdout == b"", "morto pelo kill, o container não escreve envelope"


def test_docker_stop_de_container_que_nao_termina_atende_o_sigterm(
    cliente: Any, imagem: str
) -> None:
    """O executor é o PID 1 e o kernel não entrega a um PID 1 um sinal sem handler. Sem o
    handler de SIGTERM, ``stop`` levava o prazo inteiro e terminava em 137."""
    with ContainerDoSandbox(cliente, imagem) as sandbox:
        sandbox.iniciar()
        sandbox.enviar(bytes_do(payload(REGRA_QUE_NAO_TERMINA, ("2025-11",))))
        sandbox.esperar_a_regra_comecar()

        inicio = time.monotonic()
        sandbox.container.stop(timeout=10)
        demorou = time.monotonic() - inicio
        codigo = sandbox.esperar(30)

    assert codigo == SAIDA_SIGTERM
    assert demorou < 5, f"stop levou {demorou:.1f}s: o SIGTERM foi ignorado até o prazo"


def test_container_que_estoura_a_memoria_e_morto_sem_envelope(cliente: Any, imagem: str) -> None:
    if not cliente.info().get("MemoryLimit"):
        pytest.skip("o daemon não aplica limite de memória")

    with ContainerDoSandbox(cliente, imagem, mem_limit="128m", memswap_limit="128m") as sandbox:
        sandbox.iniciar()
        sandbox.enviar(bytes_do(payload(REGRA_QUE_ESTOURA_A_MEMORIA, ("2025-11",))))
        codigo = sandbox.esperar(60)
        estado = sandbox.estado()
        stdout = sandbox.stdout()

    # 137 sem envelope, e é o OOMKilled que distingue de um kill por timeout.
    assert codigo == SAIDA_SIGKILL and estado["OOMKilled"] is True
    assert stdout == b""
