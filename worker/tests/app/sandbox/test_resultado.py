import json
import re
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.sandbox.assercoes import Desfecho
from app.sandbox.resultado import (
    PADRAO_COMPETENCIA,
    PADRAO_ELEMENTO_REF,
    DecomposicaoInconsistenteError,
    ResultadoInvalidoError,
    ResultadoSimulacao,
    montar_resultado,
)
from tests.app.sandbox.test_regras_base import DataFrameFalso

RAIZ = Path(__file__).resolve().parents[4]
VALIDADOR = RAIZ / "contracts" / "harness" / "validar-saida.py"
COMUM = RAIZ / "contracts" / "domain" / "comum.schema.json"


def linha_base(
    matricula: str = "MATRIC-1",
    *,
    competencia: str = "2025-11",
    cod_loja: int = 13,
    cod_marca: int = 10,
    cod_cargo: int = 100,
    comissao: float = 100.0,
) -> dict[str, object]:
    return {
        "matricula": matricula,
        "cod_loja": cod_loja,
        "cod_marca": cod_marca,
        "cod_cargo": cod_cargo,
        "competencia": competencia,
        "comissao": comissao,
    }


def contribuicao(
    matricula: str = "MATRIC-1",
    *,
    competencia: str = "2025-11",
    cod_loja: int = 13,
    cod_marca: int = 10,
    cod_cargo: int = 100,
    elemento_ref: str = "elem.1",
    delta: float = 30.0,
) -> dict[str, object]:
    return {
        "matricula": matricula,
        "cod_loja": cod_loja,
        "cod_marca": cod_marca,
        "cod_cargo": cod_cargo,
        "competencia": competencia,
        "elemento_ref": elemento_ref,
        "delta": delta,
    }


def com_comissao(linha: dict[str, object], comissao: float) -> dict[str, object]:
    return {**linha, "comissao": comissao}


def assercoes_ok() -> list[Desfecho]:
    return [Desfecho(nome="sem_comissao_negativa", resultado="ok", detalhe=None)]


def montar(
    base: list[dict[str, object]],
    simulada: list[dict[str, object]],
    contribuicoes: list[dict[str, object]],
    competencias: list[str] | None = None,
) -> ResultadoSimulacao:
    return montar_resultado(
        {"apuracao_simulada": simulada, "contribuicoes": contribuicoes},
        base,
        competencias if competencias is not None else ["2025-11"],
        assercoes=assercoes_ok(),
    )


def soma(quebra: dict[str, float]) -> Decimal:
    return sum((Decimal(str(valor)) for valor in quebra.values()), Decimal(0))


def cenario_de_varias_dimensoes() -> (
    tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]
):
    """Duas competências, três lojas, dois cargos, duas marcas e dois elementos."""
    base = [
        linha_base("MATRIC-1", competencia="2025-10", cod_loja=9, comissao=100.0),
        linha_base("MATRIC-2", competencia="2025-10", cod_loja=13, cod_marca=20, comissao=250.55),
        linha_base("MATRIC-3", competencia="2025-11", cod_loja=58, cod_cargo=150, comissao=80.10),
        linha_base("MATRIC-4", competencia="2025-11", cod_loja=13, comissao=310.40),
    ]
    simulada = [
        com_comissao(base[0], 100.0),
        com_comissao(base[1], 263.08),
        com_comissao(base[2], 84.11),
        com_comissao(base[3], 325.92),
    ]
    contribuicoes = [
        contribuicao("MATRIC-2", competencia="2025-10", cod_loja=13, cod_marca=20, delta=12.53),
        contribuicao(
            "MATRIC-3",
            competencia="2025-11",
            cod_loja=58,
            cod_cargo=150,
            elemento_ref="nucleo.percentual",
            delta=4.01,
        ),
        contribuicao("MATRIC-4", competencia="2025-11", delta=15.52),
    ]
    return base, simulada, contribuicoes


