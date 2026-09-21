import linecache
import sys
import traceback
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, cast

import pandas
import pytest

from app.sandbox.carga import RAIZ_DADOS, Entrada, carregar, ler_jsonl
from app.sandbox.harness import (
    NOME_ARQUIVO,
    NOME_SEM_COMISSAO_NEGATIVA,
    RegraInvalidaError,
    SaidaForaDoContratoError,
    agregar,
    carregar_regra,
    chamar,
    comissao_nao_negativa,
    conferir_saida,
    preparar,
    rodar_regra,
)
from app.sandbox.regras_base import apurar
from app.sandbox.resultado import DecomposicaoInconsistenteError
from tests.app.sandbox.test_regras_base import rh, taxa, venda
from tests.app.sandbox.test_resultado import com_orcamento, validar_no_contrato

RAIZ = Path(__file__).resolve().parents[4]
EXEMPLO = (RAIZ / "contracts" / "harness" / "exemplo" / "regra.py").read_text(encoding="utf-8")

# Devolve o baseline sem mudança e sem nenhuma contribuição.
REGRA_SEM_EFEITO = """
def aplicar_regra(bases, apuracao_base, competencias):
    contribuicoes = apuracao_base.iloc[0:0].copy()
    contribuicoes["elemento_ref"] = []
    contribuicoes["delta"] = []
    return {"apuracao_simulada": apuracao_base.copy(), "contribuicoes": contribuicoes}
"""

# Altera tudo que recebeu, no lugar, e devolve uma saída válida e sem efeito.
REGRA_QUE_MUTA_AS_ENTRADAS = """
def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    apuracao_base["comissao"] = 0.0
    bases["rh"].drop(bases["rh"].index, inplace=True)
    bases["eventos_rh"]["tipo"] = "x"
    competencias.clear()
    contribuicoes = simulada.iloc[0:0].copy()
    contribuicoes["elemento_ref"] = []
    contribuicoes["delta"] = []
    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
"""


# Rebaixa o baseline recebido pela metade e declara, como contribuição, exatamente a
# diferença que isso cria. Se a agregação usasse o baseline que a regra alterou, tudo
# reconciliaria: economia inventada, sem exceção e sem asserção violada.
REGRA_QUE_REBAIXA_O_BASELINE_E_DECLARA_A_DIFERENCA = """
def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    apuracao_base["comissao"] = apuracao_base["comissao"] * 0.5
    contribuicoes = simulada[
        ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]
    ].copy()
    contribuicoes["elemento_ref"] = "elem.1"
    contribuicoes["delta"] = simulada["comissao"] - apuracao_base["comissao"]
    contribuicoes = contribuicoes[contribuicoes["delta"] != 0.0]
    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
"""


@pytest.fixture
def entrada() -> Entrada:
    # Função e não módulo: as regras deste arquivo mutam o que recebem, e a carga custa
    # poucas centenas de ms.
    return carregar(["2025-11"])


def _tabela(**colunas: list[Any]) -> Any:
    return pandas.DataFrame(colunas)


def _saida_valida() -> dict[str, Any]:
    dimensoes: dict[str, list[Any]] = {
        "matricula": ["M"],
        "cod_loja": [1],
        "cod_marca": [10],
        "cod_cargo": [100],
        "competencia": ["2025-11"],
    }
    return {
        "apuracao_simulada": _tabela(**dimensoes, comissao=[1.0]),
        "contribuicoes": _tabela(**dimensoes, elemento_ref=["elem.1"], delta=[1.0]),
    }


# ---- carregar_regra ----


def test_carrega_a_funcao_do_exemplo_do_contrato() -> None:
    assert callable(carregar_regra(EXEMPLO))


@pytest.mark.parametrize(
    ("fonte", "trecho"),
    [
        ("x = 1\n", "não define aplicar_regra"),
        ("aplicar_regra = 3\n", "não define aplicar_regra"),
        ("def aplicar_regra(:\n", "não compila"),
        ("x = 1\x00\n", "não compila"),
    ],
)
def test_fonte_invalida_ou_sem_aplicar_regra_e_recusada(fonte: str, trecho: str) -> None:
    with pytest.raises(RegraInvalidaError, match=trecho):
        carregar_regra(fonte)


