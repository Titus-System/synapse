import io
import json
import subprocess
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from app.execucao.preparo import PayloadContainer
from app.sandbox import executor
from app.sandbox.envelope import (
    CAMPOS_PAYLOAD,
    SAIDA_ASSERCAO_VIOLADA,
    SAIDA_ERRO_CODIGO,
    SAIDA_HARNESS,
    SAIDA_SIGTERM,
    SAIDA_SUCESSO,
)
from app.sandbox.executor import PayloadInvalidoError, ler_payload, processar
from tests.app.sandbox.test_harness import EXEMPLO, REGRA_SEM_EFEITO
from tests.app.sandbox.test_resultado import com_orcamento, validar_no_contrato

WORKER = Path(__file__).resolve().parents[3]
JOB_ID = "3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021"
CODIGO_ID = "5d4c3b2a-1f0e-4d9c-8b7a-6e5d4c3b2a19"


def payload(
    fonte: str = EXEMPLO, competencias: Any = ("2025-11",), **mudancas: Any
) -> dict[str, Any]:
    corpo: dict[str, Any] = {
        "job_id": JOB_ID,
        "codigo_gerado_id": CODIGO_ID,
        "linguagem": "python",
        "fonte": fonte,
        "competencias": list(competencias) if isinstance(competencias, tuple) else competencias,
    }
    return corpo | mudancas


def bytes_do(corpo: dict[str, Any]) -> bytes:
    return json.dumps(corpo, ensure_ascii=False).encode("utf-8")


def rodar(corpo: dict[str, Any]) -> tuple[int, bytes]:
    saida = io.BytesIO()
    codigo = processar(io.BytesIO(bytes_do(corpo)), saida)
    return codigo, saida.getvalue()


