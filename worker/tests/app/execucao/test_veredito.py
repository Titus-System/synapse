"""O julgamento do resultado contra o baseline, a cobertura e o orçamento (T-066, T-241).

Cada teste monta o resultado que o harness produziria para um baseline real (os totais são
os do manifesto, conferidos pelo worker) e exige **classe, motivo e veredito**. O que está em
jogo é o número que o usuário vai ler como "cabe" ou "não cabe" no orçamento, e o que o
impede de vir de um total adulterado.
"""

import dataclasses
import json
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest

from app.core.metrics.global_metrics import DESFECHOS_DA_EXECUCAO
from app.execucao.baseline import BaselinesCongelados, LinhaDoBaseline, carregar_baselines
from app.execucao.bases import carregar_bases
from app.execucao.coleta import DesfechoClassificado, classificar, classificar_falha_de_infra
from app.execucao.schema import validador
from app.execucao.veredito import (
    decidir_veredito,
    desfecho_da_execucao,
    julgamento_de_infra,
    julgar,
)
from app.mensageria.contracts import AlcanceDaRegra
from tests.app.esquemas import erros_do_dominio
from tests.app.execucao.envelopes import (
    ASSERCAO_OK,
    ASSERCAO_VIOLADA,
    FALHA,
    PAYLOAD,
    envelope,
    linhas_para,
    montar_sobre,
    resultado_para,
    saida,
)

BASELINE_2025_11 = "508382.32"
BASELINE_2025_08_11 = "871403.78"
# A soma de vlr_venda de 2025-11 no dataset canônico, em centavos (T-270).
VENDAS_2025_11 = 13271681.51
# O baseline de 2025-11 reapurado sobre as vendas escaladas até 10% acima do total histórico, e
# essa meta. O total vem do motor congelado (test_escalonamento.py e test_bases.py o conferem).
BASELINE_NA_META_2025_11 = "558870.26"
META_2025_11 = float(Decimal(str(VENDAS_2025_11)) * Decimal("1.1"))


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


def sucesso(
    baseline: str, simulado: str, /, *, competencias: Sequence[str] = ("2025-11",), **mudancas: Any
) -> DesfechoClassificado:
    """O resultado legítimo das competências com este simulado, sobre o baseline reapurado na meta
    quando `baseline` é o de 2025-11 na meta, e sobre o congelado nos demais. Um `baseline` que não
    é o do worker, ou `mudancas`, adulteram só os totais: o detalhamento segue o legítimo."""
    periodo = list(competencias)
    meta_venda = META_2025_11 if baseline == BASELINE_NA_META_2025_11 else None
    if meta_venda is not None:
        referencia = Decimal(BASELINE_NA_META_2025_11)
    else:
        referencia = carregar_baselines().total(periodo)
    a_mais = str(Decimal(simulado) - referencia)
    resultado = resultado_para(periodo, a_mais, meta_venda=meta_venda)
    resultado["totais"] = totais(baseline, simulado) | mudancas
    linhas = linhas_para(periodo, a_mais, meta_venda=meta_venda)
    return DesfechoClassificado("sucesso", "ok", [ASSERCAO_OK], resultado=resultado, linhas=linhas)


def julgar_2025_11(
    desfecho: DesfechoClassificado,
    orcamento: float | None = 600000.0,
    *,
    elementos_exigidos: Sequence[str] | None = None,
    alcance: AlcanceDaRegra | None = None,
) -> Any:
    return julgar(
        desfecho,
        ["2025-11"],
        orcamento,
        carregar_baselines(),
        elementos_exigidos=elementos_exigidos,
        bases=carregar_bases(),
        alcance=alcance,
    )


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
        "vendas_historicas": VENDAS_2025_11,
        "orcamento": 485000.0,
    }
    assert julgamento.veredito == "inviavel"