def test_monta_totais_decomposicao_e_assercoes_do_periodo() -> None:
    base = [
        linha_base("MATRIC-1", comissao=100.0),
        linha_base("MATRIC-2", cod_loja=58, cod_cargo=150, comissao=200.0),
    ]
    simulada = [com_comissao(base[0], 130.0), base[1]]

    resultado = montar(base, simulada, [contribuicao("MATRIC-1", delta=30.0)])

    assert resultado == {
        "totais": {
            "baseline": 300.0,
            "simulado": 330.0,
            "diferenca_abs": 30.0,
            "diferenca_pct": 0.1,
        },
        "assercoes": [{"nome": "sem_comissao_negativa", "resultado": "ok", "detalhe": None}],
        "decomposicao": {
            "elemento": {"elem.1": 30.0},
            "loja": {"13": 30.0, "58": 0.0},
            "marca": {"10": 30.0},
            "cargo": {"100": 30.0, "150": 0.0},
            "competencia": {"2025-11": 30.0},
        },
    }


@pytest.mark.parametrize("quebra", ["elemento", "loja", "marca", "cargo", "competencia"])
def test_soma_de_cada_quebra_reconcilia_com_a_diferenca_total(quebra: str) -> None:
    base, simulada, contribuicoes = cenario_de_varias_dimensoes()

    resultado = montar(base, simulada, contribuicoes, ["2025-10", "2025-11"])

    esperado = Decimal(str(resultado["totais"]["diferenca_abs"]))
    assert soma(resultado["decomposicao"][quebra]) == esperado  # type: ignore[literal-required]


def test_elemento_cujas_contribuicoes_se_cancelam_aparece_com_zero() -> None:
    base = [linha_base("MATRIC-1", comissao=100.0), linha_base("MATRIC-2", comissao=100.0)]
    simulada = [com_comissao(base[0], 150.0), com_comissao(base[1], 50.0)]
    contribuicoes = [
        contribuicao("MATRIC-1", delta=50.0),
        contribuicao("MATRIC-2", delta=-50.0),
    ]

    resultado = montar(base, simulada, contribuicoes)

    assert resultado["decomposicao"]["elemento"] == {"elem.1": 0.0}
    assert resultado["totais"]["diferenca_abs"] == 0.0


def test_competencia_sem_efeito_da_regra_aparece_com_zero() -> None:
    base = [
        linha_base("MATRIC-1", competencia="2025-09", comissao=100.0),
        linha_base("MATRIC-1", competencia="2025-10", comissao=100.0),
        linha_base("MATRIC-1", competencia="2025-11", comissao=100.0),
    ]
    simulada = [base[0], base[1], com_comissao(base[2], 142.0)]
    contribuicoes = [contribuicao("MATRIC-1", competencia="2025-11", delta=42.0)]

    resultado = montar(base, simulada, contribuicoes, ["2025-09", "2025-10", "2025-11"])

    assert resultado["decomposicao"]["competencia"] == {
        "2025-09": 0.0,
        "2025-10": 0.0,
        "2025-11": 42.0,
    }


def test_competencia_do_periodo_sem_nenhuma_linha_aparece_com_zero() -> None:
    base = [linha_base("MATRIC-1", competencia="2025-11", comissao=100.0)]
    simulada = [com_comissao(base[0], 110.0)]
    contribuicoes = [contribuicao("MATRIC-1", delta=10.0)]

    resultado = montar(base, simulada, contribuicoes, ["2025-08", "2025-11"])

    assert resultado["decomposicao"]["competencia"] == {"2025-08": 0.0, "2025-11": 10.0}


def test_loja_simulada_sem_efeito_aparece_com_zero() -> None:
    base = [
        linha_base("MATRIC-1", cod_loja=13, comissao=100.0),
        linha_base("MATRIC-2", cod_loja=58, comissao=100.0),
    ]
    simulada = [com_comissao(base[0], 120.0), base[1]]

    resultado = montar(base, simulada, [contribuicao("MATRIC-1", delta=20.0)])

    assert resultado["decomposicao"]["loja"] == {"13": 20.0, "58": 0.0}


