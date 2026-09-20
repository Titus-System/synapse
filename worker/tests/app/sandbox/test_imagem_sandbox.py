"""Critérios de aceitação da T-033, exercitados contra a imagem real.

Marcados com ``docker``: ``verify.sh`` só os roda quando o daemon responde.
"""

import hashlib
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from app.sandbox.carga import RAIZ_DADOS, competencias_publicadas
from app.sandbox.envelope import SAIDA_ERRO_CODIGO, SAIDA_SUCESSO
from tests.app.sandbox.imagem import (
    DADOS_DA_IMAGEM,
    DADOS_PROIBIDOS,
    DISTRIBUICOES_PERMITIDAS,
    MODULOS_DA_IMAGEM,
    MODULOS_PROIBIDOS,
)
from tests.app.sandbox.test_executor import bytes_do, payload
from tests.app.sandbox.test_harness import EXEMPLO
from tests.app.sandbox.test_resultado import com_orcamento, validar_no_contrato
from tests.app.sandbox.varredura_orcamento import varrer_ambiente, varrer_codigo, varrer_dados

pytestmark = pytest.mark.docker

REQUISITOS = Path(__file__).resolve().parents[3] / "sandbox" / "requirements.txt"
VARREDURA = Path(__file__).with_name("varredura_orcamento.py")


def rodar(
    imagem: str,
    *,
    entrada: bytes = b"",
    argumentos: Sequence[str] = (),
    entrypoint: str | None = None,
    extras: Sequence[str] = (),
) -> subprocess.CompletedProcess[bytes]:
    """Executa a imagem com as flags do critério de aceitação: sem rede, somente leitura,
    sem volume nenhum."""
    comando = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only"]
    if entrypoint:
        comando += ["--entrypoint", entrypoint]
    comando += [*extras, imagem, *argumentos]
    return subprocess.run(comando, input=entrada, capture_output=True, check=False, timeout=600)