def test_periodo_de_varias_competencias_confere_a_soma_dos_baselines() -> None:
    desfecho = sucesso(BASELINE_2025_08_11, "880000.00", competencias=["2025-08", "2025-11"])

    julgamento = julgar(
        desfecho,
        ["2025-08", "2025-11"],
        900000.0,
        carregar_baselines(),
        elementos_exigidos=None,
        bases=carregar_bases(),
    )

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
        DesfechoClassificado(
            "erro_codigo",
            "resultado_fora_do_schema",
            problemas=({"caminho": "$.x", "palavra_chave": "type"},),
        ),
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

    julgamento = julgar(
        sucesso(BASELINE_2025_11, "520000.00"),
        ["2026-01"],
        1.0,
        baselines,
        elementos_exigidos=None,
        bases=carregar_bases(),
    )

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "baseline_divergente")


def test_baseline_zero_tem_fracao_zero_como_na_t035() -> None:
    linhas = {"2025-11": {"MATRIC-1": LinhaDoBaseline("75", "20", "200", Decimal("0.00"))}}
    baselines = BaselinesCongelados({"2025-11": Decimal("0.00")}, linhas)
    montado = montar_sobre(linhas, ["2025-11"], Decimal("10.00"))
    desfecho = DesfechoClassificado(
        "sucesso", "ok", [ASSERCAO_OK], resultado=montado.resultado, linhas=montado.linhas
    )

    julgamento = julgar(
        desfecho, ["2025-11"], 100.0, baselines, elementos_exigidos=None, bases=carregar_bases()
    )

    assert (julgamento.classe, julgamento.veredito) == ("sucesso", "viavel")


# ---- a conferência de cobertura (T-241) ----

# A decomposição do resultado de `sucesso` tem contribuição de nucleo.percentual e de elem.1.
EXIGIDOS_DO_RESULTADO = ["nucleo.percentual", "elem.1"]


def declarando(
    desfecho: DesfechoClassificado, elementos: tuple[str, ...] | None
) -> DesfechoClassificado:
    return dataclasses.replace(desfecho, elementos_implementados=elementos)


def test_cobertura_completa_segue_para_o_veredito_com_o_mesmo_resultado_de_antes() -> None:
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual", "elem.1"))

    conferido = julgar_2025_11(desfecho, 485000.0, elementos_exigidos=EXIGIDOS_DO_RESULTADO)
    sem_conferencia = julgar_2025_11(desfecho, 485000.0, elementos_exigidos=None)

    assert conferido == sem_conferencia
    assert (conferido.classe, conferido.motivo, conferido.veredito) == (
        "sucesso",
        "ok",
        "inviavel",
    )
    assert conferido.cobertura is None
    assert conferido.totais == {
        "baseline": 508382.32,
        "simulado": 520000.0,
        "diferenca_abs": 11617.68,
        "diferenca_pct": float(Decimal("11617.68") / Decimal("508382.32")),
        "vendas_historicas": VENDAS_2025_11,
        "orcamento": 485000.0,
    }


def test_elemento_exigido_que_o_codigo_nao_declara_e_cobertura_incompleta() -> None:
    """elem.2 não tem contribuição nem declaração: ficou sem implementação, e o número que sai
    parece completo sem ele."""
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual", "elem.1"))

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=[*EXIGIDOS_DO_RESULTADO, "elem.2"])

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "cobertura_incompleta",
        "indeterminado",
    )
    assert julgamento.resultado is None
    assert julgamento.cobertura is not None
    assert (julgamento.cobertura.ausentes, julgamento.cobertura.fora_da_regra) == (("elem.2",), ())


def test_elemento_com_contribuicao_e_sem_declaracao_e_cobertura_incompleta() -> None:
    """A decomposição tem elem.1, mas a declaração não: ela precisa descrever o código inteiro."""
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual",))

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=EXIGIDOS_DO_RESULTADO)

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "cobertura_incompleta")
    assert julgamento.cobertura is not None
    assert (julgamento.cobertura.ausentes, julgamento.cobertura.fora_da_regra) == (("elem.1",), ())


def test_contribuicao_de_elemento_que_a_regra_nao_tem_e_cobertura_incompleta_mesmo_declarado() -> (
    None
):
    """elem.1 está declarado e tem contribuição, mas o comando não o exige: é valor atribuído a
    um elemento que a regra não tem."""
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual", "elem.1"))

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=["nucleo.percentual"])

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "cobertura_incompleta")
    assert julgamento.cobertura is not None
    assert (julgamento.cobertura.ausentes, julgamento.cobertura.fora_da_regra) == ((), ("elem.1",))


