"""Cada restrição da execução isolada, provada contra a imagem real (T-064).

Todo teste aqui roda **código que tenta violar** a restrição, pela mesma função que o
worker usa. O código hostil relata o que observou numa linha ``SONDA`` no stderr, que a
execução já coleta, e termina levantando exceção — por isso o código de saída dessas
execuções é 3 (``erro_codigo``): o que está sob teste é o que a sonda viu, não o desfecho.

Sonda que não vê nada é sonda que mente, então as asserções são específicas: ``ENETUNREACH``
para fora e ``ECONNREFUSED`` no loopback provam que o socket funciona e a rede é que não
existe; e o teste de escrita tem um controle que roda a mesma sonda sem ``read_only`` e
exige que ela grave.
"""

import json
import re
import textwrap
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import docker
import pytest
from docker import DockerClient

from app.config import get_settings
from app.execucao.container import (
    LIMITES,
    ROTULO_SANDBOX,
    Limites,
    SaidaBruta,
    SandboxCanceladoError,
    SandboxInfraError,
    conduzir,
    container_efemero,
    executar_no_sandbox,
    opcoes_de_isolamento,
    serializar_payload,
)
from app.execucao.preparo import PayloadContainer
from tests.app.sandbox.test_harness import EXEMPLO

pytestmark = pytest.mark.docker

MARCA = "SONDA "
CURTO = Limites(timeout_s=20.0)
SAIDA_SUCESSO = 0
SAIDA_ERRO_CODIGO = 3
SAIDA_SIGKILL = 137

# O que o worker guarda e o container não pode ver. Plantado no processo do teste para
# que "não vazou" seja uma afirmação sobre um valor que existe, e não sobre o vazio.
SENTINELA = "sentinela-de-credencial-5d4c3b2a"
SEGREDO = re.compile(r"password|senha|secret|token|orcamento|rabbit|postgres", re.IGNORECASE)


def payload(fonte: str, competencias: tuple[str, ...] = ("2025-11",)) -> PayloadContainer:
    return PayloadContainer(
        job_id=uuid4(),
        codigo_gerado_id=UUID("5d4c3b2a-1f0e-4d9c-8b7a-6e5d4c3b2a19"),
        linguagem="python",
        fonte=fonte,
        competencias=list(competencias),
    )


def regra_sonda(corpo: str) -> str:
    """Uma regra que observa o ambiente, relata no stderr e falha de propósito."""
    return (
        "import errno, json, os, socket, sys\n"
        "def cod(erro):\n"
        "    return errno.errorcode.get(erro.errno, str(erro.errno))\n"
        "def aplicar_regra(bases, apuracao_base, competencias):\n"
        "    observado = {}\n"
        f"{textwrap.indent(textwrap.dedent(corpo).strip(), '    ')}\n"
        "    print('SONDA ' + json.dumps(observado), file=sys.stderr, flush=True)\n"
        "    raise RuntimeError('a sonda terminou')\n"
    )


def rodar(fonte: str, imagem: str, *, limites: Limites = CURTO) -> SaidaBruta:
    return executar_no_sandbox(payload(fonte), imagem=imagem, limites=limites)


def observar(saida: SaidaBruta) -> dict[str, Any]:
    saidas = saida.stderr.decode("utf-8").splitlines()
    linhas = [linha for linha in saidas if linha.startswith(MARCA)]
    assert len(linhas) == 1, f"a sonda não relatou: {saida.stderr[-500:]!r}"
    return dict(json.loads(linhas[0][len(MARCA) :]))


@pytest.fixture(scope="module")
def cliente() -> Iterator[DockerClient]:
    cliente = docker.DockerClient(base_url=get_settings().DOCKER_HOST)
    yield cliente
    cliente.close()


@pytest.fixture(autouse=True)
def nenhum_container_sobra(cliente: DockerClient) -> Iterator[None]:
    """Container efêmero que sobrevive ao teste é container que sobreviveria a um job."""
    yield
    restantes = cliente.containers.list(all=True, filters={"label": ROTULO_SANDBOX})
    assert [c.name for c in restantes] == []


