import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.sandbox.assercoes import TabelaApurada
from app.sandbox.regras_base import RegraBaseError
from app.sandbox.regras_competencia import apurar_vigente
from tests.app.sandbox.test_regras_base import evento, por_matricula, rh, taxa, venda


def politicas() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parents[3] / "sandbox/data/domrock/regras_competencia.jsonl"
    return [json.loads(linha) for linha in path.read_text(encoding="utf-8").splitlines()]


def test_agosto_substitui_percentual_e_soma_bonus_final_sem_mutar_entradas() -> None:
    pessoas = [rh("MATRIC-134", competencia="2025-08", cod_cargo=300)]
    vendas = [venda("MATRIC-134", 10000, competencia="2025-08")]
    taxas = [taxa(0.01, competencia="2025-08", cod_cargo=300)]
    anteriores = deepcopy((pessoas, vendas, taxas))
    resultado = apurar_vigente(pessoas, vendas, taxas, [], "2025-08", regras=politicas())
    assert por_matricula(resultado, "MATRIC-134")["comissao"] == 675.0
    assert (pessoas, vendas, taxas) == anteriores


def test_bonus_fixo_sem_venda_possui_origem_mensal_valida() -> None:
    resultado = apurar_vigente(
        [rh("MATRIC-134", competencia="2025-08")],
        [],
        [taxa(0.025, competencia="2025-08")],
        [],
        "2025-08",
        regras=politicas(),
    )
    assert isinstance(resultado, TabelaApurada)
    assert resultado[0]["comissao"] == 500.0
    assert resultado.resultado_apuracao["assercoes"][1]["resultado"] == "ok"


def test_setembro_bonus_de_base_usa_taxa_emprestada_e_nao_inventa_venda_da_loja() -> None:
    resultado = apurar_vigente(
        [
            rh("MATRIC-227", competencia="2025-09"),
            rh("GERENTE", competencia="2025-09", cod_cargo=150),
        ],
        [venda("MATRIC-227", 10000, competencia="2025-09")],
        [
            taxa(0.01, competencia="2025-09"),
            taxa(0.03, competencia="2025-09", cod_marca=20),
            taxa(0.005, competencia="2025-09", cod_cargo=150),
            taxa(0.02, competencia="2025-09", cod_marca=20, cod_cargo=150),
        ],
        [],
        "2025-09",
        regras=politicas(),
    )
    assert por_matricula(resultado, "MATRIC-227")["comissao"] == 900.0
    assert por_matricula(resultado, "MATRIC-227")["base_calculo"] == 30000.0
    assert por_matricula(resultado, "GERENTE")["comissao"] == 200.0


def test_setembro_bonus_na_base_sofre_proporcao_de_admissao() -> None:
    resultado = apurar_vigente(
        [rh("MATRIC-227", competencia="2025-09", data_admiss="2025-09-15")],
        [venda("MATRIC-227", 10000, competencia="2025-09")],
        [taxa(0.01, competencia="2025-09"), taxa(0.03, competencia="2025-09", cod_marca=20)],
        [],
        "2025-09",
        regras=politicas(),
    )
    assert por_matricula(resultado, "MATRIC-227")["comissao"] == 450.0


@pytest.mark.parametrize(
    "admissao,esperado",
    [
        ("2020-01-01", 1300.0),
        ("2025-10-10", 1203.23),
        ("2025-10-11", 193.55),
    ],
)
def test_outubro_admissao_ate_dia_dez_inclui_antigos_e_bonus_e_final(
    admissao: str,
    esperado: float,
) -> None:
    resultado = apurar_vigente(
        [rh("A", competencia="2025-10", cod_marca=30, data_admiss=admissao)],
        [venda("A", 10000, competencia="2025-10", cod_marca=30)],
        [taxa(0.025, competencia="2025-10", cod_marca=30)],
        [],
        "2025-10",
        regras=politicas(),
    )
    assert por_matricula(resultado, "A")["comissao"] == esperado


def test_outubro_exclui_gerente_do_adicional_de_percentual() -> None:
    resultado = apurar_vigente(
        [rh("G", competencia="2025-10", cod_marca=30, cod_cargo=150)],
        [venda("G", 10000, competencia="2025-10", cod_marca=30)],
        [taxa(0.01, competencia="2025-10", cod_marca=30, cod_cargo=150)],
        [],
        "2025-10",
        regras=politicas(),
    )
    assert por_matricula(resultado, "G")["comissao"] == 100.0


