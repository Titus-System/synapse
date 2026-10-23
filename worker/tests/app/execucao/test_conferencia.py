"""A conferência do detalhamento e das quebras contra o baseline do worker e os totais (T-262).

O resultado legítimo é o que o agregador do harness (``montar_resultado``, T-035) monta sobre o
baseline real, com uma regra que altera uma em cada três matrículas no período inteiro. Cada
adulteração parte dele e muda uma coisa só, como uma regra que forjasse o envelope faria.
"""

import copy
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from app.execucao.baseline import carregar_baselines
from app.execucao.bases import carregar_bases
from app.execucao.conferencia import VERIFICACOES, Divergencia, conferir_detalhamento
from tests.app.execucao.envelopes import linhas_para, resultado_para

PERIODO = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
A_MAIS = "12345.67"
# O baseline de 2025-11 reapurado sobre as vendas escaladas até 10% acima do total histórico.
VENDAS_2025_11 = Decimal("13271681.51")
META_2025_11 = float(VENDAS_2025_11 * Decimal("1.1"))

type Adulteracao = Callable[[dict[str, Any], dict[str, Any]], None]


def legitimo() -> tuple[dict[str, Any], dict[str, Any]]:
    return resultado_para(PERIODO, A_MAIS), linhas_para(PERIODO, A_MAIS)


def conferir(resultado: dict[str, Any], linhas: dict[str, Any]) -> Divergencia | None:
    return conferir_detalhamento(
        resultado,  # type: ignore[arg-type]
        linhas,  # type: ignore[arg-type]
        carregar_baselines().linhas_do_periodo(PERIODO),
    )


def alterada(linhas: dict[str, Any]) -> tuple[str, str]:
    """Uma linha que a regra alterou, com contribuição de dois elementos."""
    for competencia, mes in linhas.items():
        for matricula, linha in mes.items():
            if len(linha["contribuicoes"]) == 2:
                return competencia, matricula
    raise AssertionError("a regra do resultado legítimo não alterou nenhuma linha")


def inalterada(linhas: dict[str, Any], competencia: str) -> str:
    return next(m for m, linha in linhas[competencia].items() if not linha["contribuicoes"])


def somar(linhas: dict[str, Any], competencia: str, matricula: str, campo: str, valor: str) -> None:
    linha = linhas[competencia][matricula]
    linha[campo] = float(Decimal(str(linha[campo])) + Decimal(valor))


# ---- o resultado legítimo ----


def test_resultado_legitimo_do_periodo_inteiro_e_coerente() -> None:
    resultado, linhas = legitimo()
    alteradas = sum(1 for mes in linhas.values() for linha in mes.values() if linha["diferenca"])

    assert conferir(resultado, linhas) is None
    assert 0 < alteradas < sum(len(mes) for mes in linhas.values())


def test_resultado_legitimo_que_reduz_a_comissao_e_coerente() -> None:
    resultado = resultado_para(PERIODO, "-50000.00")
    linhas = linhas_para(PERIODO, "-50000.00")

    assert conferir(resultado, linhas) is None


def test_na_meta_o_detalhamento_e_conferido_contra_o_baseline_reapurado() -> None:
    resultado = resultado_para(["2025-11"], A_MAIS, meta_venda=META_2025_11)
    linhas = linhas_para(["2025-11"], A_MAIS, meta_venda=META_2025_11)
    reapurado = carregar_bases().linhas_na_meta(["2025-11"], META_2025_11)
    congelado = carregar_baselines().linhas_do_periodo(["2025-11"])

    assert conferir_detalhamento(resultado, linhas, reapurado) is None  # type: ignore[arg-type]
    assert conferir_detalhamento(resultado, linhas, congelado) == Divergencia(  # type: ignore[arg-type]
        "baseline_divergente", "baseline"
    )


def test_elemento_que_soma_zero_fica_na_decomposicao_sem_aparecer_no_detalhamento() -> None:
    """O harness guarda a chave de um elemento cujas parcelas somam zero (T-241) e omite a parcela
    zero da linha: a conferência não pode recusar o que ele produz."""
    resultado, linhas = legitimo()
    resultado["decomposicao"]["elemento"]["elem.9"] = 0.0

    assert conferir(resultado, linhas) is None


# ---- cada adulteração, recusada com o motivo e a verificação certos ----


def _matricula_a_mais(resultado: dict[str, Any], linhas: dict[str, Any]) -> None:
    competencia, matricula = alterada(linhas)
    linhas[competencia]["MATRIC-999999"] = copy.deepcopy(linhas[competencia][matricula])


