"""As bases da apuração que o worker mantém, e a reapuração do baseline na meta sobre elas (T-270).

O total que o worker reapura confere o baseline que volta do container numa execução na meta, e
``vendas_historicas`` sai daqui para toda execução com sucesso. Bases adulteradas fariam a
conferência confirmar o que devia denunciar, então cada arquivo é conferido contra o sha256 do
manifesto, e qualquer divergência derruba a carga.
"""

import json
import shutil
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from app import main
from app.execucao.baseline import CompetenciaSemBaselineError, carregar_baselines, localizar
from app.execucao.bases import (
    ARQUIVOS,
    BasesDoWorker,
    BasesIndisponiveisError,
    ReapuracaoNaMetaError,
    carregar_bases,
    ler_bases,
)

COMPETENCIAS = ("2025-08", "2025-09", "2025-10", "2025-11", "2025-12")
VENDAS_2025_11 = Decimal("13271681.51")


# ---- o total de vendas ----


def test_vendas_historicas_e_a_soma_das_vendas_das_competencias_em_centavos() -> None:
    bases = carregar_bases()

    assert bases.vendas_historicas(["2025-11"]) == VENDAS_2025_11
    # O mesmo valor do exemplo do contrato (resultado-totais-meta-venda.json).
    assert bases.vendas_historicas(["2025-08", "2025-11"]) == Decimal("23583194.87")


def test_vendas_historicas_de_competencia_fora_das_bases_e_recusada() -> None:
    with pytest.raises(CompetenciaSemBaselineError, match="2026-01"):
        carregar_bases().vendas_historicas(["2025-11", "2026-01"])


# ---- o baseline na meta ----


@pytest.mark.parametrize(
    "competencias", [[c] for c in COMPETENCIAS] + [list(COMPETENCIAS)], ids=[*COMPETENCIAS, "todas"]
)
def test_meta_igual_ao_total_historico_reapura_o_baseline_congelado(
    competencias: list[str],
) -> None:
    """Fator 1: a reapuração do worker reproduz o total congelado, centavo a centavo."""
    bases = carregar_bases()
    meta = float(bases.vendas_historicas(competencias))

    assert bases.baseline_na_meta(competencias, meta) == carregar_baselines().total(competencias)


def test_meta_acima_do_total_historico_reapura_sobre_as_vendas_escaladas() -> None:
    total = carregar_bases().baseline_na_meta(["2025-11"], float(VENDAS_2025_11 * Decimal("1.1")))

    assert total == Decimal("558870.26")


def test_a_reapuracao_nao_altera_as_bases_do_worker() -> None:
    bases = carregar_bases()
    antes = json.dumps([bases.rh, bases.vendas, bases.comissoes, bases.eventos_rh, bases.regras])

    bases.baseline_na_meta(["2025-11"], 20000000.0)

    assert json.dumps(
        [bases.rh, bases.vendas, bases.comissoes, bases.eventos_rh, bases.regras]
    ) == (antes)


@pytest.mark.parametrize(
    "competencias", [["2026-01"], ["2025-11", "2025-11"], []], ids=["fora", "repetida", "vazia"]
)
def test_periodo_fora_das_bases_nao_e_reapurado(competencias: list[str]) -> None:
    with pytest.raises(ReapuracaoNaMetaError, match="CompetenciaSemBaselineError"):
        carregar_bases().baseline_na_meta(competencias, 1000.0)


def test_periodo_sem_vendas_nao_e_reapurado() -> None:
    """A falha sai só com a classe: a mensagem do motor pode citar matrícula ou valor."""
    bases = BasesDoWorker(
        competencias=frozenset({"2025-11"}),
        rh=(),
        vendas=(),
        comissoes=(),
        eventos_rh=(),
        regras=(),
    )

    with pytest.raises(ReapuracaoNaMetaError) as erro:
        bases.baseline_na_meta(["2025-11"], 1000.0)

    assert str(erro.value) == "MetaVendaError"


# ---- adulteração: cada uma derruba a carga ----


@pytest.fixture
def copia(tmp_path: Path) -> Path:
    destino = tmp_path / "domrock"
    origem = localizar().parent
    shutil.copytree(origem / "baselines", destino / "baselines")
    for nome in ARQUIVOS:
        shutil.copy(origem / nome, destino / nome)
    return destino


def test_a_copia_sem_alteracao_carrega(copia: Path) -> None:
    """Controle: a cópia é boa, então o que falha abaixo falha pela adulteração."""
    bases = ler_bases(copia)

    assert bases.competencias == frozenset(COMPETENCIAS)
    assert bases.vendas_historicas(["2025-11"]) == VENDAS_2025_11


@pytest.mark.parametrize("nome", ARQUIVOS)
def test_base_alterada_sem_atualizar_o_manifesto(copia: Path, nome: str) -> None:
    arquivo = copia / nome
    arquivo.write_bytes(arquivo.read_bytes() + b"\n")

    with pytest.raises(BasesIndisponiveisError, match=f"{nome} difere do sha256"):
        ler_bases(copia)


@pytest.mark.parametrize("nome", ARQUIVOS)
def test_base_ausente(copia: Path, nome: str) -> None:
    (copia / nome).unlink()

    with pytest.raises(BasesIndisponiveisError, match=f"{nome} ilegível"):
        ler_bases(copia)


@pytest.mark.parametrize("chave", ["fontes_sha256", "baselines"])
def test_manifesto_sem_as_fontes_ou_os_baselines(copia: Path, chave: str) -> None:
    caminho = copia / "baselines" / "manifesto.json"
    manifesto = json.loads(caminho.read_text(encoding="utf-8"))
    del manifesto[chave]
    caminho.write_text(json.dumps(manifesto), encoding="utf-8")

    with pytest.raises(BasesIndisponiveisError, match="manifesto"):
        ler_bases(copia)


def test_diretorio_sem_manifesto(tmp_path: Path) -> None:
    with pytest.raises(BasesIndisponiveisError, match="manifesto"):
        ler_bases(tmp_path)


# ---- sem as bases, o worker não sobe ----


async def test_a_subida_do_worker_carrega_as_bases_antes_de_ligar_o_consumidor(
    monkeypatch: pytest.MonkeyPatch, api: FastAPI
) -> None:
    conectar = AsyncMock()
    monkeypatch.setattr(main, "verificar_acesso", AsyncMock())
    monkeypatch.setattr(main, "carregar_contratos", lambda: None)
    monkeypatch.setattr(main, "carregar_baselines", lambda: None)
    monkeypatch.setattr(main, "conectar", conectar)
    monkeypatch.setattr(
        main,
        "carregar_bases",
        lambda: (_ for _ in ()).throw(BasesIndisponiveisError("sem as bases")),
    )

    with pytest.raises(BasesIndisponiveisError):
        async with main.lifespan(api):
            pytest.fail("o worker não pode subir sem as bases")

    conectar.assert_not_awaited()