def test_excecao_no_nivel_do_modulo_nao_e_engolida() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        carregar_regra("raise RuntimeError('boom')\n")


def test_dataclass_com_annotations_futuras_funciona_na_regra() -> None:
    """Sem o módulo em sys.modules, @dataclass falha com AttributeError por um motivo
    que não tem nada a ver com a regra."""
    fonte = """
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Faixa:
    limite: float

def aplicar_regra(bases, apuracao_base, competencias):
    return Faixa(1.0)
"""

    regra = carregar_regra(fonte)

    assert cast(Any, regra)({}, None, []).limite == 1.0


def test_codigo_gerado_nao_herda_annotations_futuras_do_harness() -> None:
    fonte = """
def f(x: int) -> None:
    pass

ANOTACOES = f.__annotations__

def aplicar_regra(bases, apuracao_base, competencias):
    pass
"""

    regra = carregar_regra(fonte)

    assert regra.__globals__["ANOTACOES"] == {"x": int, "return": None}


def test_traceback_da_regra_cita_regra_py_e_a_linha_ofensora() -> None:
    fonte = "def aplicar_regra(bases, apuracao_base, competencias):\n    return 1 / 0\n"
    regra = carregar_regra(fonte)

    with pytest.raises(ZeroDivisionError) as erro:
        cast(Any, regra)({}, None, [])

    quadros = [
        q for q in traceback.extract_tb(erro.value.__traceback__) if q.filename == NOME_ARQUIVO
    ]
    assert [(q.lineno, q.line) for q in quadros] == [(2, "return 1 / 0")]
    assert linecache.getline(NOME_ARQUIVO, 2).strip() == "return 1 / 0"


def test_o_modulo_da_regra_fica_registrado() -> None:
    carregar_regra("def aplicar_regra(bases, apuracao_base, competencias):\n    pass\n")

    assert "regra" in sys.modules


# ---- cópias ----


def test_preparar_devolve_copias_profundas(entrada: Entrada) -> None:
    copias = preparar(entrada.bases)

    copias["rh"].drop(copias["rh"].index, inplace=True)
    copias["vendas"].loc[:, "vlr_venda"] = 0.0

    assert len(entrada.bases["rh"]) > 0
    assert entrada.bases["vendas"]["vlr_venda"].sum() > 0


def test_regra_que_muta_as_entradas_nao_altera_as_do_harness(entrada: Entrada) -> None:
    antes = {nome: tabela.copy(deep=True) for nome, tabela in entrada.bases.items()}
    base_antes = entrada.apuracao_base.copy(deep=True)
    competencias = ["2025-11"]

    chamar(
        carregar_regra(REGRA_QUE_MUTA_AS_ENTRADAS),
        entrada.bases,
        entrada.apuracao_base,
        competencias,
    )

    for nome, tabela in antes.items():
        assert entrada.bases[nome].equals(tabela)
    assert entrada.apuracao_base.equals(base_antes)
    assert competencias == ["2025-11"]


def test_regra_que_altera_as_entradas_no_lugar_nao_muda_o_resultado(entrada: Entrada) -> None:
    """O pior modo de falha do desenho: se a agregação usasse o mesmo objeto entregue à
    regra, ela rebaixaria o baseline recebido e tudo reconciliaria (nenhuma exceção,
    nenhuma asserção violada) com um número errado. O resultado precisa ser o de uma
    regra sem efeito."""
    saida = rodar_regra(REGRA_QUE_MUTA_AS_ENTRADAS, entrada, ["2025-11"])

    execucao = agregar(saida, entrada, ["2025-11"])

    assert execucao.resultado is not None
    assert execucao.resultado["totais"]["baseline"] == 508382.32
    assert execucao.resultado["totais"]["diferenca_abs"] == 0.0


def test_baseline_rebaixado_pela_regra_nao_vira_economia_inventada(entrada: Entrada) -> None:
    saida = rodar_regra(REGRA_QUE_REBAIXA_O_BASELINE_E_DECLARA_A_DIFERENCA, entrada, ["2025-11"])

    # Contra o baseline verdadeiro a regra não mudou nada, então as contribuições que ela
    # declarou não explicam diferença nenhuma: a fraude aparece como inconsistência.
    with pytest.raises(DecomposicaoInconsistenteError):
        agregar(saida, entrada, ["2025-11"])