def _matricula_a_menos(resultado: dict[str, Any], linhas: dict[str, Any]) -> None:
    del linhas["2025-11"][inalterada(linhas, "2025-11")]


def _competencia_a_mais(resultado: dict[str, Any], linhas: dict[str, Any]) -> None:
    linhas["2026-01"] = copy.deepcopy(linhas["2025-12"])


def _competencia_a_menos(resultado: dict[str, Any], linhas: dict[str, Any]) -> None:
    del linhas["2025-08"]


def _comissao_do_baseline_alterada(resultado: dict[str, Any], linhas: dict[str, Any]) -> None:
    competencia = "2025-10"
    somar(linhas, competencia, inalterada(linhas, competencia), "comissao_baseline", "0.01")


def _loja_trocada(resultado: dict[str, Any], linhas: dict[str, Any]) -> None:
    competencia, matricula = alterada(linhas)
    linha = linhas[competencia][matricula]
    linha["cod_loja"] = "1" if linha["cod_loja"] != "1" else "2"


def _marca_trocada(resultado: dict[str, Any], linhas: dict[str, Any]) -> None:
    competencia, matricula = alterada(linhas)
    linha = linhas[competencia][matricula]
    linha["cod_marca"] = "10" if linha["cod_marca"] != "10" else "20"


def _cargo_trocado(resultado: dict[str, Any], linhas: dict[str, Any]) -> None:
    competencia, matricula = alterada(linhas)
    linha = linhas[competencia][matricula]
    linha["cod_cargo"] = "100" if linha["cod_cargo"] != "100" else "200"


def _baseline_redistribuido_preservando_o_total(
    resultado: dict[str, Any], linhas: dict[str, Any]
) -> None:
    """Dez reais de baseline passam de uma matrícula a outra, com a diferença e a contribuição de
    cada uma acompanhando: os totais, as quebras e a coerência de cada linha continuam fechando, e
    só o baseline do worker denuncia (o que a conferência do total da T-066 não pegava)."""
    competencia = "2025-11"
    da, para = [m for m, linha in linhas[competencia].items() if linha["contribuicoes"]][:2]
    for matricula, valor in ((da, "10.00"), (para, "-10.00")):
        somar(linhas, competencia, matricula, "comissao_baseline", valor)
        somar(linhas, competencia, matricula, "diferenca", str(-Decimal(valor)))
        contribuicoes = linhas[competencia][matricula]["contribuicoes"]
        elemento = next(iter(contribuicoes))
        contribuicoes[elemento] = float(Decimal(str(contribuicoes[elemento])) - Decimal(valor))


def _comissao_simulada_alterada_sem_ajustar_o_total(
    resultado: dict[str, Any], linhas: dict[str, Any]
) -> None:
    competencia, matricula = alterada(linhas)
    somar(linhas, competencia, matricula, "comissao_simulada", "100.00")


def _diferenca_que_nao_fecha_com_as_comissoes(
    resultado: dict[str, Any], linhas: dict[str, Any]
) -> None:
    competencia, matricula = alterada(linhas)
    somar(linhas, competencia, matricula, "diferenca", "0.01")


def _contribuicao_que_nao_fecha_com_a_diferenca(
    resultado: dict[str, Any], linhas: dict[str, Any]
) -> None:
    competencia, matricula = alterada(linhas)
    contribuicoes = linhas[competencia][matricula]["contribuicoes"]
    elemento = next(iter(contribuicoes))
    contribuicoes[elemento] = float(Decimal(str(contribuicoes[elemento])) + Decimal("0.01"))


def _contribuicao_movida_entre_elementos(resultado: dict[str, Any], linhas: dict[str, Any]) -> None:
    """Cada linha continua fechando, mas a quebra por elemento não é mais a soma das linhas."""
    competencia, matricula = alterada(linhas)
    contribuicoes = linhas[competencia][matricula]["contribuicoes"]
    primeiro, segundo = sorted(contribuicoes)
    contribuicoes[primeiro] = float(Decimal(str(contribuicoes[primeiro])) + Decimal("1.00"))
    contribuicoes[segundo] = float(Decimal(str(contribuicoes[segundo])) - Decimal("1.00"))