def test_elemento_fora_da_regra_cujas_contribuicoes_somam_zero_e_cobertura_incompleta() -> None:
    """A chave de um elemento cujas contribuições se anulam fica na decomposição com zero
    (T-035), e a condição é sobre o elemento ter contribuição, não sobre o valor que ela soma."""
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual", "elem.1"))
    assert desfecho.resultado is not None
    desfecho.resultado["decomposicao"]["elemento"]["elem.9"] = 0.0

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=EXIGIDOS_DO_RESULTADO)

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "cobertura_incompleta")
    assert julgamento.cobertura is not None
    assert (julgamento.cobertura.ausentes, julgamento.cobertura.fora_da_regra) == ((), ("elem.9",))


def test_elemento_declarado_sem_contribuicao_e_aceito() -> None:
    """elem.2 é uma exclusão, uma condição de limiar ou não ocorre no período: implementado, sem
    valor próprio, sem chave na decomposição."""
    desfecho = declarando(
        sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual", "elem.1", "elem.2")
    )

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=[*EXIGIDOS_DO_RESULTADO, "elem.2"])

    assert (julgamento.classe, julgamento.motivo) == ("sucesso", "ok")


def test_declarar_a_mais_sem_contribuicao_nao_reprova() -> None:
    desfecho = declarando(
        sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual", "elem.1", "elem.7")
    )

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=EXIGIDOS_DO_RESULTADO)

    assert (julgamento.classe, julgamento.motivo) == ("sucesso", "ok")


def test_codigo_sem_declaracao_num_comando_que_exige_elementos_nao_declarou_nenhum() -> None:
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), None)

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=EXIGIDOS_DO_RESULTADO)

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "cobertura_incompleta")
    assert julgamento.cobertura is not None
    assert julgamento.cobertura.ausentes == ("nucleo.percentual", "elem.1")


def test_comando_sem_elementos_exigidos_julga_codigo_sem_declaracao_como_antes() -> None:
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), None)

    julgamento = julgar_2025_11(desfecho, 485000.0, elementos_exigidos=None)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "sucesso",
        "ok",
        "inviavel",
    )


def test_o_baseline_divergente_e_conferido_antes_da_cobertura() -> None:
    """Com as duas falhas, o motivo é o da integridade do número que saiu do container."""
    desfecho = declarando(sucesso("508382.33", "520000.00"), None)

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=EXIGIDOS_DO_RESULTADO)

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "baseline_divergente")
    assert julgamento.cobertura is None


def test_desfecho_que_nao_e_sucesso_nao_passa_pela_cobertura() -> None:
    desfecho = DesfechoClassificado("assercao_violada", "assercao", [ASSERCAO_VIOLADA])

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=EXIGIDOS_DO_RESULTADO)

    assert (julgamento.classe, julgamento.motivo) == ("assercao_violada", "assercao")
    assert julgamento.cobertura is None


# ---- pela cadeia inteira: o que a T-065 entrega é o que a T-066 julga ----


# ---- a conferência de escopo ----


def _alteradas(desfecho: DesfechoClassificado) -> int:
    """Quantas linhas do detalhamento o código mudou além de um centavo."""
    assert desfecho.linhas is not None
    return sum(
        1
        for colaboradores in desfecho.linhas.values()
        for linha in colaboradores.values()
        if abs(Decimal(str(linha["comissao_simulada"])) - Decimal(str(linha["comissao_baseline"])))
        > Decimal("0.01")
    )


def test_resultado_que_muda_linha_fora_do_alcance_e_erro_codigo_fora_do_escopo() -> None:
    """Nenhuma loja do dataset está no alcance: toda linha que o código mudou está fora dele."""
    desfecho = sucesso(BASELINE_2025_11, "520000.00")

    julgamento = julgar_2025_11(desfecho, alcance=AlcanceDaRegra(loja=["9999"]))

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "fora_do_escopo",
        "indeterminado",
    )
    assert julgamento.resultado is None
    assert julgamento.fora_do_escopo is not None
    assert julgamento.fora_do_escopo.total == _alteradas(desfecho) > 0