# ---- conferência da saída ----


@pytest.mark.parametrize("devolvido", [None, [], "texto", 1])
def test_retorno_que_nao_e_dict_e_recusado(devolvido: object) -> None:
    with pytest.raises(SaidaForaDoContratoError, match="não um dict"):
        conferir_saida(devolvido)


@pytest.mark.parametrize("chave", ["apuracao_simulada", "contribuicoes"])
def test_tabela_ausente_ou_de_tipo_errado_e_recusada(chave: str) -> None:
    ausente = _saida_valida()
    del ausente[chave]
    errada = _saida_valida() | {chave: [{"matricula": "M"}]}

    for saida in (ausente, errada):
        with pytest.raises(SaidaForaDoContratoError, match=f"{chave} deve ser um DataFrame"):
            conferir_saida(saida)


@pytest.mark.parametrize(
    ("chave", "coluna"),
    [
        ("apuracao_simulada", "comissao"),
        ("apuracao_simulada", "cod_marca"),
        ("contribuicoes", "elemento_ref"),
        ("contribuicoes", "delta"),
    ],
)
def test_coluna_ausente_na_saida_e_recusada(chave: str, coluna: str) -> None:
    saida = _saida_valida()
    saida[chave] = saida[chave].drop(columns=[coluna])

    with pytest.raises(SaidaForaDoContratoError, match=coluna):
        conferir_saida(saida)


def test_coluna_a_mais_na_saida_e_aceita() -> None:
    saida = _saida_valida()
    saida["apuracao_simulada"]["auxiliar"] = 1

    assert conferir_saida(saida) is saida


# ---- a invariante sem_comissao_negativa ----


def _linhas(*comissoes: object) -> list[dict[str, object]]:
    return [
        {"competencia": "2025-11", "matricula": f"M{numero}", "comissao": valor}
        for numero, valor in enumerate(comissoes, start=1)
    ]


def test_comissoes_nao_negativas_passam() -> None:
    assert comissao_nao_negativa(_linhas(0.0, 10.0, 0)) == {
        "nome": "sem_comissao_negativa",
        "resultado": "ok",
        "detalhe": None,
    }


@pytest.mark.parametrize("valor", [-0.01, float("nan"), float("inf"), None, "abc", True], ids=repr)
def test_comissao_negativa_ou_invalida_viola(valor: object) -> None:
    desfecho = comissao_nao_negativa(_linhas(10.0, valor))

    assert desfecho["resultado"] == "violada"
    assert desfecho["detalhe"] is not None
    assert "2025-11, matrícula M2" in desfecho["detalhe"]


def test_detalhe_cita_poucas_violacoes_e_a_contagem_do_resto() -> None:
    desfecho = comissao_nao_negativa(_linhas(*([-1.0] * 8)))

    assert desfecho["detalhe"] is not None
    assert desfecho["detalhe"].count("negativa") == 5
    assert desfecho["detalhe"].endswith("e mais 3")


def test_o_nome_da_invariante_e_o_mesmo_da_t031() -> None:
    tabela = apurar([rh("MATRIC-1")], [venda("MATRIC-1", 1000)], [taxa(0.025)], [], "2025-11")

    nomes = [d["nome"] for d in cast(Any, tabela).resultado_apuracao["assercoes"]]

    assert NOME_SEM_COMISSAO_NEGATIVA in nomes


def test_comissao_negativa_na_apuracao_simulada_nao_vira_resultado(entrada: Entrada) -> None:
    fonte = """
def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    simulada.loc[simulada.index[0], "comissao"] = -1.0
    contribuicoes = simulada.iloc[:1].copy()
    contribuicoes["elemento_ref"] = "elem.1"
    contribuicoes["delta"] = -1.0
    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
"""

    execucao = agregar(rodar_regra(fonte, entrada, ["2025-11"]), entrada, ["2025-11"])

    assert execucao.resultado is None
    assert [d["resultado"] for d in execucao.assercoes] == ["violada"]


