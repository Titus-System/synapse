"""Detalhamento e quebras absolutas usam as mesmas parcelas em centavos (T-259)."""

from decimal import Decimal

import pytest

from app.sandbox.resultado import montar_resultado
from tests.app.esquemas import erros_do_dominio
from tests.app.sandbox.test_resultado import (
    assercoes_ok,
    com_comissao,
    contribuicao,
    linha_base,
    soma,
)


def montar_cenario():
    base = [
        linha_base("MATRIC-1", competencia="2025-08", cod_loja=13, comissao=100.0),
        linha_base("MATRIC-1", competencia="2025-11", cod_loja=58, comissao=200.0),
        linha_base("MATRIC-2", competencia="2025-11", cod_loja=13, comissao=50.0),
    ]
    return montar_resultado(
        {
            "apuracao_simulada": [com_comissao(base[0], 130.01), base[1], base[2]],
            "contribuicoes": [
                contribuicao(competencia="2025-08", elemento_ref="elem.1", delta=15.005),
                contribuicao(competencia="2025-08", elemento_ref="elem.2", delta=15.005),
            ],
        },
        base,
        ["2025-08", "2025-11"],
        assercoes=assercoes_ok(),
    )


@pytest.mark.parametrize("quebra", ["matricula", "loja_absoluto", "competencia_absoluto"])
def test_quebra_absoluta_soma_o_total_simulado(quebra: str) -> None:
    montado = montar_cenario()

    assert soma(montado.resultado["decomposicao"][quebra]) == Decimal("380.01")
    assert montado.resultado["totais"]["simulado"] == 380.01
    assert erros_do_dominio("resultado-decomposicao", montado.resultado["decomposicao"]) == []


def test_transferencia_conta_na_loja_de_cada_mes() -> None:
    montado = montar_cenario()

    assert montado.resultado["decomposicao"]["loja_absoluto"] == {"13": 180.01, "58": 200.0}
    assert montado.resultado["decomposicao"]["matricula"] == {"MATRIC-1": 330.01, "MATRIC-2": 50.0}


def test_detalhamento_inclui_inalterados_e_reparte_o_residuo_como_a_decomposicao() -> None:
    montado = montar_cenario()
    linhas = montado.linhas

    assert set(linhas) == {"2025-08", "2025-11"}
    assert set(linhas["2025-08"]) == {"MATRIC-1"}
    assert set(linhas["2025-11"]) == {"MATRIC-1", "MATRIC-2"}
    assert linhas["2025-08"]["MATRIC-1"] == {
        "cod_loja": "13",
        "cod_marca": "10",
        "cod_cargo": "100",
        "comissao_baseline": 100.0,
        "comissao_simulada": 130.01,
        "diferenca": 30.01,
        "contribuicoes": {"elem.1": 15.0, "elem.2": 15.01},
    }
    for linha in linhas["2025-11"].values():
        assert linha["diferenca"] == 0
        assert linha["contribuicoes"] == {}
    assert erros_do_dominio("resultado-linhas", linhas) == []
    assert "linhas" not in montado.resultado
    total = Decimal(0)
    for mes in linhas.values():
        for linha in mes.values():
            simulado = Decimal(str(linha["comissao_simulada"]))
            diferenca = Decimal(str(linha["diferenca"]))
            total += simulado
            assert diferenca == simulado - Decimal(str(linha["comissao_baseline"]))
            assert soma(linha["contribuicoes"]) == diferenca
    assert total == Decimal(str(montado.resultado["totais"]["simulado"]))


def test_contribuicoes_agrupadas_excluem_zero_e_preservam_negativos() -> None:
    base = [linha_base(comissao=100.0)]
    montado = montar_resultado(
        {
            "apuracao_simulada": [com_comissao(base[0], 90.0)],
            "contribuicoes": [
                contribuicao(elemento_ref="elem.1", delta=3.0),
                contribuicao(elemento_ref="elem.1", delta=-3.0),
                contribuicao(elemento_ref="elem.2", delta=-10.0),
            ],
        },
        base,
        ["2025-08", "2025-11"],
        assercoes=assercoes_ok(),
    )

    assert montado.linhas["2025-08"] == {}
    assert montado.linhas["2025-11"]["MATRIC-1"]["contribuicoes"] == {"elem.2": -10.0}
    assert montado.resultado["decomposicao"]["elemento"] == {"elem.1": 0.0, "elem.2": -10.0}
    assert montado.resultado["decomposicao"]["competencia_absoluto"] == {
        "2025-08": 0.0,
        "2025-11": 90.0,
    }


def test_periodo_inteiro_cabe_no_stdout_com_ao_menos_vinte_por_cento_de_folga() -> None:
    from app.execucao.container import Limites
    from app.sandbox.envelope import serializar
    from tests.app.sandbox.detalhamento import baseline_do_periodo, envelope_do_periodo

    envelope = envelope_do_periodo()
    bruto = serializar(envelope).encode("utf-8") + b"\n"
    linhas = envelope["linhas"]
    resultado = envelope["resultado"]
    assert linhas is not None and resultado is not None
    base = baseline_do_periodo()

    assert len(bruto) < Limites().teto_stdout * 0.8
    assert sum(len(mes) for mes in linhas.values()) == len(base)
    for original in base:
        linha = linhas[original["competencia"]][original["matricula"]]
        assert linha["comissao_baseline"] == original["comissao"]
        assert Decimal(str(linha["comissao_simulada"])) == Decimal(str(original["comissao"])) + 3
        assert linha["contribuicoes"] == {"elem.1": 1.0, "elem.2": 1.0, "elem.3": 1.0}
    assert erros_do_dominio("resultado-linhas", linhas) == []
    for quebra in ("matricula", "loja_absoluto", "competencia_absoluto"):
        assert soma(resultado["decomposicao"][quebra]) == Decimal(
            str(resultado["totais"]["simulado"])
        )


def test_matric_422_tem_uma_entrada_com_a_lotacao_do_baseline_em_agosto() -> None:
    from tests.app.sandbox.detalhamento import baseline_do_periodo, envelope_do_periodo

    originais = [
        registro
        for registro in baseline_do_periodo()
        if registro["matricula"] == "MATRIC-422" and registro["competencia"] == "2025-08"
    ]
    assert len(originais) == 1
    original = originais[0]
    linha = envelope_do_periodo()["linhas"]["2025-08"]["MATRIC-422"]
    assert {k: linha[k] for k in ("cod_loja", "cod_marca", "cod_cargo")} == {
        k: str(original[k]) for k in ("cod_loja", "cod_marca", "cod_cargo")
    }