@pytest.fixture(autouse=True)
def credencial_plantada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNAPSE_WORKER_DB_PASSWORD", SENTINELA)


# ---- o caminho feliz, para o resto dos testes significarem algo ----


def test_o_exemplo_do_contrato_executa_e_o_container_some(imagem: str) -> None:
    saida = executar_no_sandbox(payload(EXEMPLO), imagem=imagem, limites=CURTO)

    assert (saida.codigo_saida, saida.oom_killed, saida.estourou_timeout) == (0, False, False)
    envelope = json.loads(saida.stdout)
    assert envelope["status"] == "sucesso"
    assert envelope["resultado"]["totais"]["baseline"] == 508382.32
    assert saida.stderr == b"" and not saida.stdout_truncado


# ---- rede desligada ----


SONDA_DE_REDE = """
for nome, alvo in (
    ("externo", ("1.1.1.1", 53)),
    ("gateway", ("172.17.0.1", 2375)),
    ("loopback", ("127.0.0.1", 9)),
):
    try:
        socket.create_connection(alvo, timeout=3).close()
        observado[nome] = "conectou"
    except OSError as erro:
        observado[nome] = cod(erro)
try:
    socket.getaddrinfo("exemplo.invalido", 80)
    observado["dns"] = "resolveu"
except OSError:
    observado["dns"] = "falhou"
observado["interfaces"] = sorted(nome for _, nome in socket.if_nameindex())
"""


def test_codigo_que_tenta_abrir_conexao_de_rede_falha(imagem: str) -> None:
    visto = observar(rodar(regra_sonda(SONDA_DE_REDE), imagem))

    assert visto["externo"] == "ENETUNREACH", "há rota para fora do container"
    assert visto["gateway"] == "ENETUNREACH", "o container alcança o host"
    assert visto["dns"] == "falhou"
    assert visto["interfaces"] == ["lo"]
    # Controle: o socket funciona: o que falta é rede, não a biblioteca.
    assert visto["loopback"] == "ECONNREFUSED"


# ---- sistema de arquivos somente leitura ----


CAMINHOS = (
    "/raiz",
    "/app/codigo.py",
    "/app/app/sandbox/harness.py",
    "/app/sandbox/data/domrock/rh.jsonl",
    "/opt/venv/lib/python3.12/site-packages/pandas/atalho.py",
    "/tmp/rascunho",
    "/var/tmp/rascunho",
    "/dev/shm/rascunho",
    "/etc/hosts",
    "/home/appuser/.bashrc",
)

SONDA_DE_ESCRITA = f"""
for caminho in {CAMINHOS!r}:
    try:
        with open(caminho, "wb") as arquivo:
            arquivo.write(b"invadido")
        observado[caminho] = "gravou"
    except OSError as erro:
        observado[caminho] = cod(erro)
observado["dev_shm"] = os.path.exists("/dev/shm")
"""


def test_codigo_que_tenta_escrever_falha_em_todo_caminho(imagem: str) -> None:
    """Não há diretório de saída: a saída é o stdout (T-033), então toda escrita falha.

    A asserção exige `EROFS`, e não "qualquer erro": um caminho digitado errado devolveria
    `ENOENT` e passaria por bloqueado sem que nada tivesse sido tentado de verdade.
    """
    visto = observar(rodar(regra_sonda(SONDA_DE_ESCRITA), imagem))

    esperado = {caminho: "EROFS" for caminho in CAMINHOS if caminho != "/dev/shm/rascunho"}
    assert {caminho: visto[caminho] for caminho in esperado} == esperado
    # --read-only não alcança /dev/shm, que o Docker monta 1777; ipc_mode="none" alcança.
    assert visto["dev_shm"] is False and visto["/dev/shm/rascunho"] == "ENOENT"


