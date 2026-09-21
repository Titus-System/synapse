"""A imagem do sandbox, lida pelo Dockerfile e pelos pins, sem precisar de Docker.

Roda no gate em qualquer máquina. Os testes com Docker conferem a imagem construída; estes
conferem que a receita dela diz o que deveria, e que os pins não divergem do ambiente de
teste, porque um número calculado com uma versão de pandas na imagem e outra aqui seria
um bug impossível de depurar.
"""

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

from tests.app.sandbox.imagem import (
    DADOS_DA_IMAGEM,
    DADOS_PROIBIDOS,
    DISTRIBUICOES_PERMITIDAS,
    MODULOS_DA_IMAGEM,
    MODULOS_PROIBIDOS,
)

WORKER = Path(__file__).resolve().parents[3]
DOCKERFILE = (WORKER / "sandbox" / "Dockerfile").read_text(encoding="utf-8")
REQUISITOS = WORKER / "sandbox" / "requirements.txt"
LOCK = WORKER / "poetry.lock"
CONTRATO_DO_HARNESS = WORKER.parent / "contracts" / "harness" / "requirements.txt"


def copias_do_dockerfile() -> list[tuple[str, ...]]:
    """Fontes de cada ``COPY`` (menos os de outro estágio), com as continuações unidas."""
    texto = re.sub(r"\\\n\s*", " ", DOCKERFILE)
    copias = []
    for linha in texto.splitlines():
        if not linha.startswith("COPY ") or "--from=" in linha:
            continue
        argumentos = [a for a in linha.split()[1:] if not a.startswith("--")]
        copias.append(tuple(argumentos[:-1]))  # o último é o destino
    return copias


def fontes_copiadas() -> set[str]:
    return {fonte for copia in copias_do_dockerfile() for fonte in copia}


def pins_da_imagem() -> dict[str, str]:
    pins = {}
    for linha in REQUISITOS.read_text(encoding="utf-8").splitlines():
        if linha.strip() and not linha.startswith("#"):
            requisito = Requirement(linha)
            (especificador,) = requisito.specifier
            assert especificador.operator == "==", f"{linha} não está pinada em versão exata"
            pins[requisito.name] = especificador.version
    return pins


def test_dockerfile_copia_exatamente_a_lista_branca_de_codigo_e_dados() -> None:
    esperado = (
        {"worker/sandbox/requirements.txt", "worker/app/__init__.py"}
        | {f"worker/app/sandbox/{nome}" for nome in MODULOS_DA_IMAGEM}
        | {f"worker/sandbox/data/domrock/{nome}" for nome in DADOS_DA_IMAGEM}
    )

    assert fontes_copiadas() == esperado


def test_dockerfile_nao_copia_diretorio_inteiro() -> None:
    """Lista branca, um arquivo por linha: diretório copiado inteiro arrastaria o que
    alguém adicionar ali depois sem que ninguém decidisse."""
    for fonte in fontes_copiadas():
        assert not fonte.endswith("/") and Path(fonte).suffix, fonte


def test_dockerfile_deixa_de_fora_o_que_nao_deve_estar_na_imagem() -> None:
    fontes = fontes_copiadas()

    for nome in MODULOS_PROIBIDOS:
        assert f"worker/app/sandbox/{nome}" not in fontes
    for nome in DADOS_PROIBIDOS:
        assert f"worker/sandbox/data/domrock/{nome}" not in fontes
    assert not any(fonte.startswith("contracts") for fonte in fontes)


def test_dockerfile_roda_como_usuario_sem_privilegio_e_sem_shell_no_entrypoint() -> None:
    linhas = [linha.strip() for linha in DOCKERFILE.splitlines()]
    usuarios = [linha for linha in linhas if linha.startswith("USER ")]

    assert usuarios[-1] == "USER appuser"
    assert 'ENTRYPOINT ["python", "-m", "app.sandbox.executor"]' in linhas
    for proibida in ("VOLUME", "EXPOSE", "HEALTHCHECK"):
        assert not any(linha.startswith(proibida) for linha in linhas), proibida


def test_arquivos_copiados_sao_somente_leitura_e_os_diretorios_ja_existem() -> None:
    """`--chmod` num COPY vale também para os diretórios que ele cria, e com 0444 eles perdem
    o bit de execução e ficam intraversáveis. Por isso os diretórios são criados antes."""
    texto = re.sub(r"\\\n\s*", " ", DOCKERFILE)
    copias = [
        linha
        for linha in texto.splitlines()
        if linha.startswith("COPY ") and "--from=" not in linha
    ]
    do_codigo_e_dos_dados = [linha for linha in copias if "requirements.txt" not in linha]

    assert do_codigo_e_dos_dados and all("--chmod=0444" in linha for linha in do_codigo_e_dos_dados)
    assert "mkdir -p /app/app/sandbox /app/sandbox/data/domrock/baselines" in texto
    assert "chmod -R" not in texto, "chmod recursivo duplica o venv numa camada nova (149 MB)"


def test_pins_da_imagem_sao_exatamente_as_distribuicoes_permitidas() -> None:
    assert set(pins_da_imagem()) == set(DISTRIBUICOES_PERMITIDAS)


def test_pins_da_imagem_sao_os_do_ambiente_de_teste() -> None:
    """Mesma versão dos dois lados: o número que o teste confere e o que a imagem calcula
    passam pela mesma aritmética de ponto flutuante."""
    with LOCK.open("rb") as arquivo:
        no_lock = {p["name"]: p["version"] for p in tomllib.load(arquivo)["package"]}

    assert {nome: no_lock[nome] for nome in pins_da_imagem()} == pins_da_imagem()


def test_pandas_da_imagem_respeita_a_faixa_que_o_contrato_da_t034_permite() -> None:
    (linha,) = [
        linha
        for linha in CONTRATO_DO_HARNESS.read_text(encoding="utf-8").splitlines()
        if linha.startswith("pandas")
    ]
    faixa = SpecifierSet(Requirement(linha).specifier)

    assert pins_da_imagem()["pandas"] in faixa