def test_alcance_que_cobre_as_linhas_mudadas_julga_como_sem_conferencia() -> None:
    desfecho = sucesso(BASELINE_2025_11, "520000.00")
    vigencia = {"inicio": "2025-08", "fim": "2025-12"}

    conferido = julgar_2025_11(
        desfecho, alcance=AlcanceDaRegra.model_validate({"vigencia": vigencia})
    )

    assert conferido == julgar_2025_11(desfecho)
    assert conferido.fora_do_escopo is None


def test_a_cobertura_e_conferida_antes_do_escopo() -> None:
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual",))

    julgamento = julgar_2025_11(
        desfecho, elementos_exigidos=EXIGIDOS_DO_RESULTADO, alcance=AlcanceDaRegra(loja=["9999"])
    )

    assert julgamento.motivo == "cobertura_incompleta"
    assert julgamento.fora_do_escopo is None


def _por_classificar(baseline: str, simulado: str) -> DesfechoClassificado:
    a_mais = str(Decimal(simulado) - Decimal(baseline))
    dados = envelope(
        competencias=PAYLOAD.competencias,
        resultado=resultado_para(PAYLOAD.competencias, a_mais),
        linhas=linhas_para(PAYLOAD.competencias, a_mais),
    )
    return classificar(saida(dados), PAYLOAD, 485000.0)


def test_o_desfecho_classificado_de_sucesso_e_julgado_sem_o_acrescimo_da_t065() -> None:
    desfecho = _por_classificar("871403.78", "880000.00")
    assert desfecho.classe == "sucesso"

    julgamento = julgar(
        desfecho,
        PAYLOAD.competencias,
        485000.0,
        carregar_baselines(),
        elementos_exigidos=None,
        bases=carregar_bases(),
    )

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


# ---- sem orçamento: as mesmas conferências, sem veredito (T-281) ----


def test_sem_orcamento_o_sucesso_conferido_sai_sem_veredito_e_sem_totais_orcamento() -> None:
    desfecho = sucesso(BASELINE_2025_11, "520000.00")
    assert desfecho.resultado is not None

    julgamento = julgar_2025_11(desfecho, None)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == ("sucesso", "ok", None)
    assert julgamento.totais == {
        "baseline": 508382.32,
        "simulado": 520000.0,
        "diferenca_abs": 11617.68,
        "diferenca_pct": float(Decimal("11617.68") / Decimal("508382.32")),
        "vendas_historicas": VENDAS_2025_11,
    }
    assert julgamento.resultado is not None
    assert julgamento.resultado["decomposicao"] is desfecho.resultado["decomposicao"]
    assert list(validador().iter_errors(julgamento.resultado)) == []


@pytest.mark.parametrize(
    "desfecho",
    [
        pytest.param(sucesso("508382.33", "520000.00"), id="um centavo a mais no baseline"),
        pytest.param(sucesso("698465.53", "720000.00"), id="baseline de outra competencia"),
        pytest.param(sucesso(BASELINE_2025_11, "520000.00", diferenca_abs=11617.69), id="abs"),
        pytest.param(sucesso(BASELINE_2025_11, "520000.00", simulado=520000.01), id="simulado"),
    ],
)
def test_sem_orcamento_baseline_adulterado_continua_baseline_divergente(
    desfecho: DesfechoClassificado,
) -> None:
    julgamento = julgar_2025_11(desfecho, None)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "baseline_divergente",
        "indeterminado",
    )
    assert julgamento.resultado is None


def test_sem_orcamento_a_cobertura_continua_conferida() -> None:
    """O desfecho do teste não declara elemento nenhum: o exigido fica ausente."""
    julgamento = julgar_2025_11(
        sucesso(BASELINE_2025_11, "520000.00"), None, elementos_exigidos=["nucleo.percentual"]
    )

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "cobertura_incompleta")
    assert julgamento.resultado is None


def test_sem_orcamento_o_que_nao_e_sucesso_continua_indeterminado() -> None:
    desfecho = DesfechoClassificado("assercao_violada", "assercao", [ASSERCAO_VIOLADA])

    julgamento = julgar_2025_11(desfecho, None)

    assert (julgamento.classe, julgamento.veredito) == ("assercao_violada", "indeterminado")