def test_decomposicao_existe_quando_a_diferenca_e_zero() -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]

    resultado = montar(base, [dict(base[0])], [])

    assert resultado["totais"] == {
        "baseline": 100.0,
        "simulado": 100.0,
        "diferenca_abs": 0.0,
        "diferenca_pct": 0.0,
    }
    assert resultado["decomposicao"] == {
        "elemento": {},
        "loja": {"13": 0.0},
        "marca": {"10": 0.0},
        "cargo": {"100": 0.0},
        "competencia": {"2025-11": 0.0},
    }


def test_diferenca_pct_e_zero_quando_o_baseline_e_zero() -> None:
    base = [linha_base("MATRIC-1", comissao=0.0)]
    simulada = [com_comissao(base[0], 50.0)]

    resultado = montar(base, simulada, [contribuicao("MATRIC-1", delta=50.0)])

    assert resultado["totais"]["diferenca_pct"] == 0.0
    assert resultado["totais"]["diferenca_abs"] == 50.0


def test_residuo_de_arredondamento_fecha_na_quebra_por_elemento() -> None:
    base = [linha_base("MATRIC-1", comissao=0.0)]
    simulada = [com_comissao(base[0], 30.01)]
    contribuicoes = [
        contribuicao("MATRIC-1", elemento_ref="elem.1", delta=15.005),
        contribuicao("MATRIC-1", elemento_ref="elem.2", delta=15.005),
    ]

    resultado = montar(base, simulada, contribuicoes)

    # Cada balde arredondado sozinho daria 15,01 e a quebra somaria um centavo a
    # mais que a diferença; o resíduo vai para o primeiro dos maiores.
    assert resultado["decomposicao"]["elemento"] == {"elem.1": 15.0, "elem.2": 15.01}
    assert soma(resultado["decomposicao"]["elemento"]) == Decimal("30.01")


def test_ruido_de_um_centavo_na_atribuicao_nao_e_defeito() -> None:
    base = [linha_base("MATRIC-1", comissao=0.0)]
    simulada = [com_comissao(base[0], 30.00)]
    contribuicoes = [contribuicao("MATRIC-1", delta=30.01)]

    resultado = montar(base, simulada, contribuicoes)

    assert resultado["decomposicao"]["elemento"] == {"elem.1": 30.0}


def test_contribuicoes_que_nao_somam_o_delta_levantam_erro() -> None:
    base = [linha_base("MATRIC-1", comissao=0.0)]
    simulada = [com_comissao(base[0], 30.0)]

    with pytest.raises(DecomposicaoInconsistenteError, match="MATRIC-1"):
        montar(base, simulada, [contribuicao("MATRIC-1", delta=20.0)])


def test_delta_sem_nenhuma_contribuicao_levanta_erro() -> None:
    base = [linha_base("MATRIC-1", comissao=0.0)]
    simulada = [com_comissao(base[0], 30.0)]

    with pytest.raises(DecomposicaoInconsistenteError, match="nenhum elemento assumiu"):
        montar(base, simulada, [])


def test_contribuicao_de_linha_inexistente_no_baseline_levanta_erro() -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]

    with pytest.raises(ResultadoInvalidoError, match="não existe no baseline"):
        montar(base, [dict(base[0])], [contribuicao("MATRIC-9", delta=0.0)])


@pytest.mark.parametrize(
    ("defeito", "mensagem"),
    [
        ("ausente", "não trouxe"),
        ("extra", "não existe no baseline"),
        ("duplicada", "repete"),
    ],
)
def test_linha_ausente_extra_ou_duplicada_na_simulada_levanta_erro(
    defeito: str, mensagem: str
) -> None:
    base = [linha_base("MATRIC-1", comissao=100.0), linha_base("MATRIC-2", comissao=100.0)]
    simulada = [dict(linha) for linha in base]
    if defeito == "ausente":
        simulada.pop()
    elif defeito == "extra":
        simulada.append(linha_base("MATRIC-9", comissao=100.0))
    else:
        simulada.append(dict(base[0]))

    with pytest.raises(ResultadoInvalidoError, match=mensagem):
        montar(base, simulada, [])


