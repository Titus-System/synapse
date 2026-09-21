"""O julgamento do resultado contra o baseline e o orçamento (T-066).

Cada teste monta o resultado que o harness produziria para um baseline real (os totais são
os do manifesto, conferidos pelo worker) e exige **classe, motivo e veredito**. O que está em
jogo é o número que o usuário vai ler como "cabe" ou "não cabe" no orçamento, e o que o
impede de vir de um total adulterado.
"""

import copy
import json
from decimal import Decimal
from typing import Any

import pytest

from app.execucao.baseline import BaselinesCongelados, carregar_baselines
from app.execucao.coleta import DesfechoClassificado, classificar, classificar_falha_de_infra
from app.execucao.schema import validador
from app.execucao.veredito import decidir_veredito, julgar
from tests.app.execucao.envelopes import (
    ASSERCAO_OK,
    ASSERCAO_VIOLADA,
    FALHA,
    PAYLOAD,
    RESULTADO,
    envelope,
    saida,
)

BASELINE_2025_11 = "508382.32"
BASELINE_2025_08_11 = "871403.78"


def totais(baseline: str, simulado: str, /) -> dict[str, float]:
    """Os totais como o harness os produz: centavos exatos, diferença e fração sobre eles."""
    base, sim = Decimal(baseline), Decimal(simulado)
    diferenca = sim - base
    return {
        "baseline": float(base),
        "simulado": float(sim),
        "diferenca_abs": float(diferenca),
        "diferenca_pct": float(diferenca / base) if base else 0.0,
    }


def sucesso(baseline: str, simulado: str, /, **mudancas: Any) -> DesfechoClassificado:
    resultado = copy.deepcopy(RESULTADO)
    resultado["totais"] = totais(baseline, simulado) | mudancas
    return DesfechoClassificado("sucesso", "ok", [ASSERCAO_OK], resultado=resultado)


def julgar_2025_11(desfecho: DesfechoClassificado, orcamento: float = 600000.0) -> Any:
    return julgar(desfecho, ["2025-11"], orcamento, carregar_baselines())


# ---- o veredito ----


def test_total_abaixo_do_orcamento_e_viavel() -> None:
    julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"), 600000.0)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "sucesso",
        "ok",
        "viavel",
    )


def test_total_acima_do_orcamento_e_inviavel() -> None:
    julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, "520000.01"), 520000.0)

    assert (julgamento.classe, julgamento.veredito) == ("sucesso", "inviavel")


def test_total_exatamente_igual_ao_orcamento_e_viavel() -> None:
    """DEC-093: cabe no orçamento inclui gastar exatamente o orçamento."""
    julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"), 520000.0)

    assert (julgamento.classe, julgamento.veredito) == ("sucesso", "viavel")


@pytest.mark.parametrize(
    ("simulado", "orcamento", "esperado"),
    [
        (492100.0, 485000.0, "inviavel"),
        (480312.0, 485000.0, "viavel"),
        (485000.0, 485000.0, "viavel"),
        (485000.01, 485000.0, "inviavel"),
        (484999.99, 485000.0, "viavel"),
        (0.3, 0.3, "viavel"),
        (0.0, 0.0, "viavel"),
        (0.01, 0.0, "inviavel"),
        (1305396.25, 1305396.25, "viavel"),
        (1305396.26, 1305396.25, "inviavel"),
    ],
)
def test_a_fronteira_do_orcamento(simulado: float, orcamento: float, esperado: str) -> None:
    assert decidir_veredito(simulado, orcamento) == esperado


def test_o_orcamento_com_fracao_de_centavo_nao_e_arredondado() -> None:
    """Arredondar 484999.995 para o centavo daria 485000.00 e pintaria de viável um total que
    passa do que o usuário informou."""
    assert decidir_veredito(485000.0, 484999.995) == "inviavel"
    assert decidir_veredito(484999.99, 484999.995) == "viavel"


def test_o_veredito_confronta_o_total_e_nao_a_diferenca() -> None:
    """A diferença é 11.617,68, muito abaixo do orçamento de 15.000,00; é o total, acima dele,
    que o orçamento confronta."""
    julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"), 15000.0)

    assert julgamento.veredito == "inviavel"


# ---- a diferença acompanha o veredito ----


def test_a_diferenca_absoluta_e_a_percentual_acompanham_o_veredito() -> None:
    desfecho = sucesso(BASELINE_2025_11, "520000.00")

    julgamento = julgar_2025_11(desfecho, 485000.0)

    assert julgamento.totais == {
        "baseline": 508382.32,
        "simulado": 520000.0,
        "diferenca_abs": 11617.68,
        "diferenca_pct": float(Decimal("11617.68") / Decimal("508382.32")),
        "orcamento": 485000.0,
    }
    assert julgamento.veredito == "inviavel"


def test_periodo_de_varias_competencias_confere_a_soma_dos_baselines() -> None:
    desfecho = sucesso(BASELINE_2025_08_11, "880000.00")

    julgamento = julgar(desfecho, ["2025-08", "2025-11"], 900000.0, carregar_baselines())

    assert (julgamento.classe, julgamento.veredito) == ("sucesso", "viavel")