def test_black_friday_usa_data_real_inclusiva_e_total_loja_para_gerente() -> None:
    vendas = [
        {**venda("A", 1000), "data_venda": "2025-11-23"},
        {**venda("A", 2000), "data_venda": "2025-11-24"},
        {**venda("A", 3000), "data_venda": "2025-11-30"},
        {**venda("A", 4000), "data_ref": "2025-11-27"},
    ]
    resultado = apurar_vigente(
        [rh("A"), rh("G", cod_cargo=150)],
        vendas,
        [taxa(0.02), taxa(0.01, cod_cargo=150)],
        [],
        "2025-11",
        regras=politicas(),
    )
    assert por_matricula(resultado, "A")["comissao"] == 250.0  # 200 + 50
    assert por_matricula(resultado, "G")["comissao"] == 125.0  # 100 + 25


def test_black_friday_sofre_proporcoes_e_nao_e_somada_depois_do_piso() -> None:
    resultado = apurar_vigente(
        [rh("A")],
        [{**venda("A", 20000), "data_venda": "2025-11-24"}],
        [taxa(0.025)],
        [evento("E", "afastamento", "A", "2025-11-01", "2025-11-10")],
        "2025-11",
        regras=politicas(),
    )
    assert por_matricula(resultado, "A")["comissao"] == 3500.0


def test_arredondamento_ocorre_uma_vez_apos_somar_adicional() -> None:
    resultado = apurar_vigente(
        [rh("A")],
        [{**venda("A", 0.4), "data_venda": "2025-11-24"}],
        [taxa(0.01)],
        [],
        "2025-11",
        regras=politicas(),
    )
    assert por_matricula(resultado, "A")["comissao"] == 0.01  # 0.004 + 0.004


@pytest.mark.parametrize(
    "base,bonus",
    [
        (40000, 0),
        (40000.01, 3500),
        (50000, 3500),
        (50000.01, 4000),
        (60000, 4000),
        (60000.01, 4500),
    ],
)
def test_dezembro_faixas_individuais_sao_continuas_e_usam_soma_mensal(
    base: float,
    bonus: float,
) -> None:
    resultado = apurar_vigente(
        [rh("A", competencia="2025-12")],
        [venda("A", base / 2, competencia="2025-12"), venda("A", base / 2, competencia="2025-12")],
        [taxa(0, competencia="2025-12")],
        [],
        "2025-12",
        regras=politicas(),
    )
    assert por_matricula(resultado, "A")["comissao"] == bonus


@pytest.mark.parametrize(
    "base,bonus",
    [
        (120000, 0),
        (120000.01, 5000),
        (140000, 5000),
        (140000.01, 6000),
        (160000, 6000),
        (160000.01, 7000),
    ],
)
def test_dezembro_faixas_do_gerente_usam_total_loja(base: float, bonus: float) -> None:
    resultado = apurar_vigente(
        [
            rh("A", competencia="2025-12", cod_marca=40),
            rh("G", competencia="2025-12", cod_marca=40, cod_cargo=150),
        ],
        [venda("A", base, competencia="2025-12", cod_marca=40)],
        [
            taxa(0, competencia="2025-12", cod_marca=40),
            taxa(0, competencia="2025-12", cod_marca=40, cod_cargo=150),
        ],
        [],
        "2025-12",
        regras=politicas(),
    )
    assert por_matricula(resultado, "G")["comissao"] == bonus


@pytest.mark.parametrize(
    "marca,cargo,esperado",
    [
        (30, 100, 250),
        (40, 100, 300),
        (50, 200, 300),
        (60, 300, 300),
        (40, 150, 200),
        (10, 100, 200),
        (20, 100, 200),
    ],
)
def test_dezembro_adicionais_seguem_marca_e_exclusao_de_cargo(
    marca: int,
    cargo: int,
    esperado: float,
) -> None:
    resultado = apurar_vigente(
        [rh("A", competencia="2025-12", cod_marca=marca, cod_cargo=cargo)],
        [venda("A", 10000, competencia="2025-12", cod_marca=marca)],
        [taxa(0.02, competencia="2025-12", cod_marca=marca, cod_cargo=cargo)],
        [],
        "2025-12",
        regras=politicas(),
    )
    assert por_matricula(resultado, "A")["comissao"] == esperado


def test_dezembro_gerente_pode_acumular_bonus_proprio_e_da_loja() -> None:
    resultado = apurar_vigente(
        [rh("G", competencia="2025-12", cod_cargo=150)],
        [venda("G", 130000, competencia="2025-12")],
        [taxa(0, competencia="2025-12", cod_cargo=150)],
        [],
        "2025-12",
        regras=politicas(),
    )
    assert por_matricula(resultado, "G")["comissao"] == 9500.0


def test_julho_nao_ganha_baseline_silenciosamente() -> None:
    with pytest.raises(RegraBaseError, match="sem política histórica"):
        apurar_vigente([], [], [], [], "2025-07", regras=politicas())