def test_baseline_com_chave_repetida_levanta_erro() -> None:
    base = [linha_base("MATRIC-1", comissao=100.0), linha_base("MATRIC-1", comissao=100.0)]

    with pytest.raises(ResultadoInvalidoError, match="repete"):
        montar(base, [dict(base[0])], [])


def test_baseline_com_competencia_fora_do_periodo_levanta_erro() -> None:
    base = [linha_base("MATRIC-1", competencia="2025-08", comissao=100.0)]

    with pytest.raises(ResultadoInvalidoError, match="fora do período"):
        montar(base, [dict(base[0])], [], ["2025-11"])


@pytest.mark.parametrize("campo", ["cod_loja", "cod_marca", "cod_cargo"])
def test_dimensao_divergente_do_baseline_levanta_erro(campo: str) -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    simulada = [{**base[0], campo: 999}]

    with pytest.raises(ResultadoInvalidoError, match=f"mudou {campo}"):
        montar(base, simulada, [])


def test_dimensao_declarada_na_contribuicao_nao_move_a_quebra() -> None:
    base = [linha_base("MATRIC-1", cod_loja=13, comissao=100.0)]
    simulada = [com_comissao(base[0], 130.0)]
    contribuicoes = [contribuicao("MATRIC-1", cod_loja=99, delta=30.0)]

    resultado = montar(base, simulada, contribuicoes)

    assert resultado["decomposicao"]["loja"] == {"13": 30.0}


@pytest.mark.parametrize("valor", [None, "abc", True, float("nan"), float("inf")])
def test_comissao_nao_numerica_ou_nao_finita_levanta_erro(valor: object) -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    simulada = [{**base[0], "comissao": valor}]

    with pytest.raises(ResultadoInvalidoError, match="comissao"):
        montar(base, simulada, [])


@pytest.mark.parametrize("elemento_ref", ["nucleo.percentual", "elem.1", "elem.42", "nucleo.loja"])
def test_elemento_ref_do_nucleo_e_da_especificacao_sao_aceitos(elemento_ref: str) -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    simulada = [com_comissao(base[0], 130.0)]
    contribuicoes = [contribuicao("MATRIC-1", elemento_ref=elemento_ref, delta=30.0)]

    resultado = montar(base, simulada, contribuicoes)

    assert resultado["decomposicao"]["elemento"] == {elemento_ref: 30.0}


@pytest.mark.parametrize("elemento_ref", ["elem.a", "nucleo.Percentual", "elem1", "outro.coisa"])
def test_elemento_ref_fora_do_padrao_levanta_erro(elemento_ref: str) -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    simulada = [com_comissao(base[0], 130.0)]
    contribuicoes = [contribuicao("MATRIC-1", elemento_ref=elemento_ref, delta=30.0)]

    with pytest.raises(ResultadoInvalidoError, match="fora do espaço"):
        montar(base, simulada, contribuicoes)


@pytest.mark.parametrize(
    ("tabela", "coluna"),
    [
        ("apuracao_base", "matricula"),
        ("apuracao_base", "cod_marca"),
        ("apuracao_base", "comissao"),
        ("apuracao_simulada", "comissao"),
        ("contribuicoes", "elemento_ref"),
        ("contribuicoes", "delta"),
    ],
)
def test_coluna_ausente_levanta_erro(tabela: str, coluna: str) -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    simulada = [com_comissao(base[0], 130.0)]
    contribuicoes = [contribuicao("MATRIC-1", delta=30.0)]
    tabelas = {
        "apuracao_base": base,
        "apuracao_simulada": simulada,
        "contribuicoes": contribuicoes,
    }
    tabelas[tabela][0].pop(coluna)

    with pytest.raises(ResultadoInvalidoError, match=coluna):
        montar(base, simulada, contribuicoes)