def test_a_sonda_de_escrita_grava_quando_o_sistema_de_arquivos_e_gravavel(
    cliente: DockerClient, imagem: str
) -> None:
    """Controle do teste acima: sem ``read_only`` a mesma tentativa grava. Sem isto, um
    caminho digitado errado passaria por "bloqueado"."""
    opcoes = opcoes_de_isolamento(f"sbx-controle-{uuid4().hex[:8]}", {ROTULO_SANDBOX: "1"}, CURTO)
    opcoes["read_only"] = False

    with container_efemero(cliente, imagem, opcoes) as (container, soquete):
        fonte = serializar_payload(payload(regra_sonda(SONDA_DE_ESCRITA)))
        visto = observar(conduzir(container, soquete, fonte, CURTO))

    assert visto["/tmp/rascunho"] == "gravou" and visto["/var/tmp/rascunho"] == "gravou"
    # E, mesmo assim, o harness continua irregravável: os arquivos entram na imagem com
    # modo 0444 e dono root (T-033). São duas camadas, e esta não depende do worker.
    assert visto["/app/app/sandbox/harness.py"] == "EACCES"


# ---- timeout com kill automático ----


REGRA_QUE_NAO_TERMINA = """
import signal
import sys

def aplicar_regra(bases, apuracao_base, competencias):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    print("regra-em-execucao", file=sys.stderr, flush=True)
    while True:
        try:
            pass
        except BaseException:
            pass
"""


def test_codigo_que_excede_o_timeout_e_morto_automaticamente(imagem: str) -> None:
    """A regra ignora SIGTERM e engole exceção: o prazo não pede cooperação, mata."""
    limites = replace(LIMITES, timeout_s=5.0)

    saida = rodar(REGRA_QUE_NAO_TERMINA, imagem, limites=limites)

    assert saida.estourou_timeout is True
    assert saida.codigo_saida == SAIDA_SIGKILL
    assert saida.stdout == b"", "morto pelo kill, o container não escreve envelope"
    assert 5.0 <= saida.duracao_s < 20.0, "o kill não veio junto com o fim do prazo"


REGRA_QUE_DEIXA_THREAD_VIVA = """

import threading as _threading
import time as _time

_original = aplicar_regra


def aplicar_regra(bases, apuracao_base, competencias):
    saida = _original(bases, apuracao_base, competencias)
    # Thread não-daemon: o interpretador a espera na saída, depois do envelope escrito.
    _threading.Thread(target=_time.sleep, args=(300,), daemon=False).start()
    return saida
"""


def test_envelope_completo_pode_chegar_junto_com_um_timeout(imagem: str) -> None:
    """O pior caso para quem classifica (T-065): o resultado está inteiro no stdout **e** o
    container foi morto pelo prazo. A regra terminou e o envelope foi escrito, mas uma
    thread não-daemon segurou o processo na saída. Os dois fatos vêm no mesmo `SaidaBruta`,
    e quem decidir o desfecho não pode olhar só o stdout."""
    limites = replace(LIMITES, timeout_s=8.0)

    saida = rodar(EXEMPLO + REGRA_QUE_DEIXA_THREAD_VIVA, imagem, limites=limites)

    assert saida.estourou_timeout is True and saida.codigo_saida == SAIDA_SIGKILL
    assert json.loads(saida.stdout)["status"] == "sucesso", "o envelope saiu inteiro"


def test_execucao_dentro_do_prazo_nao_e_marcada_como_timeout(imagem: str) -> None:
    """Controle: ``estourou_timeout`` distingue, não é sempre verdadeiro."""
    saida = rodar(regra_sonda("observado['rapida'] = True"), imagem)

    assert saida.estourou_timeout is False and saida.codigo_saida == SAIDA_ERRO_CODIGO
    assert saida.duracao_s < LIMITES.timeout_s


# ---- limite de memória ----


def regra_que_aloca(mebibytes: int) -> str:
    return (
        "def aplicar_regra(bases, apuracao_base, competencias):\n"
        f"    bloco = bytearray({mebibytes} << 20)\n"
        "    for posicao in range(0, len(bloco), 4096):\n"
        "        bloco[posicao] = 1\n"
        "    raise RuntimeError('alocou ' + str(len(bloco)))\n"
    )


