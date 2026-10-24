"""A conferência de escopo: fora do alcance da regra, a comissão simulada é a do baseline."""

from typing import Any

import pytest

from app.execucao.escopo import EXEMPLOS, conferir_escopo
from app.mensageria.contracts import AlcanceDaRegra
from app.sandbox.resultado import LinhaDetalhada


def linha(
    loja: str = "13",
    marca: str = "10",
    cargo: str = "100",
    *,
    baseline: float = 1000.0,
    simulada: float = 1000.0,
) -> LinhaDetalhada:
    return LinhaDetalhada(
        cod_loja=loja,
        cod_marca=marca,
        cod_cargo=cargo,
        comissao_baseline=baseline,
        comissao_simulada=simulada,
        diferenca=simulada - baseline,
        contribuicoes={"elem.1": simulada - baseline} if simulada != baseline else {},
    )


def alcance(**campos: Any) -> AlcanceDaRegra:
    return AlcanceDaRegra.model_validate(campos)


@pytest.mark.parametrize(
    ("restricao", "fora"),
    [
        ({"loja": ["13"]}, linha(loja="33", simulada=1350.0)),
        ({"marca": ["10"]}, linha(marca="20", simulada=1350.0)),
        ({"cargo": ["100"]}, linha(cargo="150", simulada=1350.0)),
        ({"excluidos": {"loja": ["58"]}}, linha(loja="58", simulada=1350.0)),
    ],
    ids=["loja", "marca", "cargo", "exclusao"],
)
def test_linha_fora_do_alcance_com_a_comissao_mudada_e_reprovada(
    restricao: dict[str, Any], fora: LinhaDetalhada
) -> None:
    linhas = {"2025-11": {"MATRIC-1": linha(simulada=1200.0), "MATRIC-2": fora}}

    resultado = conferir_escopo(alcance(**restricao), linhas)

    assert resultado is not None
    assert resultado.total == 1
    assert resultado.exemplos == (
        {
            "competencia": "2025-11",
            "matricula": "MATRIC-2",
            "cod_loja": fora["cod_loja"],
            "cod_marca": fora["cod_marca"],
            "cod_cargo": fora["cod_cargo"],
            "diferenca": 350.0,
        },
    )


def test_competencia_fora_da_vigencia_conserva_o_baseline() -> None:
    linhas = {
        "2025-08": {"MATRIC-1": linha(simulada=1350.0)},
        "2025-11": {"MATRIC-1": linha(simulada=1350.0)},
    }

    resultado = conferir_escopo(alcance(vigencia={"inicio": "2025-09", "fim": "2025-11"}), linhas)

    assert resultado is not None
    assert [exemplo["competencia"] for exemplo in resultado.exemplos] == ["2025-08"]


def test_mudanca_dentro_do_alcance_e_a_regra_e_nao_reprova() -> None:
    linhas = {"2025-11": {"MATRIC-1": linha(simulada=1350.0), "MATRIC-2": linha(loja="33")}}

    assert conferir_escopo(alcance(loja=["13"]), linhas) is None


@pytest.mark.parametrize(
    ("simulada", "reprova"), [(1000.01, False), (999.99, False), (1000.02, True)]
)
def test_a_tolerancia_e_de_um_centavo(simulada: float, reprova: bool) -> None:
    """O código que reapura a linha do baseline pode arredondar de outro jeito."""
    linhas = {"2025-11": {"MATRIC-1": linha(loja="33", simulada=simulada)}}

    resultado = conferir_escopo(alcance(loja=["13"]), linhas)

    assert (resultado is not None) is reprova


def test_o_total_conta_todas_e_os_exemplos_sao_as_primeiras() -> None:
    linhas = {
        "2025-11": {f"MATRIC-{n}": linha(loja="33", simulada=1350.0) for n in range(1, 9)},
    }

    resultado = conferir_escopo(alcance(loja=["13"]), linhas)

    assert resultado is not None
    assert resultado.total == 8
    assert [e["matricula"] for e in resultado.exemplos] == [
        f"MATRIC-{n}" for n in range(1, EXEMPLOS + 1)
    ]


def test_o_repr_nao_leva_as_linhas_do_container() -> None:
    linhas = {"2025-11": {"MATRIC-PRIVADA": linha(loja="33", simulada=1350.0)}}

    resultado = conferir_escopo(alcance(loja=["13"]), linhas)

    assert "MATRIC-PRIVADA" not in repr(resultado)
