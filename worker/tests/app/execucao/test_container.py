"""As flags, os limites e o payload da execução isolada (T-064), sem subir container."""

import json
import threading
import time
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from app.config import get_settings
from app.execucao.container import (
    LIMITES,
    PASSO_DA_ESPERA_S,
    PREFIXO_NOME,
    ROTULO_JOB,
    ROTULO_SANDBOX,
    Limites,
    SandboxCanceladoError,
    SandboxInfraError,
    _esperar,
    conduzir,
    executar_no_sandbox,
    opcoes_de_isolamento,
    serializar_payload,
)
from app.execucao.preparo import PayloadContainer, preparar_execucao
from app.mensageria.contracts import ExecutarCodigo
from app.repositorio.codigos_gerados import CodigoGerado
from app.sandbox.envelope import CAMPOS_PAYLOAD
from app.sandbox.executor import ler_payload

JOB_ID = UUID("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021")
CODIGO_ID = UUID("5d4c3b2a-1f0e-4d9c-8b7a-6e5d4c3b2a19")

FONTE = "def aplicar_regra(bases, apuracao_base, competencias):\n    return {}  # ação, matrícula\n"


def payload(**mudancas: Any) -> PayloadContainer:
    campos: dict[str, Any] = {
        "job_id": JOB_ID,
        "codigo_gerado_id": CODIGO_ID,
        "linguagem": "python",
        "fonte": FONTE,
        "competencias": ["2025-11"],
    }
    return PayloadContainer(**(campos | mudancas))


def opcoes(limites: Limites = LIMITES) -> dict[str, Any]:
    return opcoes_de_isolamento("sbx-teste", {ROTULO_SANDBOX: "1"}, limites)


# ---- as flags de isolamento ----


def test_as_opcoes_do_container_sao_exatamente_as_flags_de_isolamento() -> None:
    """Igualdade, não subconjunto: este teste é o que quebra quando alguém afrouxa uma
    flag "só para desenvolver" ou acrescenta uma porta de entrada nova."""
    resultado = opcoes()
    log_config = resultado.pop("log_config")

    assert resultado == {
        "name": "sbx-teste",
        "labels": {ROTULO_SANDBOX: "1"},
        "stdin_open": True,
        "network_mode": "none",
        "network_disabled": True,
        "read_only": True,
        "ipc_mode": "none",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "privileged": False,
        "mem_limit": "256m",
        "memswap_limit": "256m",
        "nano_cpus": 1_000_000_000,
        "pids_limit": 64,
        "environment": {},
        "volumes": {},
    }
    assert (log_config["Type"], log_config["Config"]) == (
        "json-file",
        {"max-size": "8m", "max-file": "1"},
    )


def test_a_memoria_nao_tem_folga_em_swap() -> None:
    """Com swap maior que a memória, o cgroup deixaria o container continuar em disco em
    vez de matá-lo, e o limite de memória viraria uma sugestão lenta."""
    assert opcoes()["memswap_limit"] == opcoes()["mem_limit"]


def test_os_limites_de_producao_sao_os_medidos() -> None:
    """Medidos contra a imagem real: 90 MiB de pico e 1,2 s nas cinco competências."""
    assert (LIMITES.memoria, LIMITES.timeout_s, LIMITES.cpus, LIMITES.pids) == (
        "256m",
        60.0,
        1.0,
        64,
    )


def test_os_limites_apertados_dos_testes_chegam_as_opcoes() -> None:
    """Os testes encurtam prazo e memória para não levarem minutos; o que eles exercitam
    continua sendo o mesmo caminho de produção."""
    resultado = opcoes(Limites(timeout_s=3.0, memoria="64m", cpus=0.5, pids=16))

    assert (resultado["mem_limit"], resultado["nano_cpus"], resultado["pids_limit"]) == (
        "64m",
        500_000_000,
        16,
    )


def test_o_container_nao_recebe_ambiente_nem_volume() -> None:
    """É o que separa o worker, que fala com o daemon e conhece as credenciais, do
    container, que não pode conhecer nem o orçamento (T-066)."""
    assert opcoes()["environment"] == {}
    assert opcoes()["volumes"] == {}


def test_o_nome_do_container_e_o_rotulo_do_job_existem_para_o_watchdog() -> None:
    assert PREFIXO_NOME == "sbx-"
    assert ROTULO_SANDBOX == "synapse.sandbox" and ROTULO_JOB == "synapse.job_id"


# ---- o payload que vai para o stdin ----


def test_o_payload_tem_exatamente_os_campos_do_contrato() -> None:
    corpo = json.loads(serializar_payload(payload()))

    assert corpo.keys() == set(CAMPOS_PAYLOAD)
    assert "orcamento" not in corpo


def test_o_payload_e_aceito_pelo_executor_da_imagem() -> None:
    """A paridade com o outro lado do stdin, conferida sem subir container: o executor
    recusa campo que sobra ou que falta."""
    lido = ler_payload(serializar_payload(payload(competencias=["2025-08", "2025-11"])))

    assert (lido.job_id, lido.codigo_gerado_id) == (str(JOB_ID), str(CODIGO_ID))
    assert lido.competencias == ("2025-08", "2025-11")
    assert lido.fonte == FONTE