ADULTERACOES_DO_BASELINE: dict[str, Adulteracao] = {
    "matricula a mais": _matricula_a_mais,
    "matricula a menos": _matricula_a_menos,
    "competencia a mais": _competencia_a_mais,
    "competencia a menos": _competencia_a_menos,
    "comissao do baseline alterada": _comissao_do_baseline_alterada,
    "loja trocada": _loja_trocada,
    "marca trocada": _marca_trocada,
    "cargo trocado": _cargo_trocado,
    "baseline redistribuido preservando o total": _baseline_redistribuido_preservando_o_total,
}

ADULTERACOES_DA_COERENCIA: dict[str, tuple[Adulteracao, str]] = {
    "comissao simulada alterada sem ajustar o total": (
        _comissao_simulada_alterada_sem_ajustar_o_total,
        "soma_do_detalhamento",
    ),
    "diferenca que nao fecha com as comissoes": (
        _diferenca_que_nao_fecha_com_as_comissoes,
        "diferencas",
    ),
    "contribuicao que nao fecha com a diferenca": (
        _contribuicao_que_nao_fecha_com_a_diferenca,
        "contribuicoes",
    ),
    "contribuicao movida entre elementos": (_contribuicao_movida_entre_elementos, "quebras"),
}


@pytest.mark.parametrize(
    "adulterar", ADULTERACOES_DO_BASELINE.values(), ids=ADULTERACOES_DO_BASELINE
)
def test_detalhamento_que_nao_e_o_baseline_do_worker_e_baseline_divergente(
    adulterar: Adulteracao,
) -> None:
    resultado, linhas = legitimo()

    adulterar(resultado, linhas)

    assert conferir(resultado, linhas) == Divergencia("baseline_divergente", "baseline")


@pytest.mark.parametrize(
    ("adulterar", "verificacao"),
    ADULTERACOES_DA_COERENCIA.values(),
    ids=ADULTERACOES_DA_COERENCIA,
)
def test_detalhamento_incoerente_e_recusado_pela_verificacao_que_falha(
    adulterar: Adulteracao, verificacao: str
) -> None:
    resultado, linhas = legitimo()

    adulterar(resultado, linhas)

    assert conferir(resultado, linhas) == Divergencia("resultado_incoerente", verificacao)  # type: ignore[arg-type]


QUEBRAS = [
    "elemento",
    "loja",
    "marca",
    "cargo",
    "competencia",
    "matricula",
    "loja_absoluto",
    "competencia_absoluto",
]


@pytest.mark.parametrize("quebra", QUEBRAS)
def test_cada_quebra_alterada_e_resultado_incoerente(quebra: str) -> None:
    resultado, linhas = legitimo()
    valores = resultado["decomposicao"][quebra]
    chave = next(iter(valores))
    valores[chave] = float(Decimal(str(valores[chave])) + Decimal("0.01"))

    assert conferir(resultado, linhas) == Divergencia("resultado_incoerente", "quebras")


@pytest.mark.parametrize("quebra", QUEBRAS)
def test_quebra_com_chave_a_mais_e_resultado_incoerente(quebra: str) -> None:
    """Uma chave que nenhuma linha produz, com valor diferente de zero. Na quebra por elemento,
    uma chave com zero é o elemento que soma zero, e o harness a produz."""
    resultado, linhas = legitimo()
    resultado["decomposicao"][quebra]["9999"] = 0.01

    assert conferir(resultado, linhas) == Divergencia("resultado_incoerente", "quebras")


@pytest.mark.parametrize("quebra", QUEBRAS)
def test_quebra_sem_uma_chave_e_resultado_incoerente(quebra: str) -> None:
    resultado, linhas = legitimo()
    valores = resultado["decomposicao"][quebra]
    del valores[next(k for k, v in valores.items() if v)]

    assert conferir(resultado, linhas) == Divergencia("resultado_incoerente", "quebras")


@pytest.mark.parametrize("quebra", ["matricula", "loja_absoluto", "competencia_absoluto"])
def test_sucesso_sem_quebra_absoluta_e_resultado_incoerente(quebra: str) -> None:
    """O contrato as deixa opcionais pelos resultados gravados antes delas; o harness sempre as
    produz, e um sucesso sem elas não é o que ele devolveria."""
    resultado, linhas = legitimo()
    del resultado["decomposicao"][quebra]

    assert conferir(resultado, linhas) == Divergencia("resultado_incoerente", "quebras")


def test_as_verificacoes_sao_um_conjunto_fechado_na_ordem_da_conferencia() -> None:
    assert VERIFICACOES == (
        "baseline",
        "soma_do_detalhamento",
        "diferencas",
        "contribuicoes",
        "quebras",
    )