def test_codigo_que_excede_a_memoria_e_interrompido_pelo_limite(
    cliente: DockerClient, imagem: str
) -> None:
    """Interrompido pelo cgroup, não pelo host: é o ``OOMKilled`` que diz qual dos dois."""
    if not cliente.info().get("MemoryLimit"):
        pytest.fail("o daemon não aplica limite de memória: a restrição não pode ser provada")

    saida = rodar(regra_que_aloca(2048), imagem)

    assert saida.oom_killed is True
    assert saida.codigo_saida == SAIDA_SIGKILL and saida.estourou_timeout is False
    assert saida.stdout == b""


def test_alocacao_dentro_do_limite_nao_e_morta(imagem: str) -> None:
    """Controle: 64 MiB cabem nos 256 MiB, então o limite não mata qualquer regra."""
    saida = rodar(regra_que_aloca(64), imagem)

    assert saida.oom_killed is False and saida.codigo_saida == SAIDA_ERRO_CODIGO


# ---- usuário não-root e privilégios ----


SONDA_DE_PRIVILEGIO = """
observado["uid"] = os.getuid()
observado["euid"] = os.geteuid()
observado["gid"] = os.getgid()
estado = dict(
    linha.split(":", 1) for linha in open("/proc/self/status").read().splitlines() if ":" in linha
)
for campo in ("CapEff", "CapPrm", "NoNewPrivs", "Seccomp"):
    observado[campo] = estado[campo].strip()
try:
    os.setuid(0)
    observado["setuid"] = "virou root"
except OSError as erro:
    observado["setuid"] = cod(erro)
"""


def test_o_processo_dentro_do_container_nao_e_root_e_nao_consegue_virar(imagem: str) -> None:
    visto = observar(rodar(regra_sonda(SONDA_DE_PRIVILEGIO), imagem))

    assert (visto["uid"], visto["euid"], visto["gid"]) == (1000, 1000, 1000)
    assert visto["setuid"] == "EPERM"
    # Sem capability nenhuma, sem ganhar privilégio por setuid e com o seccomp do Docker.
    assert visto["CapEff"] == "0000000000000000" and visto["CapPrm"] == "0000000000000000"
    assert visto["NoNewPrivs"] == "1" and visto["Seccomp"] == "2"


# ---- nem orçamento nem credenciais ----


SONDA_DE_SEGREDO = """
observado["ambiente"] = dict(os.environ)
observado["docker_sock"] = os.path.exists("/var/run/docker.sock")
observado["montagens"] = [
    linha.split()[1] for linha in open("/proc/self/mounts").read().splitlines()
]
observado["argumentos"] = sys.argv
"""


def test_o_container_nao_recebe_orcamento_nem_credencial(imagem: str) -> None:
    saida = rodar(regra_sonda(SONDA_DE_SEGREDO), imagem)
    visto = observar(saida)

    ambiente: dict[str, str] = visto["ambiente"]
    assert [chave for chave in ambiente if SEGREDO.search(chave)] == []
    assert SENTINELA not in "".join(ambiente.values()), "credencial do worker vazou no ambiente"
    assert SENTINELA not in saida.stderr.decode("utf-8")
    assert "orcamento" not in json.dumps(visto).lower()
    assert visto["docker_sock"] is False, "o container alcança o daemon que o criou"
    assert [ponto for ponto in visto["montagens"] if "docker" in ponto] == []


