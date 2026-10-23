"""A conferência do detalhamento contra a imagem real (T-262).

`test_conferencia.py` prova cada verificação com resultados montados pelo agregador do harness.
Aqui o resultado vem de um container de verdade, pela mesma sequência do consumidor: executar,
classificar e julgar. O que se afirma é que um resultado legítimo do período inteiro passa, e que
um ataque que a conferência do total da T-066 não pegava agora é recusado.
"""

from uuid import uuid4

import pytest

from app.execucao.baseline import carregar_baselines
from app.execucao.bases import carregar_bases
from app.execucao.coleta import classificar
from app.execucao.container import Limites, executar_no_sandbox
from app.execucao.preparo import PayloadContainer
from app.execucao.veredito import Julgamento, julgar

pytestmark = pytest.mark.docker

PERIODO = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
LIMITES = Limites(timeout_s=60.0)

# Cinco por cento a mais para o cargo 100, e só para ele: parte das matrículas muda, o resto não.
REGRA_QUE_ALTERA_PARTE_DAS_MATRICULAS = """
def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    do_cargo = simulada["cod_cargo"] == 100
    simulada.loc[do_cargo, "comissao"] = (simulada.loc[do_cargo, "comissao"] * 1.05).round(2)
    contribuicoes = simulada[do_cargo][
        ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]
    ].copy()
    contribuicoes["elemento_ref"] = "elem.1"
    contribuicoes["delta"] = (
        simulada.loc[do_cargo, "comissao"] - apuracao_base.loc[do_cargo, "comissao"]
    ).round(2).values
    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
"""

# A regra roda no mesmo processo do harness, e o gc entrega os registros do baseline que ele
# guarda (o mesmo caminho de REGRA_QUE_INFLA_O_BASELINE_DO_HARNESS, T-066). Ela move dez reais de
# baseline de uma matrícula para outra: o total não muda, a decomposição reconcilia, e para o
# harness e para a conferência do total é um sucesso. Só a linha a linha denuncia.
REGRA_QUE_REDISTRIBUI_O_BASELINE_DO_HARNESS = """
import gc
def aplicar_regra(bases, apuracao_base, competencias):
    alvo = None
    for objeto in gc.get_objects():
        if (isinstance(objeto, tuple) and len(objeto) == len(apuracao_base) and objeto
                and isinstance(objeto[0], dict) and "comissao" in objeto[0]
                and "cod_marca" in objeto[0]):
            alvo = objeto
            break
    if alvo is None:
        raise RuntimeError("baseline do harness não encontrado")
    doador = next(registro for registro in alvo if registro["comissao"] >= 10)
    receptor = next(registro for registro in alvo if registro is not doador)
    doador["comissao"] = round(doador["comissao"] - 10, 2)
    receptor["comissao"] = round(receptor["comissao"] + 10, 2)
    movido = {
        (doador["matricula"], doador["competencia"]): 10.0,
        (receptor["matricula"], receptor["competencia"]): -10.0,
    }
    contribuicoes = apuracao_base[
        ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]
    ].copy()
    contribuicoes["elemento_ref"] = "elem.1"
    contribuicoes["delta"] = [
        movido.get((linha.matricula, linha.competencia), 0.0)
        for linha in apuracao_base.itertuples()
    ]
    return {"apuracao_simulada": apuracao_base.copy(), "contribuicoes": contribuicoes}
"""


def executar_e_julgar(
    fonte: str, competencias: list[str], imagem: str, orcamento: float | None = None
) -> Julgamento:
    """A sequência do consumidor: executar, classificar e julgar com o orçamento do comando."""
    entrada = PayloadContainer(
        job_id=uuid4(),
        codigo_gerado_id=uuid4(),
        linguagem="python",
        fonte=fonte,
        competencias=competencias,
    )
    desfecho = classificar(
        executar_no_sandbox(entrada, imagem=imagem, limites=LIMITES), entrada, orcamento
    )
    return julgar(
        desfecho,
        competencias,
        orcamento,
        carregar_baselines(),
        elementos_exigidos=None,
        bases=carregar_bases(),
    )


@pytest.mark.parametrize(
    ("orcamento", "veredito"),
    [(None, None), (999999999.0, "viavel"), (1.0, "inviavel")],
    ids=["sem orcamento", "cabe", "acima"],
)
def test_resultado_real_do_periodo_inteiro_que_altera_parte_das_matriculas_e_coerente(
    imagem: str, orcamento: float | None, veredito: str | None
) -> None:
    """Passa na conferência e recebe o veredito como antes dela: o do orçamento, ou nenhum."""
    julgamento = executar_e_julgar(
        REGRA_QUE_ALTERA_PARTE_DAS_MATRICULAS, PERIODO, imagem, orcamento
    )

    assert (julgamento.classe, julgamento.motivo, julgamento.conferencia) == (
        "sucesso",
        "ok",
        "coerente",
    )
    assert julgamento.veredito == veredito
    assert julgamento.linhas is not None and list(julgamento.linhas) == PERIODO
    diferencas = [
        linha["diferenca"] for mes in julgamento.linhas.values() for linha in mes.values()
    ]
    assert any(diferencas) and not all(diferencas)


def test_regra_que_redistribui_o_baseline_preservando_o_total_e_denunciada_linha_a_linha(
    imagem: str,
) -> None:
    julgamento = executar_e_julgar(REGRA_QUE_REDISTRIBUI_O_BASELINE_DO_HARNESS, ["2025-11"], imagem)

    # Controle: para o harness, a classificação e a conferência do total, isto é um sucesso com
    # o baseline certo. Se o harness for endurecido e este assert cair, o ataque deixou de existir
    # por este caminho: adapte o teste, não relaxe a conferência.
    desfecho = julgamento.desfecho
    assert desfecho is not None and desfecho.classe == "sucesso"
    assert desfecho.resultado is not None
    assert desfecho.resultado["totais"]["baseline"] == float(
        carregar_baselines().total(["2025-11"])
    )

    assert (julgamento.classe, julgamento.motivo, julgamento.verificacao) == (
        "erro_codigo",
        "baseline_divergente",
        "baseline",
    )
    assert julgamento.resultado is None and julgamento.linhas is None