@pytest.mark.parametrize("tabela", ["apuracao_simulada", "contribuicoes"])
def test_chave_que_a_funcao_gerada_nao_devolveu_levanta_erro(tabela: str) -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    saida: dict[str, list[dict[str, object]]] = {
        "apuracao_simulada": [dict(base[0])],
        "contribuicoes": [],
    }
    saida.pop(tabela)

    with pytest.raises(ResultadoInvalidoError, match=tabela):
        montar_resultado(saida, base, ["2025-11"], assercoes=assercoes_ok())


@pytest.mark.parametrize("competencias", [[], ["2025-11", "2025-11"], ["2025-13"], ["novembro"]])
def test_competencias_invalidas_levantam_erro(competencias: list[str]) -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]

    with pytest.raises(ResultadoInvalidoError, match="compet"):
        montar(base, [dict(base[0])], [], competencias)


def test_aceita_tabela_dataframe_like_sem_depender_de_pandas() -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    simulada = [com_comissao(base[0], 130.0)]
    contribuicoes = [contribuicao("MATRIC-1", delta=30.0)]

    resultado = montar_resultado(
        {
            "apuracao_simulada": DataFrameFalso(simulada),
            "contribuicoes": DataFrameFalso(contribuicoes),
        },
        DataFrameFalso(base),
        ["2025-11"],
        assercoes=assercoes_ok(),
    )

    assert resultado == montar(base, simulada, contribuicoes)


def test_codigo_inteiro_e_texto_produzem_a_mesma_chave() -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    como_texto = [{**base[0], "cod_loja": "13", "cod_marca": "10", "cod_cargo": "100"}]

    resultado = montar(como_texto, [com_comissao(como_texto[0], 100.0)], [])

    assert resultado["decomposicao"]["loja"] == {"13": 0.0}
    assert resultado == montar(base, [com_comissao(base[0], 100.0)], [])


def test_chaves_da_decomposicao_sao_strings_em_ordem_deterministica() -> None:
    base = [
        linha_base("MATRIC-1", competencia="2025-08", cod_loja=58, comissao=100.0),
        linha_base("MATRIC-2", competencia="2025-11", cod_loja=9, comissao=100.0),
        linha_base("MATRIC-3", competencia="2025-11", cod_loja=13, comissao=100.0),
    ]
    simulada = [com_comissao(linha, 110.0) for linha in base]
    contribuicoes = [
        contribuicao(
            "MATRIC-1", competencia="2025-08", cod_loja=58, elemento_ref="elem.10", delta=10.0
        ),
        contribuicao("MATRIC-2", cod_loja=9, elemento_ref="elem.2", delta=10.0),
        contribuicao("MATRIC-3", elemento_ref="nucleo.percentual", delta=10.0),
    ]

    resultado = montar(base, simulada, contribuicoes, ["2025-08", "2025-11"])

    assert list(resultado["decomposicao"]["loja"]) == ["9", "13", "58"]
    assert list(resultado["decomposicao"]["elemento"]) == [
        "nucleo.percentual",
        "elem.2",
        "elem.10",
    ]
    assert list(resultado["decomposicao"]["competencia"]) == ["2025-08", "2025-11"]


def test_totais_nao_trazem_orcamento() -> None:
    base = [linha_base("MATRIC-1", comissao=100.0)]

    resultado = montar(base, [dict(base[0])], [])

    assert "orcamento" not in resultado["totais"]


def test_nenhuma_linha_das_bases_aparece_na_saida() -> None:
    base, simulada, contribuicoes = cenario_de_varias_dimensoes()

    resultado = montar(base, simulada, contribuicoes, ["2025-10", "2025-11"])

    serializado = json.dumps(resultado)
    assert "MATRIC-" not in serializado
    assert "matricula" not in serializado