# ---- o desfecho da execução na métrica ----


@pytest.mark.parametrize(
    ("orcamento", "esperado"),
    [(600000.0, "viavel"), (485000.0, "inviavel"), (None, "sem_orcamento")],
)
def test_o_desfecho_de_um_sucesso_e_o_veredito_ou_sem_orcamento(
    orcamento: float | None, esperado: str
) -> None:
    julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"), orcamento)

    assert desfecho_da_execucao(julgamento) == esperado


def test_o_desfecho_do_que_nao_e_sucesso_e_a_classe() -> None:
    divergente = julgar_2025_11(sucesso("508382.33", "520000.00"), None)
    violada = julgar_2025_11(DesfechoClassificado("assercao_violada", "assercao", []), 1.0)

    assert desfecho_da_execucao(divergente) == "erro_codigo"
    assert desfecho_da_execucao(violada) == "assercao_violada"
    assert desfecho_da_execucao(julgamento_de_infra()) == "erro_infra"


def test_os_desfechos_da_metrica_sao_um_conjunto_fechado() -> None:
    assert set(DESFECHOS_DA_EXECUCAO) == {
        "viavel",
        "inviavel",
        "sem_orcamento",
        "assercao_violada",
        "erro_codigo",
        "erro_infra",
    }


# ---- na meta de venda: a conferência contra o baseline que o worker reapurou (T-270) ----


def julgar_na_meta(desfecho: DesfechoClassificado, orcamento: float | None = 600000.0) -> Any:
    return julgar(
        desfecho,
        ["2025-11"],
        orcamento,
        carregar_baselines(),
        elementos_exigidos=None,
        bases=carregar_bases(),
        baseline_na_meta=carregar_bases().linhas_na_meta(["2025-11"], META_2025_11),
        meta_venda=META_2025_11,
    )


def test_na_meta_o_baseline_e_conferido_contra_o_que_o_worker_reapurou() -> None:
    julgamento = julgar_na_meta(sucesso(BASELINE_NA_META_2025_11, "570000.00"), 600000.0)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "sucesso",
        "ok",
        "viavel",
    )
    assert julgamento.totais == {
        "baseline": 558870.26,
        "simulado": 570000.0,
        "diferenca_abs": 11129.74,
        "diferenca_pct": float(Decimal("11129.74") / Decimal(BASELINE_NA_META_2025_11)),
        "vendas_historicas": VENDAS_2025_11,
        "orcamento": 600000.0,
    }
    assert list(validador().iter_errors(julgamento.resultado)) == []


@pytest.mark.parametrize(
    "desfecho",
    [
        pytest.param(sucesso(BASELINE_2025_11, "570000.00"), id="baseline congelado"),
        pytest.param(sucesso("558870.27", "570000.00"), id="um centavo a mais"),
        pytest.param(sucesso("559220.55", "570000.00"), id="baseline proporcional"),
        pytest.param(
            sucesso(BASELINE_NA_META_2025_11, "570000.00", diferenca_abs=11129.75), id="abs"
        ),
    ],
)
def test_na_meta_baseline_que_nao_e_o_reapurado_e_divergente(
    desfecho: DesfechoClassificado,
) -> None:
    """Na meta, nem o congelado vale: o container que devolve o baseline histórico (ou o
    proporcional, 1,1 vez o congelado) não simulou na meta, e o número não é o pedido."""
    julgamento = julgar_na_meta(desfecho)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "baseline_divergente",
        "indeterminado",
    )
    assert julgamento.resultado is None


@pytest.mark.parametrize(
    ("orcamento", "veredito"),
    [(570000.0, "viavel"), (569999.99, "inviavel")],
    ids=["cabe", "acima"],
)
def test_na_meta_o_veredito_compara_o_simulado_na_meta(orcamento: float, veredito: str) -> None:
    julgamento = julgar_na_meta(sucesso(BASELINE_NA_META_2025_11, "570000.00"), orcamento)

    assert (julgamento.classe, julgamento.veredito) == ("sucesso", veredito)