def test_a_sonda_de_ambiente_enxerga_uma_variavel_quando_ela_e_passada(
    cliente: DockerClient, imagem: str
) -> None:
    """Controle do teste acima: passando uma variável, a sonda a encontra. Sem isto, uma
    sonda quebrada afirmaria "nenhuma credencial" lendo coisa nenhuma."""
    opcoes = opcoes_de_isolamento(f"sbx-controle-{uuid4().hex[:8]}", {ROTULO_SANDBOX: "1"}, CURTO)
    opcoes["environment"] = {"SEGREDO_DE_CONTROLE": SENTINELA}

    with container_efemero(cliente, imagem, opcoes) as (container, soquete):
        fonte = serializar_payload(payload(regra_sonda(SONDA_DE_SEGREDO)))
        visto = observar(conduzir(container, soquete, fonte, CURTO))

    assert visto["ambiente"]["SEGREDO_DE_CONTROLE"] == SENTINELA


def test_o_payload_entregue_no_stdin_nao_carrega_orcamento(imagem: str) -> None:
    """O executor recusa campo desconhecido: se um dia o orçamento entrar no payload, a
    execução falha em voz alta em vez de rodar com o critério dentro do container."""
    bruto = serializar_payload(payload(EXEMPLO))

    assert b"orcamento" not in bruto


# ---- os limites chegam ao cgroup ----


SONDA_DE_CGROUP = """
for campo in ("cpu.max", "pids.max", "memory.max", "memory.swap.max"):
    observado[campo] = open("/sys/fs/cgroup/" + campo).read().strip()
"""


def test_os_limites_de_cpu_memoria_e_pids_valem_dentro_do_container(imagem: str) -> None:
    visto = observar(rodar(regra_sonda(SONDA_DE_CGROUP), imagem))

    assert visto["cpu.max"] == "100000 100000", "uma CPU, medida pelo próprio cgroup"
    assert visto["memory.max"] == str(256 * 1024 * 1024)
    assert visto["pids.max"] == "64"
    # Sem swap: com ele o cgroup deixaria o container continuar em disco em vez de matá-lo.
    assert visto["memory.swap.max"] == "0"


SONDA_DE_THREADS = """
import threading
import time
vivas = []
try:
    # Thread que dorme, e não que termina: a bomba só é bomba enquanto as tarefas vivem.
    for _ in range(500):
        tarefa = threading.Thread(target=time.sleep, args=(20,), daemon=True)
        tarefa.start()
        vivas.append(tarefa)
    observado["threads"] = "sem limite"
except RuntimeError:
    observado["threads"] = len(vivas)
"""


def test_codigo_que_tenta_uma_bomba_de_threads_esbarra_no_limite_de_pids(imagem: str) -> None:
    visto = observar(rodar(regra_sonda(SONDA_DE_THREADS), imagem))

    assert visto["threads"] != "sem limite"
    assert visto["threads"] < LIMITES.pids


# ---- a saída bruta tem teto ----


def test_saida_gigante_e_truncada_no_teto(imagem: str) -> None:
    """Um despejo de megabytes no stderr não pode derrubar o worker por memória."""
    fonte = (
        "import sys\n"
        "def aplicar_regra(bases, apuracao_base, competencias):\n"
        "    for _ in range(200):\n"
        "        sys.stderr.write('x' * 4096)\n"
        "    sys.stderr.flush()\n"
        "    raise RuntimeError('despejou')\n"
    )
    limites = replace(CURTO, teto_stderr=4096)

    saida = rodar(fonte, imagem, limites=limites)

    assert saida.stderr_truncado is True
    assert len(saida.stderr) == 4096
    assert saida.codigo_saida == SAIDA_ERRO_CODIGO, "o teto é de leitura, não mata a execução"


# ---- um container novo por execução ----


def test_duas_execucoes_seguidas_usam_containers_distintos(imagem: str) -> None:
    primeira = rodar(regra_sonda("observado['hostname'] = socket.gethostname()"), imagem)
    segunda = rodar(regra_sonda("observado['hostname'] = socket.gethostname()"), imagem)

    assert primeira.container_id != segunda.container_id
    # De dentro, o hostname é o id do container: duas execuções, dois containers.
    assert observar(primeira)["hostname"] != observar(segunda)["hostname"]


# ---- falha de infraestrutura ----