def test_diferenca_sem_contribuicao_e_recusada(entrada: Entrada) -> None:
    fonte = """
def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    simulada.loc[simulada.index[0], "comissao"] += 5.0
    contribuicoes = simulada.iloc[0:0].copy()
    contribuicoes["elemento_ref"] = []
    contribuicoes["delta"] = []
    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
"""

    saida = rodar_regra(fonte, entrada, ["2025-11"])

    with pytest.raises(DecomposicaoInconsistenteError, match="nenhum elemento assumiu"):
        agregar(saida, entrada, ["2025-11"])


# ---- a regra de exemplo do contrato, de ponta a ponta ----


def _diferenca_esperada_do_exemplo(competencia: str) -> Decimal:
    """Oráculo independente: aritmética exata em Decimal, sem pandas. A regra usa float e
    a soma em ordem diferente pode virar meio centavo em algumas linhas, por isso o teste
    compara com tolerância declarada."""
    centavo = Decimal("0.01")
    marcas = {
        r["matricula"]: r["cod_marca"]
        for r in ler_jsonl(RAIZ_DADOS / "rh.jsonl")
        if r["competencia"] == competencia
    }
    vendido: dict[str, Decimal] = {}
    for r in ler_jsonl(RAIZ_DADOS / "vendas.jsonl"):
        if r["competencia"] == competencia:
            vendido[str(r["matricula"])] = vendido.get(str(r["matricula"]), Decimal(0)) + Decimal(
                str(r["vlr_venda"])
            )
    total = Decimal(0)
    for r in ler_jsonl(RAIZ_DADOS / "baselines" / f"baseline-{competencia}.jsonl"):
        if marcas[str(r["matricula"])] != 10 or r["cod_cargo"] != 100:
            continue
        nova = (vendido.get(str(r["matricula"]), Decimal(0)) * Decimal("0.025")).quantize(
            centavo, rounding=ROUND_HALF_UP
        )
        total += nova - Decimal(str(r["comissao"]))
    return total


def test_exemplo_do_contrato_sobre_novembro(entrada: Entrada) -> None:
    saida = rodar_regra(EXEMPLO, entrada, ["2025-11"])

    execucao = agregar(saida, entrada, ["2025-11"])

    assert execucao.resultado is not None
    totais = execucao.resultado["totais"]
    decomposicao = execucao.resultado["decomposicao"]
    # O baseline é exato e independente: é o total que a T-032 congelou.
    assert totais["baseline"] == 508382.32
    assert abs(
        Decimal(str(totais["diferenca_abs"])) - _diferenca_esperada_do_exemplo("2025-11")
    ) <= Decimal("0.10")
    assert decomposicao["elemento"] == {"nucleo.percentual": totais["diferenca_abs"]}
    assert decomposicao["competencia"] == {"2025-11": totais["diferenca_abs"]}
    assert len(decomposicao["loja"]) == entrada.apuracao_base["cod_loja"].nunique()
    assert set(decomposicao["marca"]) == {
        str(m) for m in entrada.apuracao_base["cod_marca"].unique()
    }


def test_exemplo_do_contrato_sobre_o_periodo_inteiro() -> None:
    competencias = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
    completa = carregar(competencias)

    execucao = agregar(rodar_regra(EXEMPLO, completa, competencias), completa, competencias)

    assert execucao.resultado is not None
    assert execucao.resultado["totais"]["baseline"] == 3299894.24
    assert list(execucao.resultado["decomposicao"]["competencia"]) == competencias


def test_saida_do_exemplo_valida_no_schema_do_contrato(entrada: Entrada) -> None:
    execucao = agregar(rodar_regra(EXEMPLO, entrada, ["2025-11"]), entrada, ["2025-11"])
    assert execucao.resultado is not None

    processo = validar_no_contrato(com_orcamento(execucao.resultado))

    assert processo.returncode == 0, processo.stderr


def test_execucao_e_deterministica(entrada: Entrada) -> None:
    primeira = agregar(rodar_regra(EXEMPLO, entrada, ["2025-11"]), entrada, ["2025-11"])
    segunda = agregar(rodar_regra(EXEMPLO, entrada, ["2025-11"]), entrada, ["2025-11"])

    assert primeira == segunda