def test_na_meta_sem_orcamento_sai_sem_veredito() -> None:
    julgamento = julgar_na_meta(sucesso(BASELINE_NA_META_2025_11, "570000.00"), None)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == ("sucesso", "ok", None)
    assert julgamento.totais is not None and "orcamento" not in julgamento.totais
    assert julgamento.totais["vendas_historicas"] == VENDAS_2025_11
    assert desfecho_da_execucao(julgamento) == "sem_orcamento"


@pytest.mark.parametrize("na_meta", [False, True], ids=["historico", "meta"])
@pytest.mark.parametrize("orcamento", [600000.0, None], ids=["com orcamento", "sem orcamento"])
def test_todo_sucesso_leva_o_total_de_vendas_das_competencias(
    na_meta: bool, orcamento: float | None
) -> None:
    """O total histórico, antes da escala, com e sem meta: é o divisor do fator e o que a tela
    mostra ao lado da meta. Vem das bases do worker, nunca do container."""
    if na_meta:
        julgamento = julgar_na_meta(sucesso(BASELINE_NA_META_2025_11, "570000.00"), orcamento)
    else:
        julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"), orcamento)

    assert julgamento.totais is not None
    assert julgamento.totais["vendas_historicas"] == VENDAS_2025_11
    assert erros_do_dominio("resultado-totais", dict(julgamento.totais)) == []


# ---- o total vendido de cada linha do detalhamento (T-282) ----


def test_cada_linha_do_sucesso_leva_o_total_vendido_das_bases_do_worker() -> None:
    """MATRIC-1 vendeu R$ 24.785,01 em novembro, e MATRIC-16 não vendeu: quem não vendeu no mês
    fica com zero, e não sem o campo, que é o que distingue as linhas gravadas antes dele. O resto
    da linha segue como veio do container."""
    desfecho = sucesso(BASELINE_2025_11, "520000.00")
    assert desfecho.linhas is not None
    novembro = desfecho.linhas["2025-11"]

    julgamento = julgar_2025_11(desfecho)

    assert julgamento.classe == "sucesso" and julgamento.linhas is not None
    julgadas = julgamento.linhas["2025-11"]
    assert julgadas["MATRIC-1"]["vendas"] == 24785.01
    assert julgadas["MATRIC-16"]["vendas"] == 0.0
    assert julgadas.keys() == novembro.keys()
    for matricula, linha in novembro.items():
        assert {k: v for k, v in julgadas[matricula].items() if k != "vendas"} == linha
    assert erros_do_dominio("resultado-linhas", julgamento.linhas) == []


def test_na_meta_cada_linha_leva_as_vendas_escaladas_ate_a_meta() -> None:
    """As comissões da linha foram apuradas sobre as vendas escaladas, e é essa venda que ela
    mostra. ``totais.vendas_historicas`` continua com o total antes da escala."""
    julgamento = julgar_na_meta(sucesso(BASELINE_NA_META_2025_11, "570000.00"))

    assert julgamento.linhas is not None and julgamento.totais is not None
    fator = Decimal(str(META_2025_11)) / Decimal(str(VENDAS_2025_11))
    esperado = (Decimal("24785.01") * fator).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert julgamento.linhas["2025-11"]["MATRIC-1"]["vendas"] == float(esperado) == 27263.51
    assert julgamento.totais["vendas_historicas"] == VENDAS_2025_11


def test_desfecho_recusado_no_julgamento_nao_leva_detalhamento() -> None:
    julgamento = julgar_2025_11(sucesso("1.00", "2.00"))

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "baseline_divergente")
    assert julgamento.linhas is None


def test_baseline_na_meta_sem_a_meta_do_comando_e_recusado() -> None:
    """Sem a meta, as linhas levariam a venda histórica ao lado de comissões apuradas na meta."""
    with pytest.raises(ValueError, match="vêm juntos"):
        julgar(
            sucesso(BASELINE_NA_META_2025_11, "570000.00"),
            ["2025-11"],
            None,
            carregar_baselines(),
            elementos_exigidos=None,
            bases=carregar_bases(),
            baseline_na_meta=carregar_bases().linhas_na_meta(["2025-11"], META_2025_11),
        )