def test_imagem_inexistente_vira_erro_de_infraestrutura(imagem: str) -> None:
    """Não é culpa do código gerado, e quem classifica (T-065) precisa da distinção."""
    with pytest.raises(SandboxInfraError):
        executar_no_sandbox(payload(EXEMPLO), imagem="synapse-sandbox:inexistente", limites=CURTO)


def test_a_limpeza_enxerga_um_container_que_ainda_existe(
    cliente: DockerClient, imagem: str
) -> None:
    """Controle da fixture `nenhum_container_sobra`: o filtro por rótulo acha um container
    que existe. Sem isto, um rótulo que deixasse de ser aplicado faria a fixture procurar
    algo que nunca aparece e aprovar qualquer vazamento."""
    opcoes = opcoes_de_isolamento(f"sbx-controle-{uuid4().hex[:8]}", {ROTULO_SANDBOX: "1"}, CURTO)

    with container_efemero(cliente, imagem, opcoes) as (container, _soquete):
        durante = cliente.containers.list(all=True, filters={"label": ROTULO_SANDBOX})
        nomes = [existente.name for existente in durante]
        esperado = [container.name]

    assert nomes == esperado
    assert cliente.containers.list(all=True, filters={"label": ROTULO_SANDBOX}) == []


def test_envelope_maior_que_o_teto_de_stdout_e_truncado(imagem: str) -> None:
    """O teto vale para o stdout também, e não mata a execução: trunca a leitura."""
    limites = replace(CURTO, teto_stdout=200)

    saida = rodar(EXEMPLO, imagem, limites=limites)

    assert saida.stdout_truncado is True and len(saida.stdout) == 200
    assert saida.codigo_saida == SAIDA_SUCESSO and saida.stderr == b""


def test_o_container_e_removido_mesmo_quando_o_prazo_estoura(
    cliente: DockerClient, imagem: str
) -> None:
    """A limpeza garantida da arquitetura (§3.4): o assert está na fixture autouse, e
    este teste existe para exercê-la no pior caso."""
    inicio = time.monotonic()

    saida = rodar(REGRA_QUE_NAO_TERMINA, imagem, limites=replace(LIMITES, timeout_s=5.0))

    assert saida.estourou_timeout and time.monotonic() - inicio < 60
    assert cliente.containers.list(all=True, filters={"id": saida.container_id}) == []


# ---- o cancelamento: o encerramento do worker no meio de uma execução ----


def test_cancelar_mata_o_container_em_curso_e_o_remove_muito_antes_do_prazo(imagem: str) -> None:
    """A regra dorme 10 minutos e o prazo é de 20 s: o cancelamento marcado aos 3 s tem de matar o
    container e removê-lo em poucos segundos (o `nenhum_container_sobra` confere a remoção)."""
    fonte = (
        "import time\n\n"
        "def aplicar_regra(bases, apuracao_base, competencias):\n"
        "    time.sleep(600)\n"
    )
    cancelar = threading.Event()
    threading.Timer(3.0, cancelar.set).start()
    inicio = time.monotonic()

    with pytest.raises(SandboxCanceladoError):
        executar_no_sandbox(payload(fonte), imagem=imagem, limites=CURTO, cancelar=cancelar)

    assert time.monotonic() - inicio < 10.0


def test_cancelar_que_nunca_e_marcado_nao_muda_o_desfecho(imagem: str) -> None:
    saida = executar_no_sandbox(
        payload(EXEMPLO), imagem=imagem, limites=CURTO, cancelar=threading.Event()
    )

    assert (saida.codigo_saida, saida.estourou_timeout) == (0, False)
    assert json.loads(saida.stdout)["status"] == "sucesso"


def test_o_prazo_continua_valendo_com_um_cancelamento_nunca_marcado(imagem: str) -> None:
    saida = executar_no_sandbox(
        payload(REGRA_QUE_NAO_TERMINA),
        imagem=imagem,
        limites=replace(LIMITES, timeout_s=5.0),
        cancelar=threading.Event(),
    )

    assert saida.estourou_timeout is True
    assert saida.codigo_saida == SAIDA_SIGKILL