def test_nao_muta_as_tabelas_recebidas() -> None:
    base, simulada, contribuicoes = cenario_de_varias_dimensoes()
    copias = deepcopy((base, simulada, contribuicoes))

    montar(base, simulada, contribuicoes, ["2025-10", "2025-11"])

    assert (base, simulada, contribuicoes) == copias


type Cenario = tuple[
    list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[str]
]


def cenario_diferenca_zero() -> Cenario:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    return base, [dict(base[0])], [], ["2025-11"]


def cenario_diferenca_negativa() -> Cenario:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    return base, [com_comissao(base[0], 60.0)], [contribuicao(delta=-40.0)], ["2025-11"]


def cenario_elemento_que_se_cancela() -> Cenario:
    base = [linha_base("MATRIC-1", comissao=100.0), linha_base("MATRIC-2", comissao=100.0)]
    simulada = [com_comissao(base[0], 150.0), com_comissao(base[1], 50.0)]
    contribuicoes = [contribuicao("MATRIC-1", delta=50.0), contribuicao("MATRIC-2", delta=-50.0)]
    return base, simulada, contribuicoes, ["2025-11"]


def cenario_competencia_sem_efeito() -> Cenario:
    base = [
        linha_base("MATRIC-1", competencia="2025-09", comissao=100.0),
        linha_base("MATRIC-1", competencia="2025-10", comissao=100.0),
        linha_base("MATRIC-1", competencia="2025-11", comissao=100.0),
    ]
    simulada = [base[0], base[1], com_comissao(base[2], 142.0)]
    contribuicoes = [contribuicao(competencia="2025-11", delta=42.0)]
    return base, simulada, contribuicoes, ["2025-09", "2025-10", "2025-11"]


def cenario_competencia_do_periodo_sem_nenhuma_linha() -> Cenario:
    base = [linha_base("MATRIC-1", comissao=100.0)]
    return base, [com_comissao(base[0], 110.0)], [contribuicao(delta=10.0)], ["2025-08", "2025-11"]


def cenario_baseline_zero() -> Cenario:
    base = [linha_base("MATRIC-1", comissao=0.0)]
    return base, [com_comissao(base[0], 50.0)], [contribuicao(delta=50.0)], ["2025-11"]


def cenario_residuo_de_arredondamento() -> Cenario:
    base = [linha_base("MATRIC-1", comissao=0.0)]
    contribuicoes = [
        contribuicao(elemento_ref="elem.1", delta=15.005),
        contribuicao(elemento_ref="elem.2", delta=15.005),
    ]
    return base, [com_comissao(base[0], 30.01)], contribuicoes, ["2025-11"]


def cenario_codigos_como_texto() -> Cenario:
    base = [{**linha_base("MATRIC-1", comissao=100.0), "cod_loja": "13", "cod_marca": "10"}]
    return base, [com_comissao(base[0], 130.0)], [contribuicao(delta=30.0)], ["2025-11"]


def cenario_elementos_de_nucleo_e_especificacao() -> Cenario:
    base = [
        linha_base("MATRIC-1", cod_loja=58, comissao=100.0),
        linha_base("MATRIC-2", cod_loja=9, comissao=100.0),
        linha_base("MATRIC-3", cod_loja=13, comissao=100.0),
    ]
    simulada = [com_comissao(linha, 110.0) for linha in base]
    contribuicoes = [
        contribuicao("MATRIC-1", elemento_ref="elem.10", delta=10.0),
        contribuicao("MATRIC-2", elemento_ref="elem.2", delta=10.0),
        contribuicao("MATRIC-3", elemento_ref="nucleo.percentual", delta=10.0),
    ]
    return base, simulada, contribuicoes, ["2025-11"]


def cenario_varias_dimensoes_em_duas_competencias() -> Cenario:
    return (*cenario_de_varias_dimensoes(), ["2025-10", "2025-11"])