# ---- a conferência do detalhamento e das quebras (T-262) ----


def test_o_sucesso_conferido_sai_coerente_e_sem_verificacao_reprovada() -> None:
    julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"))

    assert (julgamento.classe, julgamento.conferencia, julgamento.verificacao) == (
        "sucesso",
        "coerente",
        None,
    )


def test_o_que_nao_e_sucesso_nao_passa_pela_conferencia() -> None:
    julgamento = julgar_2025_11(classificar(saida(envelope("erro_codigo"), 1), PAYLOAD, None))

    assert (julgamento.conferencia, julgamento.verificacao) == (None, None)


def test_total_do_baseline_adulterado_e_recusado_pela_verificacao_do_baseline() -> None:
    julgamento = julgar_2025_11(sucesso("508382.33", "520000.00"))

    assert (julgamento.motivo, julgamento.conferencia, julgamento.verificacao) == (
        "baseline_divergente",
        "baseline_divergente",
        "baseline",
    )


def test_linha_do_baseline_adulterada_e_baseline_divergente_sem_veredito_nem_linhas() -> None:
    desfecho = sucesso(BASELINE_2025_11, "520000.00")
    assert desfecho.linhas is not None
    linha = desfecho.linhas["2025-11"]["MATRIC-16"]
    linha["comissao_baseline"] = float(Decimal(str(linha["comissao_baseline"])) + Decimal("0.01"))

    julgamento = julgar_2025_11(desfecho)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "baseline_divergente",
        "indeterminado",
    )
    assert (julgamento.conferencia, julgamento.verificacao) == ("baseline_divergente", "baseline")
    assert julgamento.resultado is None and julgamento.linhas is None


def test_quebra_adulterada_e_resultado_incoerente_sem_veredito_nem_linhas() -> None:
    desfecho = sucesso(BASELINE_2025_11, "520000.00")
    assert desfecho.resultado is not None
    loja = desfecho.resultado["decomposicao"]["loja"]
    chave = next(iter(loja))
    loja[chave] = float(Decimal(str(loja[chave])) + Decimal("0.01"))

    julgamento = julgar_2025_11(desfecho)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "resultado_incoerente",
        "indeterminado",
    )
    assert (julgamento.conferencia, julgamento.verificacao) == ("resultado_incoerente", "quebras")
    assert julgamento.resultado is None and julgamento.linhas is None


def test_a_conferencia_vem_antes_da_cobertura() -> None:
    """Com o detalhamento incoerente, a cobertura nem é conferida: ela lê a quebra por elemento,
    que só vale depois de conferida contra as linhas."""
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual",))
    assert desfecho.linhas is not None
    novembro = desfecho.linhas["2025-11"]
    linha = next(linha for linha in novembro.values() if linha["contribuicoes"])
    linha["diferenca"] = float(Decimal(str(linha["diferenca"])) + Decimal("0.01"))

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=EXIGIDOS_DO_RESULTADO)

    assert (julgamento.motivo, julgamento.verificacao) == ("resultado_incoerente", "diferencas")
    assert julgamento.cobertura is None


def test_a_cobertura_incompleta_vem_de_um_resultado_conferido_coerente() -> None:
    desfecho = declarando(sucesso(BASELINE_2025_11, "520000.00"), ("nucleo.percentual",))

    julgamento = julgar_2025_11(desfecho, elementos_exigidos=EXIGIDOS_DO_RESULTADO)

    assert (julgamento.motivo, julgamento.conferencia) == ("cobertura_incompleta", "coerente")


def test_na_meta_o_detalhamento_sobre_o_baseline_congelado_e_baseline_divergente() -> None:
    """O container que devolve o total reapurado na meta, mas linhas do baseline histórico, não
    simulou na meta linha a linha: só o total não basta."""
    desfecho = sucesso(BASELINE_NA_META_2025_11, "570000.00")
    a_mais = str(Decimal("570000.00") - Decimal(BASELINE_2025_11))
    historico = dataclasses.replace(desfecho, linhas=linhas_para(["2025-11"], a_mais))

    julgamento = julgar_na_meta(historico)

    assert (julgamento.motivo, julgamento.verificacao) == ("baseline_divergente", "baseline")