def test_o_payload_preserva_acento_da_fonte_em_utf8() -> None:
    """A fonte vem de texto ditado por usuário; um acento perdido aqui vira erro de
    sintaxe dentro do container, a quilômetros da causa."""
    fonte = "# regra de comissão da matrícula órfã\ndef aplicar_regra(b, a, c):\n    return {}\n"

    bruto = serializar_payload(payload(fonte=fonte))

    assert bruto.decode("utf-8")
    assert ler_payload(bruto).fonte == fonte


ORCAMENTO_SENTINELA = 487123.45
FORMAS_DO_ORCAMENTO = ("487123.45", "48712345", "487123,45", "487123.4", "4.8712345e+05")


def test_o_orcamento_nao_aparece_no_payload_nem_nas_opcoes_do_container() -> None:
    """A execução preparada retém o orçamento fora do payload; o que vai para o stdin, e o que
    configura o container, não o contém em forma nenhuma."""
    comando = ExecutarCodigo(
        job_id=JOB_ID,
        codigo_gerado_id=CODIGO_ID,
        competencias=["2025-11"],
        orcamento=ORCAMENTO_SENTINELA,
    )
    codigo = CodigoGerado(id=CODIGO_ID, job_id=JOB_ID, linguagem="python", fonte=FONTE)

    execucao = preparar_execucao(comando, codigo)
    superficie = (
        serializar_payload(execucao.payload).decode() + repr(opcoes()) + repr(execucao.payload)
    )

    assert execucao.orcamento == ORCAMENTO_SENTINELA
    for forma in FORMAS_DO_ORCAMENTO:
        assert forma not in superficie


@pytest.mark.parametrize("campo", sorted(CAMPOS_PAYLOAD))
def test_nenhum_campo_do_contrato_fica_de_fora(campo: str) -> None:
    assert campo in json.loads(serializar_payload(payload()))


# ---- falha de infraestrutura ----


def test_daemon_inalcancavel_vira_erro_de_infraestrutura(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem daemon não há execução, e isso não é culpa do código gerado: quem classificar
    (T-065) precisa da distinção para repetir o comando em vez de reprovar a regra."""
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/daemon-que-nao-existe.sock")
    get_settings.cache_clear()

    try:
        with pytest.raises(SandboxInfraError, match="daemon"):
            executar_no_sandbox(payload(), imagem="synapse-sandbox:qualquer")
    finally:
        get_settings.cache_clear()


# ---- o cancelamento (o encerramento do worker no meio de uma execução) ----


class ContainerFalso:
    """Um container que só termina quando `kill` é chamado. `wait` estoura o timeout de leitura
    do cliente HTTP (um `OSError`), como o SDK faz, quando nada acontece no prazo."""

    id = "c" * 64

    def __init__(self, ja_terminado: bool = False) -> None:
        self.terminou = threading.Event()
        if ja_terminado:
            self.terminou.set()
        self.esperas: list[float] = []
        self.mortes = 0

    def start(self) -> None:
        return None

    def wait(self, timeout: float) -> dict[str, int]:
        self.esperas.append(timeout)
        if self.terminou.wait(timeout):
            return {"StatusCode": 137}
        raise OSError("read timeout")

    def kill(self) -> None:
        self.mortes += 1
        self.terminou.set()


def test_sem_cancelamento_a_espera_e_uma_chamada_so_com_o_prazo_inteiro() -> None:
    """O caminho de produção sem `cancelar` continua um único `wait` longo, sem passos."""
    container = ContainerFalso(ja_terminado=True)

    assert _esperar(container, 60.0, time.monotonic()) is True  # type: ignore[arg-type]
    assert container.esperas == [60.0]


def test_a_espera_ve_o_cancelamento_em_um_passo_e_nao_no_fim_do_prazo() -> None:
    """O prazo é de 60 s; o cancelamento tem de ser visto em uma fração disso, senão o
    encerramento esperaria o `docker stop` perder a paciência."""
    container = ContainerFalso()
    cancelar = threading.Event()
    threading.Timer(0.3, cancelar.set).start()
    inicio = time.monotonic()

    with pytest.raises(SandboxCanceladoError):
        _esperar(container, 60.0, inicio, cancelar)  # type: ignore[arg-type]

    assert time.monotonic() - inicio < 2.0
    assert max(container.esperas) <= PASSO_DA_ESPERA_S


def test_cancelamento_ja_marcado_nao_espera_nada() -> None:
    container = ContainerFalso()
    cancelar = threading.Event()
    cancelar.set()

    with pytest.raises(SandboxCanceladoError):
        _esperar(container, 60.0, time.monotonic(), cancelar)  # type: ignore[arg-type]

    assert container.esperas == []


def test_cancelar_nao_le_a_saida_nem_classifica() -> None:
    """Não há desfecho: a exceção sobe antes de qualquer leitura, e o container é morto e removido
    pelo `remove(force=True)` do `finally` de `container_efemero` (testado com Docker real)."""
    container = MagicMock()
    soquete = MagicMock()
    cancelar = threading.Event()
    cancelar.set()

    with pytest.raises(SandboxCanceladoError):
        conduzir(container, soquete, b"{}", Limites(timeout_s=60.0), cancelar)

    container.start.assert_called_once()
    soquete._sock.sendall.assert_called_once_with(b"{}")
    container.reload.assert_not_called()
    container.logs.assert_not_called()


def test_o_cancelamento_nao_e_erro_de_infraestrutura() -> None:
    """Se fosse, o comando entraria no retry e no esgotamento (DEC-094) por um encerramento."""
    assert not issubclass(SandboxCanceladoError, SandboxInfraError)
