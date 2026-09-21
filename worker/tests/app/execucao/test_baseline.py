"""Os baselines congelados que o worker mantém, e o que acontece quando não são os do manifesto.

O total que volta do container é conferido contra estes números (T-066). Um baseline que o
worker aceitasse adulterado faria a conferência confirmar o que devia denunciar, então cada
adulteração possível de um arquivo ou do manifesto tem de derrubar a carga.
"""

import hashlib
import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from app import main
from app.execucao import baseline
from app.execucao.baseline import (
    BaselineIndisponivelError,
    CompetenciaSemBaselineError,
    carregar_baselines,
    ler_baselines,
    localizar,
)

TOTAIS = {
    "2025-08": Decimal("363021.46"),
    "2025-09": Decimal("424628.68"),
    "2025-10": Decimal("698465.53"),
    "2025-11": Decimal("508382.32"),
    "2025-12": Decimal("1305396.25"),
}


def test_carrega_os_cinco_baselines_do_manifesto() -> None:
    assert dict(carregar_baselines().por_competencia) == TOTAIS


def test_o_total_do_periodo_e_a_soma_das_competencias() -> None:
    baselines = carregar_baselines()

    assert baselines.total(["2025-11"]) == Decimal("508382.32")
    assert baselines.total(["2025-08", "2025-11"]) == Decimal("871403.78")
    assert baselines.total(list(TOTAIS)) == sum(TOTAIS.values(), Decimal(0))


def test_competencia_sem_baseline_e_recusada() -> None:
    with pytest.raises(CompetenciaSemBaselineError, match="2026-01"):
        carregar_baselines().total(["2025-11", "2026-01"])


# ---- adulteração: cada uma derruba a carga ----


@pytest.fixture
def copia(tmp_path: Path) -> Path:
    destino = tmp_path / "baselines"
    shutil.copytree(localizar(), destino)
    return destino


def _reescrever(copia: Path, competencia: str, alterar: Any) -> None:
    """Regrava o baseline de uma competência com as linhas alteradas e **atualiza o sha256 do
    manifesto**, para que só a verificação sob teste possa reprová-lo."""
    manifesto = json.loads((copia / "manifesto.json").read_text(encoding="utf-8"))
    arquivo = copia / Path(manifesto["baselines"][competencia]["arquivo"]).name
    linhas = [json.loads(t) for t in arquivo.read_text(encoding="utf-8").splitlines() if t.strip()]
    linhas = alterar(linhas)
    conteudo = ("\n".join(json.dumps(linha) for linha in linhas) + "\n").encode("utf-8")
    arquivo.write_bytes(conteudo)
    manifesto["baselines"][competencia]["sha256"] = hashlib.sha256(conteudo).hexdigest()
    (copia / "manifesto.json").write_text(json.dumps(manifesto), encoding="utf-8")


def _primeira_matricula(linhas: list[dict[str, Any]]) -> dict[str, Any]:
    return next(linha for linha in linhas if linha["nivel"] == "matricula")


def test_a_copia_sem_alteracao_carrega(copia: Path) -> None:
    """Controle: a cópia é boa, então o que falha abaixo falha pela adulteração."""
    assert dict(ler_baselines(copia).por_competencia) == TOTAIS


def test_arquivo_alterado_sem_atualizar_o_manifesto(copia: Path) -> None:
    arquivo = copia / "baseline-2025-11.jsonl"
    arquivo.write_bytes(arquivo.read_bytes().replace(b"508382.32", b"508382.33", 1))

    with pytest.raises(BaselineIndisponivelError, match="sha256"):
        ler_baselines(copia)


