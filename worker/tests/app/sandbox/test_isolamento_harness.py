"""O ``exec`` de código gerado não pode ser alcançável pelo processo do worker.

``worker/AGENTS.md``: nenhum caminho de código do worker importa, executa ou avalia uma
regra gerada fora do container efêmero. O ``worker/Dockerfile`` copia ``worker/app``
inteiro, então ``harness.py`` e ``executor.py`` estão fisicamente na imagem do processo
worker; o que os mantém inertes ali é que nada os importa. Este arquivo é o que garante
isso, e também que a imagem do sandbox só leva o que deveria.
"""

import ast
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.app.sandbox.imagem import (
    MODULOS_DA_IMAGEM,
    MODULOS_PROIBIDOS,
    MODULOS_SO_STDLIB,
)

WORKER = Path(__file__).resolve().parents[3]
SANDBOX = WORKER / "app" / "sandbox"
PONTOS_DE_ENTRADA_DO_WORKER = (WORKER / "run.py", WORKER / "app" / "main.py")

# O que executa código gerado, e o que arrasta pandas para um processo que não o tem.
PROIBIDOS_NO_WORKER = frozenset(
    {"app.sandbox.harness", "app.sandbox.executor", "app.sandbox.carga"}
)


def importados(arquivo: Path) -> set[str]:
    """Nomes de módulo importados em qualquer ponto do arquivo, inclusive dentro de função."""
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            nomes.add(no.module)
            # `from app.sandbox import daemon` importa o submódulo app.sandbox.daemon.
            nomes.update(f"{no.module}.{alias.name}" for alias in no.names)
    return nomes


def arquivo_do_modulo(nome: str) -> Path | None:
    base = WORKER.joinpath(*nome.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def fecho_de_imports(partida: Iterable[Path]) -> set[str]:
    """Módulos ``app.*`` alcançáveis por import estático a partir dos arquivos dados."""
    alcancados: set[str] = set()
    pendentes = list(partida)
    vistos: set[Path] = set()
    while pendentes:
        arquivo = pendentes.pop()
        if arquivo in vistos:
            continue
        vistos.add(arquivo)
        for nome in importados(arquivo):
            if nome != "app" and not nome.startswith("app."):
                continue
            partes = nome.split(".")
            # Importar a.b.c também importa a e a.b.
            for tamanho in range(1, len(partes) + 1):
                pai = ".".join(partes[:tamanho])
                alvo = arquivo_do_modulo(pai)
                if alvo is not None:
                    alcancados.add(pai)
                    pendentes.append(alvo)
    return alcancados


# ---- o processo do worker ----


def test_o_percurso_de_imports_enxerga_o_que_o_worker_importa() -> None:
    """Controle: sem ele, um percurso quebrado devolveria vazio e o teste abaixo passaria."""
    alcancados = fecho_de_imports(PONTOS_DE_ENTRADA_DO_WORKER)

    # app.main é ponto de partida, não algo que alguém importa: o que conta é o que ele puxa.
    assert {"app.sandbox.daemon", "app.mensageria.consumidor"} <= alcancados


def test_o_percurso_de_imports_enxerga_o_harness_quando_ele_e_alcancavel() -> None:
    assert "app.sandbox.harness" in fecho_de_imports([SANDBOX / "executor.py"])


def test_processo_do_worker_nao_alcanca_o_harness_por_import_estatico() -> None:
    alcancados = fecho_de_imports(PONTOS_DE_ENTRADA_DO_WORKER)

    assert alcancados & PROIBIDOS_NO_WORKER == set(), (
        "o processo do worker alcança o módulo que executa código gerado; "
        "worker/AGENTS.md proíbe isso fora do container efêmero"
    )


def test_processo_do_worker_nao_carrega_o_harness_nem_pandas_em_runtime() -> None:
    """Pega o que o percurso estático não vê, como um import dinâmico."""
    programa = (
        "import json, sys\n"
        "import app.main\n"
        "print(json.dumps({'sandbox': sorted(m for m in sys.modules "
        "if m.startswith('app.sandbox')), 'pandas': 'pandas' in sys.modules}))\n"
    )

    processo = subprocess.run(
        [sys.executable, "-c", programa],
        capture_output=True,
        text=True,
        cwd=WORKER,
        check=False,
        timeout=120,
    )

    assert processo.returncode == 0, processo.stderr
    carregado = json.loads(processo.stdout)
    assert set(carregado["sandbox"]) & PROIBIDOS_NO_WORKER == set()
    assert carregado["pandas"] is False


# ---- o que a imagem do sandbox carrega ----


def test_o_envelope_pode_ser_importado_pelo_worker_sem_arrastar_o_harness() -> None:
    """A T-064 vai importar o envelope do lado do worker. Ele só pode depender de módulos
    que são dados e aritmética."""
    alcancados = fecho_de_imports([SANDBOX / "envelope.py"])

    assert alcancados & PROIBIDOS_NO_WORKER == set()


@pytest.mark.parametrize("modulo", sorted(MODULOS_DA_IMAGEM))
def test_modulo_da_imagem_so_importa_stdlib_pandas_e_irmaos_da_imagem(modulo: str) -> None:
    permitidos_internos = {
        f"app.sandbox.{nome.removesuffix('.py')}"
        for nome in MODULOS_DA_IMAGEM
        if nome != "__init__.py"
    } | {"app", "app.sandbox"}

    for nome in importados(SANDBOX / modulo):
        raiz = nome.split(".")[0]
        if raiz == "app":
            # `from app.sandbox.x import y` também registra `app.sandbox.x.y`, que só
            # existe como nome importado; interessa o módulo, não o atributo.
            assert any(nome == p or nome.startswith(p + ".") for p in permitidos_internos), nome
            assert not any(
                nome == f"app.sandbox.{proibido.removesuffix('.py')}"
                for proibido in MODULOS_PROIBIDOS
            ), nome
        else:
            assert raiz in sys.stdlib_module_names or raiz == "pandas", nome


@pytest.mark.parametrize("modulo", sorted(MODULOS_SO_STDLIB))
def test_modulo_de_dados_e_aritmetica_nao_importa_pandas(modulo: str) -> None:
    assert not any(nome.split(".")[0] == "pandas" for nome in importados(SANDBOX / modulo))


def test_so_carga_e_harness_importam_pandas() -> None:
    com_pandas = {
        arquivo.name
        for arquivo in SANDBOX.glob("*.py")
        if any(nome.split(".")[0] == "pandas" for nome in importados(arquivo))
    }

    assert com_pandas == {"carga.py", "harness.py"}