def rodar_e_ler(corpo: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    codigo, bruto = rodar(corpo)
    assert bruto.endswith(b"\n") and bruto.count(b"\n") == 1, "o envelope é uma linha"
    return codigo, json.loads(bruto)


# ---- os códigos de saída são contrato com a T-064 ----


def test_codigos_de_saida_sao_literais_e_distintos() -> None:
    """Os testes abaixo comparam com as constantes, e uma constante comparada com ela
    mesma não prova nada: trocar 1 por 3 colidiria a falha do harness com erro_codigo e
    todos passariam. O worker decide o status pelo número, então o número é fixado aqui."""
    codigos = (
        SAIDA_SUCESSO,
        SAIDA_HARNESS,
        SAIDA_ASSERCAO_VIOLADA,
        SAIDA_ERRO_CODIGO,
        SAIDA_SIGTERM,
    )

    assert codigos == (0, 1, 2, 3, 143)
    assert len(set(codigos)) == len(codigos)


def test_falha_nao_tratada_do_python_coincide_com_falha_do_harness() -> None:
    """1 é o que o Python devolve para exceção não tratada. Por isso é o código do harness:
    uma falha inesperada nunca é atribuída à regra por engano."""
    processo = _executar_processo(b"", "-c", "raise RuntimeError('nao tratada')")

    assert processo.returncode == SAIDA_HARNESS == 1


# ---- o payload ----


def test_payload_valido_e_lido() -> None:
    lido = ler_payload(bytes_do(payload()))

    assert (lido.job_id, lido.codigo_gerado_id, lido.competencias) == (
        JOB_ID,
        CODIGO_ID,
        ("2025-11",),
    )
    assert lido.fonte == EXEMPLO


def test_fonte_com_acento_atravessa_o_json_byte_a_byte() -> None:
    fonte = '"""Comissão é útil: ação, não, coração."""\nx = "日本語"\n'

    assert ler_payload(bytes_do(payload(fonte))).fonte == fonte


def test_o_exemplo_do_contrato_atravessa_o_json_byte_a_byte() -> None:
    assert ler_payload(bytes_do(payload())).fonte.encode() == EXEMPLO.encode()


@pytest.mark.parametrize(
    ("dados", "trecho"),
    [
        ("ação".encode("latin-1"), "UTF-8"),
        (b"isto nao e json", "UTF-8"),
        (b"[]", "objeto JSON"),
        (bytes_do(payload(orcamento=485000.0)), r"sobram \['orcamento'\]"),
        (bytes_do({k: v for k, v in payload().items() if k != "fonte"}), r"faltam \['fonte'\]"),
        (bytes_do(payload(linguagem="r")), "linguagem"),
        (bytes_do(payload(job_id="")), "job_id"),
        (bytes_do(payload(fonte="")), "fonte"),
        (bytes_do(payload(competencias=[])), "competencias"),
        (bytes_do(payload(competencias="2025-11")), "competencias"),
        (bytes_do(payload(competencias=[202511])), "competencias"),
    ],
)
def test_payload_invalido_e_recusado(dados: bytes, trecho: str) -> None:
    with pytest.raises(PayloadInvalidoError, match=trecho):
        ler_payload(dados)


def test_orcamento_no_payload_e_recusado_sem_repetir_o_valor() -> None:
    with pytest.raises(PayloadInvalidoError) as erro:
        ler_payload(bytes_do(payload(orcamento=485000.0)))

    assert "485000" not in str(erro.value)


def test_campos_do_payload_sao_os_de_payload_container() -> None:
    """A fronteira que o worker escreve e a que o sandbox lê têm de ser a mesma lista."""
    assert {campo.name for campo in fields(PayloadContainer)} == CAMPOS_PAYLOAD


# ---- sucesso ----


def test_exemplo_do_contrato_devolve_envelope_de_sucesso() -> None:
    codigo, envelope = rodar_e_ler(payload())

    assert codigo == SAIDA_SUCESSO
    assert envelope["status"] == "sucesso" and envelope["erro"] is None
    assert envelope["versao"] == 1
    assert (envelope["job_id"], envelope["codigo_gerado_id"]) == (JOB_ID, CODIGO_ID)
    assert envelope["competencias"] == ["2025-11"]
    assert envelope["resultado"]["totais"]["baseline"] == 508382.32
    assert envelope["assercoes"] == envelope["resultado"]["assercoes"]
    assert [a["resultado"] for a in envelope["assercoes"]] == ["ok"]


def test_o_resultado_nao_traz_orcamento_nem_linha_das_bases() -> None:
    _, bruto = rodar(payload())

    assert b"orcamento" not in bruto
    assert b"MATRIC-" not in bruto and b"matricula" not in bruto


def test_resultado_do_envelope_valida_no_contrato_com_o_orcamento_do_worker() -> None:
    _, envelope = rodar_e_ler(payload())

    processo = validar_no_contrato(com_orcamento(envelope["resultado"]))

    assert processo.returncode == 0, processo.stderr


def test_mesma_entrada_produz_os_mesmos_bytes() -> None:
    assert rodar(payload())[1] == rodar(payload())[1]


def test_periodo_de_varios_meses_devolve_uma_entrada_por_competencia() -> None:
    _, envelope = rodar_e_ler(payload(competencias=("2025-09", "2025-10", "2025-11")))

    assert list(envelope["resultado"]["decomposicao"]["competencia"]) == [
        "2025-09",
        "2025-10",
        "2025-11",
    ]


# ---- erro no código gerado ----

REGRA_COM_SAIDA_INVALIDA = "def aplicar_regra(bases, apuracao_base, competencias):\n    return 1\n"
REGRA_COM_DIFERENCA_SEM_DONO = """
def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    simulada.loc[simulada.index[0], "comissao"] += 5.0
    contribuicoes = simulada.iloc[0:0].copy()
    contribuicoes["elemento_ref"] = []
    contribuicoes["delta"] = []
    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
"""


@pytest.mark.parametrize(
    ("fonte", "tipo"),
    [
        ("def aplicar_regra(b, a, c):\n    raise RuntimeError('boom')\n", "RuntimeError"),
        ("import modulo_que_nao_existe_xyz\n", "ModuleNotFoundError"),
        ("x = 1\n", "RegraInvalidaError"),
        ("def aplicar_regra(:\n", "RegraInvalidaError"),
        ("import sys\nsys.exit(0)\n", "SystemExit"),
        (REGRA_COM_SAIDA_INVALIDA, "SaidaForaDoContratoError"),
        (REGRA_COM_DIFERENCA_SEM_DONO, "DecomposicaoInconsistenteError"),
    ],
)
def test_defeito_no_codigo_gerado_vira_erro_codigo(fonte: str, tipo: str) -> None:
    codigo, envelope = rodar_e_ler(payload(fonte))

    assert codigo == SAIDA_ERRO_CODIGO
    assert envelope["status"] == "erro_codigo"
    assert envelope["erro"]["tipo"] == tipo
    assert envelope["resultado"] is None and envelope["assercoes"] == []


def test_sys_exit_da_regra_nao_parece_sucesso() -> None:
    """SystemExit não é Exception: sem tratamento próprio o processo sairia com 0 e sem
    envelope, e pareceria sucesso para quem só olha o código de saída."""
    codigo, _ = rodar_e_ler(payload("import sys\nsys.exit(0)\n"))

    assert codigo != SAIDA_SUCESSO


def test_erro_carrega_a_linha_da_regra_e_nenhum_quadro_do_harness() -> None:
    fonte = "def aplicar_regra(b, a, c):\n    return 1 / 0\n"

    _, envelope = rodar_e_ler(payload(fonte))

    assert envelope["erro"]["mensagem"] == "division by zero"
    assert 'File "regra.py", line 2, in aplicar_regra' in envelope["erro"]["traceback"]
    assert "return 1 / 0" in envelope["erro"]["traceback"]
    assert "harness.py" not in envelope["erro"]["traceback"]


def test_mensagem_e_traceback_de_erro_tem_tamanho_limitado() -> None:
    fonte = "def aplicar_regra(b, a, c):\n    raise ValueError('x' * 5000)\n"

    _, envelope = rodar_e_ler(payload(fonte))

    assert len(envelope["erro"]["mensagem"]) == 1000
    assert len(envelope["erro"]["traceback"]) <= 8000


def test_excecao_com_str_que_levanta_nao_derruba_o_envelope() -> None:
    fonte = """
class Ruim(Exception):
    def __str__(self):
        raise RuntimeError("str quebrado")

def aplicar_regra(b, a, c):
    raise Ruim()
"""

    codigo, envelope = rodar_e_ler(payload(fonte))

    assert codigo == SAIDA_ERRO_CODIGO
    assert envelope["erro"]["mensagem"] == "<mensagem ilegível>"


# ---- asserção violada ----


def test_comissao_negativa_e_assercao_violada_e_nao_erro_de_codigo() -> None:
    fonte = """
def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    simulada.loc[simulada.index[0], "comissao"] = -1.0
    contribuicoes = simulada.iloc[:1].copy()
    contribuicoes["elemento_ref"] = "elem.1"
    contribuicoes["delta"] = -1.0
    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
"""

    codigo, envelope = rodar_e_ler(payload(fonte))

    assert codigo == SAIDA_ASSERCAO_VIOLADA
    assert envelope["status"] == "assercao_violada"
    assert envelope["resultado"] is None and envelope["erro"] is None
    assert [(a["nome"], a["resultado"]) for a in envelope["assercoes"]] == [
        ("sem_comissao_negativa", "violada")
    ]


# ---- falha do harness: sem envelope ----


@pytest.mark.parametrize(
    "corpo",
    [
        payload(orcamento=1.0),
        payload(linguagem="r"),
        payload(competencias=("2025-07",)),
        payload(competencias=("2025-11", "2025-11")),
    ],
    ids=["orcamento_no_payload", "linguagem_errada", "competencia_nao_publicada", "repetida"],
)
def test_payload_ou_periodo_invalido_sai_com_codigo_1_sem_envelope(
    corpo: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    codigo, bruto = rodar(corpo)

    assert codigo == SAIDA_HARNESS and bruto == b""
    assert "falha do harness" in capsys.readouterr().err


def test_bug_do_harness_na_agregacao_nao_e_culpa_da_regra(monkeypatch: pytest.MonkeyPatch) -> None:
    def quebrado(*_: object, **__: object) -> None:
        raise RuntimeError("bug do harness")

    monkeypatch.setattr(executor, "agregar", quebrado)

    with pytest.raises(RuntimeError, match="bug do harness"):
        rodar(payload(REGRA_SEM_EFEITO))


# ---- o processo de verdade: canal de saída e código de saída ----


def _executar_processo(entrada: bytes, *argumentos: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, *argumentos],
        input=entrada,
        capture_output=True,
        cwd=WORKER,
        check=False,
        timeout=120,
    )


REGRA_BARULHENTA = """
import os
import subprocess
import sys

def aplicar_regra(bases, apuracao_base, competencias):
    print("lixo-do-print")
    sys.stdout.write("lixo-do-write\\n")
    os.write(1, b"lixo-do-descritor\\n")
    subprocess.run(["echo", "lixo-do-subprocesso"], check=False)
    contribuicoes = apuracao_base.iloc[0:0].copy()
    contribuicoes["elemento_ref"] = []
    contribuicoes["delta"] = []
    return {"apuracao_simulada": apuracao_base.copy(), "contribuicoes": contribuicoes}
"""


def test_saida_da_regra_nao_se_mistura_ao_envelope() -> None:
    """print, sys.stdout, escrita direta no descritor 1 e subprocesso: nada disso pode
    chegar ao stdout, onde só o envelope tem lugar."""
    processo = _executar_processo(bytes_do(payload(REGRA_BARULHENTA)), "-m", "app.sandbox.executor")

    assert processo.returncode == SAIDA_SUCESSO, processo.stderr
    linhas = processo.stdout.splitlines()
    assert len(linhas) == 1 and json.loads(linhas[0])["status"] == "sucesso"
    for lixo in (b"lixo-do-print", b"lixo-do-write", b"lixo-do-descritor", b"lixo-do-subprocesso"):
        assert lixo in processo.stderr and lixo not in processo.stdout


def test_falha_inesperada_do_harness_sai_com_codigo_1_e_stdout_vazio() -> None:
    programa = (
        "from app.sandbox import executor\n"
        "def quebrado(*a, **k):\n"
        "    raise RuntimeError('bug do harness')\n"
        "executor.agregar = quebrado\n"
        "raise SystemExit(executor.main())\n"
    )

    processo = _executar_processo(bytes_do(payload(REGRA_SEM_EFEITO)), "-c", programa)

    assert processo.returncode == SAIDA_HARNESS
    assert processo.stdout == b""
    assert b"bug do harness" in processo.stderr


def test_codigo_de_saida_do_processo_acompanha_o_status() -> None:
    fonte = "def aplicar_regra(b, a, c):\n    raise RuntimeError('boom')\n"

    processo = _executar_processo(bytes_do(payload(fonte)), "-m", "app.sandbox.executor")

    assert processo.returncode == SAIDA_ERRO_CODIGO
    assert json.loads(processo.stdout)["status"] == "erro_codigo"