def rodar_python(imagem: str, programa: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
    return rodar(imagem, entrypoint="python", argumentos=["-c", programa], **kwargs)


def dentro(imagem: str, programa: str) -> Any:
    """Roda um programa que imprime JSON e devolve o valor."""
    processo = rodar_python(imagem, programa)
    assert processo.returncode == 0, processo.stderr.decode()
    return json.loads(processo.stdout)


# ---- o critério principal ----


def test_executa_a_funcao_de_exemplo_do_contrato_sobre_novembro(imagem: str) -> None:
    processo = rodar(imagem, entrada=bytes_do(payload(EXEMPLO, ("2025-11",))))

    assert processo.returncode == SAIDA_SUCESSO, processo.stderr.decode()
    assert processo.stderr == b""
    envelope = json.loads(processo.stdout)
    assert envelope["status"] == "sucesso"
    # O oráculo é o total que a T-032 congelou, calculado por outro caminho.
    assert envelope["resultado"]["totais"]["baseline"] == 508382.32
    assert envelope["resultado"]["decomposicao"]["competencia"] == {
        "2025-11": envelope["resultado"]["totais"]["diferenca_abs"]
    }


def test_resultado_da_imagem_valida_no_schema_do_contrato(imagem: str) -> None:
    processo = rodar(imagem, entrada=bytes_do(payload(EXEMPLO, ("2025-11",))))
    resultado = json.loads(processo.stdout)["resultado"]

    validacao = validar_no_contrato(com_orcamento(resultado))

    assert validacao.returncode == 0, validacao.stderr


def test_periodo_inteiro_das_cinco_competencias(imagem: str) -> None:
    competencias = competencias_publicadas()

    processo = rodar(imagem, entrada=bytes_do(payload(EXEMPLO, competencias)))

    assert processo.returncode == SAIDA_SUCESSO, processo.stderr.decode()
    envelope = json.loads(processo.stdout)
    assert list(envelope["resultado"]["decomposicao"]["competencia"]) == list(competencias)
    assert envelope["resultado"]["totais"]["baseline"] == 3299894.24


def test_execucoes_iguais_produzem_a_mesma_saida(imagem: str) -> None:
    entrada = bytes_do(payload(EXEMPLO, ("2025-11",)))

    primeira = rodar(imagem, entrada=entrada)
    segunda = rodar(imagem, entrada=entrada)

    assert primeira.stdout == segunda.stdout


# ---- isolamento ----


def test_o_processo_roda_como_usuario_nao_root(imagem: str) -> None:
    identidade = dentro(imagem, "import json,os;print(json.dumps([os.getuid(), os.getgid()]))")
    configurado = subprocess.run(
        ["docker", "image", "inspect", imagem, "--format", "{{.Config.User}}"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert identidade == [1000, 1000]
    # Sem isto, o uid acima dependeria de o teste não passar --user.
    assert configurado.stdout.strip() == "appuser"


def test_nenhum_volume_e_montado_e_a_raiz_e_somente_leitura(imagem: str) -> None:
    """Com --read-only e sem tmpfs, nem /app nem os diretórios temporários são graváveis.

    O ``tempfile`` levanta FileNotFoundError ("No usable temporary directory"), que é
    subclasse de OSError: o que importa é que gravar falhe, não o nome exato da classe.
    """
    programa = """
import json, tempfile
def bloqueado(tentativa):
    try:
        tentativa()
    except OSError:
        return True
    return False
def gravar_em_app():
    with open("/app/prova", "w"):
        pass
print(json.dumps({
    "raiz_bloqueada": bloqueado(gravar_em_app),
    "temporario_bloqueado": bloqueado(tempfile.NamedTemporaryFile),
    "montagens": [l.split()[1] for l in open("/proc/mounts") if l.split()[1].startswith("/app")],
}))
"""
    resultado = dentro(imagem, programa)

    assert resultado == {"raiz_bloqueada": True, "temporario_bloqueado": True, "montagens": []}


def test_a_regra_nao_alcanca_a_rede(imagem: str) -> None:
    fonte = """
import socket

def aplicar_regra(bases, apuracao_base, competencias):
    socket.create_connection(("1.1.1.1", 80), timeout=5)
"""
    processo = rodar(imagem, entrada=bytes_do(payload(fonte, ("2025-11",))))

    assert processo.returncode == SAIDA_ERRO_CODIGO
    assert json.loads(processo.stdout)["erro"]["tipo"] == "OSError"


def test_a_regra_nao_escreve_em_disco(imagem: str) -> None:
    fonte = """
def aplicar_regra(bases, apuracao_base, competencias):
    with open("/app/saida.csv", "w") as arquivo:
        arquivo.write("x")
"""
    processo = rodar(imagem, entrada=bytes_do(payload(fonte, ("2025-11",))))

    assert processo.returncode == SAIDA_ERRO_CODIGO
    assert json.loads(processo.stdout)["erro"]["tipo"] in {"OSError", "PermissionError"}


def test_o_ambiente_que_o_prompt_do_codegen_promete_e_o_que_a_imagem_entrega(
    imagem: str,
) -> None:
    """O prompt de geração (``ambiente_de_execucao`` em codegen/app/prompts/geracao_codigo.py)
    diz ao modelo como o código dele roda. Se a imagem deixar de ser assim, o prompt passa a
    mentir e ninguém vê. As sondas rodam pelo ponto de entrada real e voltam pela mensagem de
    uma exceção, que é o único canal de dentro da regra."""
    fonte = """
import json
import tempfile

def _bloqueado(tentativa, excecao):
    try:
        tentativa()
    except excecao:
        return True
    return False

def aplicar_regra(bases, apuracao_base, competencias):
    def import_relativo():
        from . import irmao  # noqa: F401
    sondas = {
        "nome": __name__,
        "arquivo": __file__,
        "import_relativo_falha": _bloqueado(import_relativo, ImportError),
        "open_para_escrita_falha": _bloqueado(lambda: open("/app/x.csv", "w"), OSError),
        "to_csv_falha": _bloqueado(lambda: apuracao_base.to_csv("/app/x.csv"), OSError),
        "tempfile_falha": _bloqueado(tempfile.NamedTemporaryFile, OSError),
    }
    raise RuntimeError(json.dumps(sondas))
"""
    processo = rodar(imagem, entrada=bytes_do(payload(fonte, ("2025-11",))))

    assert processo.returncode == SAIDA_ERRO_CODIGO
    sondas = json.loads(json.loads(processo.stdout)["erro"]["mensagem"])
    assert sondas == {
        "nome": "regra",  # nunca "__main__"
        "arquivo": "regra.py",  # nome fictício: não há arquivo de verdade
        "import_relativo_falha": True,
        "open_para_escrita_falha": True,
        "to_csv_falha": True,
        "tempfile_falha": True,
    }


def test_saida_da_regra_nao_contamina_o_envelope(imagem: str) -> None:
    fonte = """
import os, sys

def aplicar_regra(bases, apuracao_base, competencias):
    print("lixo-do-print")
    os.write(1, b"lixo-do-descritor\\n")
    contribuicoes = apuracao_base.iloc[0:0].copy()
    contribuicoes["elemento_ref"] = []
    contribuicoes["delta"] = []
    return {"apuracao_simulada": apuracao_base.copy(), "contribuicoes": contribuicoes}
"""
    processo = rodar(imagem, entrada=bytes_do(payload(fonte, ("2025-11",))))

    assert processo.returncode == SAIDA_SUCESSO, processo.stderr.decode()
    assert len(processo.stdout.splitlines()) == 1
    assert json.loads(processo.stdout)["status"] == "sucesso"
    assert b"lixo-do-print" in processo.stderr and b"lixo-do-print" not in processo.stdout


# ---- o conteúdo da imagem ----


def test_bibliotecas_instaladas_sao_exatamente_as_permitidas(imagem: str) -> None:
    programa = (
        "import json;from importlib.metadata import distributions;"
        "print(json.dumps(sorted(d.metadata['Name'] for d in distributions())))"
    )

    instaladas = dentro(imagem, programa)
    do_sistema = rodar(imagem, entrypoint="/usr/local/bin/python", argumentos=["-c", programa])

    assert set(instaladas) == set(DISTRIBUICOES_PERMITIDAS)
    # O Python da imagem base não pode ter sobrado com pacote nenhum, nem o pip.
    assert json.loads(do_sistema.stdout) == []


def test_pin_dos_requisitos_bate_com_o_instalado_e_com_a_faixa_do_contrato(imagem: str) -> None:
    pinadas = dict(
        linha.split("==")
        for linha in REQUISITOS.read_text(encoding="utf-8").splitlines()
        if linha.strip() and not linha.startswith("#")
    )
    programa = (
        "import json;from importlib.metadata import distributions;"
        "print(json.dumps({d.metadata['Name']: d.version for d in distributions()}))"
    )

    instaladas = dentro(imagem, programa)

    assert set(pinadas) == set(DISTRIBUICOES_PERMITIDAS)
    assert instaladas == pinadas
    # A T-034 tranca pandas na major 2.x.
    assert pinadas["pandas"].startswith("2.")


def test_a_imagem_nao_tem_pip_nem_compilador(imagem: str) -> None:
    programa = (
        "import json,shutil;"
        "print(json.dumps({n: shutil.which(n) for n in ('pip','pip3','gcc','cc','apt-get')}))"
    )

    encontrados = dentro(imagem, programa)

    assert encontrados["pip"] is None and encontrados["pip3"] is None
    assert encontrados["gcc"] is None and encontrados["cc"] is None


def test_modulos_da_imagem_sao_exatamente_a_lista_branca(imagem: str) -> None:
    programa = (
        "import json,pathlib;"
        "print(json.dumps(sorted(p.name for p in pathlib.Path('/app/app/sandbox').iterdir())))"
    )

    arquivos = dentro(imagem, programa)

    assert set(arquivos) == set(MODULOS_DA_IMAGEM)
    assert not set(arquivos) & MODULOS_PROIBIDOS


@pytest.mark.parametrize("modulo", sorted(MODULOS_PROIBIDOS))
def test_modulo_proibido_nao_e_importavel_na_imagem(imagem: str, modulo: str) -> None:
    nome = f"app.sandbox.{modulo.removesuffix('.py')}"

    processo = rodar_python(imagem, f"import {nome}")

    assert processo.returncode != 0
    # O módulo em si tem de estar ausente. Com daemon.py copiado, o import falharia do mesmo
    # jeito, mas por "No module named 'docker'", e o teste passaria pelo motivo errado.
    assert f"No module named '{nome}'".encode() in processo.stderr


def test_a_imagem_contem_as_bases_os_eventos_e_os_baselines(imagem: str) -> None:
    programa = (
        "import json,pathlib;raiz=pathlib.Path('/app/sandbox/data/domrock');"
        "print(json.dumps(sorted(str(p.relative_to(raiz))"
        " for p in raiz.rglob('*') if p.is_file())))"
    )

    arquivos = dentro(imagem, programa)

    assert set(arquivos) == set(DADOS_DA_IMAGEM)
    assert not set(arquivos) & DADOS_PROIBIDOS


def test_os_baselines_da_imagem_sao_os_congelados_pelo_manifesto(imagem: str) -> None:
    programa = (
        "import hashlib,json,pathlib;raiz=pathlib.Path('/app/sandbox/data/domrock');"
        "print(json.dumps({str(p.relative_to(raiz)): hashlib.sha256(p.read_bytes()).hexdigest()"
        " for p in sorted(raiz.glob('baselines/baseline-*.jsonl'))}))"
    )
    manifesto = json.loads(
        (RAIZ_DADOS / "baselines" / "manifesto.json").read_text(encoding="utf-8")
    )
    esperado = {dados["arquivo"]: dados["sha256"] for dados in manifesto["baselines"].values()}

    assert dentro(imagem, programa) == esperado


def test_os_dados_da_imagem_sao_os_do_repositorio(imagem: str) -> None:
    programa = (
        "import hashlib,json,pathlib;raiz=pathlib.Path('/app/sandbox/data/domrock');"
        "print(json.dumps({str(p.relative_to(raiz)): hashlib.sha256(p.read_bytes()).hexdigest()"
        " for p in sorted(raiz.rglob('*')) if p.is_file()}))"
    )

    na_imagem = dentro(imagem, programa)

    assert na_imagem == {
        nome: hashlib.sha256((RAIZ_DADOS / nome).read_bytes()).hexdigest()
        for nome in sorted(DADOS_DA_IMAGEM)
    }


# ---- orçamento ----


def test_nenhum_valor_de_orcamento_existe_dentro_da_imagem(imagem: str) -> None:
    processo = rodar(imagem, entrypoint="python", argumentos=["-"], entrada=VARREDURA.read_bytes())

    assert processo.returncode == 0, processo.stderr.decode()
    assert json.loads(processo.stdout) == []


def test_a_varredura_reconhece_orcamento_como_dado_e_como_simbolo(tmp_path: Path) -> None:
    """Controle negativo: sem ele, a varredura poderia estar sempre devolvendo vazio."""
    dados = tmp_path / "dados"
    codigo = tmp_path / "codigo"
    dados.mkdir()
    codigo.mkdir()
    (dados / "limpo.jsonl").write_text('{"comissao": 1.0}\n', encoding="utf-8")
    (dados / "sujo.jsonl").write_text('{"totais": {"orcamento": 485000.0}}\n', encoding="utf-8")
    (dados / "sujo.json").write_text('{"budget": 1}\n', encoding="utf-8")
    (codigo / "prosa.py").write_text(
        '"""O orçamento e o veredito não aparecem aqui."""\n# orçamento fica de fora\n',
        encoding="utf-8",
    )
    (codigo / "variavel.py").write_text("orcamento = 485000.0\n", encoding="utf-8")
    (codigo / "chave.py").write_text('x = {"orcamento": 1.0}\n', encoding="utf-8")
    (codigo / "argumento.py").write_text("def f(orcamento):\n    pass\n", encoding="utf-8")

    achados_dados = varrer_dados(dados)
    achados_codigo = varrer_codigo(codigo)

    assert len(achados_dados) == 2 and "limpo" not in " ".join(achados_dados)
    assert len(achados_codigo) == 3 and "prosa" not in " ".join(achados_codigo)
    assert varrer_ambiente({"SYNAPSE_ORCAMENTO": "1"}) and varrer_ambiente({"X": "budget=1"})
    assert varrer_ambiente({"PATH": "/usr/bin"}) == []


def test_o_payload_com_orcamento_e_recusado_pela_imagem(imagem: str) -> None:
    processo = rodar(imagem, entrada=bytes_do(payload(EXEMPLO, ("2025-11",), orcamento=485000.0)))

    assert processo.returncode == 1
    assert processo.stdout == b""
    assert b"orcamento" in processo.stderr and b"485000" not in processo.stderr