def test_matricula_a_menos(copia: Path) -> None:
    def sem_a_ultima(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indice = max(i for i, linha in enumerate(linhas) if linha["nivel"] == "matricula")
        return linhas[:indice] + linhas[indice + 1 :]

    _reescrever(copia, "2025-11", sem_a_ultima)

    with pytest.raises(BaselineIndisponivelError, match="matrículas, o manifesto registra"):
        ler_baselines(copia)


def test_um_centavo_a_mais_numa_matricula(copia: Path) -> None:
    def mais_um_centavo(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _primeira_matricula(linhas)["comissao"] = round(
            _primeira_matricula(linhas)["comissao"] + 0.01, 2
        )
        return linhas

    _reescrever(copia, "2025-11", mais_um_centavo)

    with pytest.raises(BaselineIndisponivelError, match="somam"):
        ler_baselines(copia)


def test_comissao_com_fracao_de_centavo(copia: Path) -> None:
    def tres_casas(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _primeira_matricula(linhas)["comissao"] = 12.345
        return linhas

    _reescrever(copia, "2025-11", tres_casas)

    with pytest.raises(BaselineIndisponivelError, match="centavos"):
        ler_baselines(copia)


@pytest.mark.parametrize("valor", [None, "12.30", True, float("inf")], ids=str)
def test_comissao_que_nao_e_um_numero_finito(copia: Path, valor: object) -> None:
    def invalida(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _primeira_matricula(linhas)["comissao"] = valor
        return linhas

    _reescrever(copia, "2025-11", invalida)

    with pytest.raises(BaselineIndisponivelError, match="numérica|finita"):
        ler_baselines(copia)


def test_matricula_repetida(copia: Path) -> None:
    def duplicada(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [*linhas, dict(_primeira_matricula(linhas))]

    _reescrever(copia, "2025-11", duplicada)

    with pytest.raises(BaselineIndisponivelError, match="repetida"):
        ler_baselines(copia)


def test_linha_de_outra_competencia(copia: Path) -> None:
    def de_outro_mes(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _primeira_matricula(linhas)["competencia"] = "2025-10"
        return linhas

    _reescrever(copia, "2025-11", de_outro_mes)

    with pytest.raises(BaselineIndisponivelError, match="competência diferente"):
        ler_baselines(copia)


def test_arquivo_de_baseline_ausente(copia: Path) -> None:
    (copia / "baseline-2025-11.jsonl").unlink()

    with pytest.raises(BaselineIndisponivelError, match="ilegível"):
        ler_baselines(copia)


@pytest.mark.parametrize(
    "conteudo",
    ["{", "[]", '{"baselines": {}}', '{"baselines": {"2025-11": 1}}'],
    ids=["json invalido", "nao e objeto", "sem baselines", "registro invalido"],
)
def test_manifesto_invalido(copia: Path, conteudo: str) -> None:
    (copia / "manifesto.json").write_text(conteudo, encoding="utf-8")

    with pytest.raises(BaselineIndisponivelError):
        ler_baselines(copia)


def test_diretorio_sem_manifesto(tmp_path: Path) -> None:
    with pytest.raises(BaselineIndisponivelError, match="manifesto"):
        ler_baselines(tmp_path)


# ---- sem os arquivos, o worker não sobe ----


def test_sem_os_baselines_a_localizacao_falha_alto(tmp_path: Path) -> None:
    """Numa imagem montada sem os baselines, o processo tem de cair na subida, e não deixar o
    primeiro job descobrir. O módulo é copiado para uma árvore sem `sandbox/data` acima dele."""
    pasta = tmp_path / "app" / "execucao"
    pasta.mkdir(parents=True)
    (pasta / "baseline.py").write_text(Path(baseline.__file__).read_text(encoding="utf-8"))

    resultado = subprocess.run(
        [sys.executable, "-c", "import baseline; baseline.carregar_baselines()"],
        cwd=pasta,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert resultado.returncode != 0
    assert "BaselineIndisponivelError" in resultado.stderr


async def test_a_subida_do_worker_carrega_os_baselines_antes_de_ligar_o_consumidor(
    monkeypatch: pytest.MonkeyPatch, api: FastAPI
) -> None:
    conectar = AsyncMock()
    monkeypatch.setattr(main, "verificar_acesso", AsyncMock())
    monkeypatch.setattr(main, "carregar_contratos", lambda: None)
    monkeypatch.setattr(main, "conectar", conectar)
    monkeypatch.setattr(
        main,
        "carregar_baselines",
        lambda: (_ for _ in ()).throw(BaselineIndisponivelError("sem baselines")),
    )

    with pytest.raises(BaselineIndisponivelError):
        async with main.lifespan(api):
            pytest.fail("o worker não pode subir sem os baselines")

    conectar.assert_not_awaited()