def com_orcamento(resultado: ResultadoSimulacao) -> dict[str, Any]:
    """O passo que o worker faz fora do container (T-066).

    O schema exige `totais.orcamento`, que o container não recebe; o teste faz aqui
    o que o worker fará lá.
    """
    payload: dict[str, Any] = dict(resultado)
    payload["totais"] = {**resultado["totais"], "orcamento": 485000.0}
    return payload


def validar_no_contrato(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    """Roda o validador do contrato (T-034) por subprocesso, com o JSON no stdin."""
    return subprocess.run(
        [sys.executable, str(VALIDADOR), "-"],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.parametrize(
    "cenario",
    [
        pytest.param(cenario_diferenca_zero(), id="diferenca_zero"),
        pytest.param(cenario_diferenca_negativa(), id="diferenca_negativa"),
        pytest.param(cenario_elemento_que_se_cancela(), id="elemento_que_se_cancela"),
        pytest.param(cenario_competencia_sem_efeito(), id="competencia_sem_efeito"),
        pytest.param(
            cenario_competencia_do_periodo_sem_nenhuma_linha(),
            id="competencia_do_periodo_sem_nenhuma_linha",
        ),
        pytest.param(cenario_baseline_zero(), id="baseline_zero"),
        pytest.param(cenario_residuo_de_arredondamento(), id="residuo_de_arredondamento"),
        pytest.param(cenario_codigos_como_texto(), id="codigos_como_texto"),
        pytest.param(
            cenario_elementos_de_nucleo_e_especificacao(),
            id="elementos_de_nucleo_e_especificacao",
        ),
        pytest.param(
            cenario_varias_dimensoes_em_duas_competencias(),
            id="varias_dimensoes_em_duas_competencias",
        ),
    ],
)
def test_saida_valida_contra_o_schema_pelo_validador_do_contrato(cenario: Cenario) -> None:
    base, simulada, contribuicoes, competencias = cenario

    resultado = montar(base, simulada, contribuicoes, competencias)

    execucao = validar_no_contrato(com_orcamento(resultado))
    assert execucao.returncode == 0, execucao.stderr


@pytest.mark.parametrize(
    ("adulteracao", "trecho_do_erro"),
    [
        (lambda p: p["totais"].pop("orcamento"), "orcamento"),
        (lambda p: p.pop("decomposicao"), "decomposicao"),
        (lambda p: p["decomposicao"].pop("competencia"), "competencia"),
        (lambda p: p["decomposicao"]["elemento"].update({"foo": 1.0}), "foo"),
        (lambda p: p["decomposicao"]["competencia"].update({"2025-13": 1.0}), "2025-13"),
        (lambda p: p["decomposicao"]["loja"].update({"13": "abc"}), "abc"),
    ],
    ids=[
        "sem_orcamento",
        "sem_decomposicao",
        "sem_quebra_por_competencia",
        "elemento_ref_invalido",
        "competencia_invalida",
        "valor_nao_numerico",
    ],
)
def test_validador_do_contrato_rejeita_saida_adulterada(
    adulteracao: Callable[[dict[str, Any]], object], trecho_do_erro: str
) -> None:
    """Prova que o validador não é vacuoso: sem isto, os testes acima passariam
    mesmo que o subprocesso deixasse de conferir alguma coisa."""
    base, simulada, contribuicoes, competencias = cenario_varias_dimensoes_em_duas_competencias()
    payload = com_orcamento(montar(base, simulada, contribuicoes, competencias))

    adulteracao(payload)

    execucao = validar_no_contrato(payload)
    assert execucao.returncode != 0
    assert trecho_do_erro in execucao.stderr


@pytest.mark.parametrize(
    ("padrao", "definicao"),
    [(PADRAO_ELEMENTO_REF, "elemento_ref"), (PADRAO_COMPETENCIA, "competencia")],
)
def test_padroes_acompanham_o_schema_do_contrato(padrao: re.Pattern[str], definicao: str) -> None:
    schema = json.loads(COMUM.read_text(encoding="utf-8"))

    assert padrao.pattern == schema["$defs"][definicao]["pattern"]