def test_o_resultado_julgado_e_o_do_container_mais_o_orcamento() -> None:
    """O worker confere e acrescenta; não recompõe. A decomposição é o mesmo objeto, e o
    resultado do container segue sem o campo que ele não tem como conhecer."""
    desfecho = sucesso(BASELINE_2025_11, "520000.00")
    assert desfecho.resultado is not None

    julgamento = julgar_2025_11(desfecho, 485000.0)

    assert julgamento.resultado is not None
    assert julgamento.resultado["decomposicao"] is desfecho.resultado["decomposicao"]
    assert julgamento.resultado["assercoes"] == desfecho.resultado["assercoes"]
    assert "orcamento" not in desfecho.resultado["totais"]
    assert julgamento.resultado["totais"]["orcamento"] == 485000.0


def test_o_resultado_julgado_valida_inteiro_contra_o_schema_sem_acrescimo() -> None:
    """É o que a T-067 grava: `resultado-simulacao.schema.json` completo, com o orçamento."""
    julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"), 485000.0)

    assert list(validador().iter_errors(julgamento.resultado)) == []


# ---- indeterminado: sem número confiável não há julgamento ----


@pytest.mark.parametrize(
    "desfecho",
    [
        DesfechoClassificado("assercao_violada", "assercao", [ASSERCAO_VIOLADA]),
        DesfechoClassificado("erro_codigo", "excecao", erro=FALHA),
        DesfechoClassificado("erro_codigo", "timeout"),
        DesfechoClassificado("erro_codigo", "envelope_invalido"),
        DesfechoClassificado("erro_codigo", "resultado_fora_do_schema", problemas=("$.x: type",)),
        classificar_falha_de_infra(),
    ],
    ids=["assercao_violada", "excecao", "timeout", "envelope", "schema", "erro_infra"],
)
def test_desfecho_que_nao_e_sucesso_e_indeterminado_e_nao_inviavel(
    desfecho: DesfechoClassificado,
) -> None:
    julgamento = julgar_2025_11(desfecho, 1.0)

    assert julgamento.veredito == "indeterminado"
    assert (julgamento.classe, julgamento.motivo) == (desfecho.classe, desfecho.motivo)
    assert julgamento.resultado is None and julgamento.totais is None


# ---- a conferência contra o baseline congelado ----


@pytest.mark.parametrize(
    "desfecho",
    [
        pytest.param(sucesso("508382.33", "520000.00"), id="um centavo a mais no baseline"),
        pytest.param(sucesso("508382.31", "520000.00"), id="um centavo a menos no baseline"),
        pytest.param(sucesso("698465.53", "720000.00"), id="baseline de outra competencia"),
        pytest.param(sucesso(BASELINE_2025_11, "520000.00", diferenca_abs=11617.69), id="abs"),
        pytest.param(sucesso(BASELINE_2025_11, "520000.00", diferenca_pct=0.0228), id="pct"),
        pytest.param(sucesso(BASELINE_2025_11, "520000.00", simulado=520000.01), id="simulado"),
    ],
)
def test_totais_que_nao_batem_com_o_baseline_do_worker_sao_erro_do_codigo(
    desfecho: DesfechoClassificado,
) -> None:
    julgamento = julgar_2025_11(desfecho, 999999999.0)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "baseline_divergente",
        "indeterminado",
    )
    assert julgamento.resultado is None


def test_competencia_sem_baseline_no_worker_e_divergencia() -> None:
    """O harness não produz sucesso para uma competência que a imagem não tem; se produziu, a
    imagem tem um baseline que o worker não tem, e o número não tem com o que ser conferido."""
    baselines = BaselinesCongelados({"2025-11": Decimal(BASELINE_2025_11)})

    julgamento = julgar(sucesso(BASELINE_2025_11, "520000.00"), ["2026-01"], 1.0, baselines)

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "baseline_divergente")


def test_baseline_zero_tem_fracao_zero_como_na_t035() -> None:
    baselines = BaselinesCongelados({"2025-11": Decimal("0.00")})
    desfecho = sucesso("0.00", "10.00")

    julgamento = julgar(desfecho, ["2025-11"], 100.0, baselines)

    assert (julgamento.classe, julgamento.veredito) == ("sucesso", "viavel")


# ---- pela cadeia inteira: o que a T-065 entrega é o que a T-066 julga ----


def _por_classificar(baseline: str, simulado: str) -> DesfechoClassificado:
    resultado = copy.deepcopy(RESULTADO)
    resultado["totais"] = totais(baseline, simulado)
    dados = envelope(competencias=PAYLOAD.competencias, resultado=resultado)
    return classificar(saida(dados), PAYLOAD, 485000.0)


def test_o_desfecho_classificado_de_sucesso_e_julgado_sem_o_acrescimo_da_t065() -> None:
    desfecho = _por_classificar("871403.78", "880000.00")
    assert desfecho.classe == "sucesso"

    julgamento = julgar(desfecho, PAYLOAD.competencias, 485000.0, carregar_baselines())

    assert (julgamento.classe, julgamento.veredito) == ("sucesso", "inviavel")
    assert julgamento.totais is not None and julgamento.totais["orcamento"] == 485000.0


# ---- o veredito nunca contradiz a api ----


@pytest.mark.parametrize("orcamento", [0.0, 480000.0, 520000.0, 600000.0])
@pytest.mark.parametrize("simulado", ["500000.00", "520000.00", "540000.00"])
def test_sucesso_nunca_sai_indeterminado_e_o_resto_sempre_sai(
    simulado: str, orcamento: float
) -> None:
    """A api lê `sucesso` + `indeterminado` como número confiável ainda sem julgamento; o
    worker nunca emite essa combinação."""
    julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, simulado), orcamento)

    assert julgamento.classe == "sucesso"
    assert julgamento.veredito in {"viavel", "inviavel"}
    assert json.dumps(julgamento.totais)  # números finitos, serializáveis
