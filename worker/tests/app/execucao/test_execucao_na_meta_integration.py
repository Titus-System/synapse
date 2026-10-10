"""A execução na meta de venda contra a imagem real do sandbox (T-270).

O caminho do consumidor, do comando ao julgamento, com o container de verdade: o harness escala as
vendas e reapura o baseline dentro do container, e o worker confere esse baseline contra a
reapuração que ele mesmo faz, sobre as próprias bases. Os dois lados rodam o mesmo motor sobre os
mesmos dados, e a conferência só passa se chegarem ao mesmo centavo.
"""

import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.execucao.baseline import carregar_baselines
from app.execucao.bases import carregar_bases
from app.execucao.coleta import classificar
from app.execucao.container import Limites, SaidaBruta, executar_no_sandbox
from app.execucao.preparo import preparar_execucao
from app.execucao.registro import linha_do_julgamento
from app.execucao.veredito import Julgamento, julgar
from app.mensageria.contracts import ExecutarCodigo
from app.repositorio.codigos_gerados import CodigoGerado
from tests.app.esquemas import erros_do_dominio
from tests.app.execucao.test_cobertura_integration import REFERENCIA_ADMISSAO
from tests.app.execucao.test_coleta_integration import REGRA_QUE_INFLA_O_BASELINE_DO_HARNESS
from tests.app.sandbox.test_harness import EXEMPLO

pytestmark = pytest.mark.docker

CURTO = Limites(timeout_s=30.0)
COMPETENCIAS = ("2025-08", "2025-09", "2025-10", "2025-11", "2025-12")


def meta_por_fator(competencias: list[str], fator: str) -> float:
    return float(carregar_bases().vendas_historicas(competencias) * Decimal(fator))


def executar_na_meta(
    fonte: str,
    imagem: str,
    competencias: list[str],
    meta_venda: float,
    *,
    orcamento: float | None = 999999999.0,
    elementos_exigidos: list[str] | None = None,
) -> tuple[SaidaBruta, Julgamento]:
    """O caminho do consumidor: a reapuração do worker, o container, a classificação e o
    julgamento contra o baseline que o worker reapurou."""
    job_id, codigo_id = uuid4(), uuid4()
    corpo: dict[str, Any] = {
        "job_id": str(job_id),
        "codigo_gerado_id": str(codigo_id),
        "competencias": competencias,
        "meta_venda": meta_venda,
    }
    if orcamento is not None:
        corpo["orcamento"] = orcamento
    if elementos_exigidos is not None:
        corpo["elementos_exigidos"] = elementos_exigidos
    comando = ExecutarCodigo.model_validate_json(json.dumps(corpo))
    codigo = CodigoGerado(id=codigo_id, job_id=job_id, linguagem="python", fonte=fonte)
    execucao = preparar_execucao(comando, codigo)
    bases = carregar_bases()
    baseline_na_meta = bases.baseline_na_meta(competencias, meta_venda)

    saida = executar_no_sandbox(execucao.payload, imagem=imagem, limites=CURTO)
    desfecho = classificar(saida, execucao.payload, execucao.orcamento)
    julgamento = julgar(
        desfecho,
        execucao.payload.competencias,
        execucao.orcamento,
        carregar_baselines(),
        elementos_exigidos=execucao.elementos_exigidos,
        bases=bases,
        baseline_na_meta=baseline_na_meta,
    )
    return saida, julgamento


def baseline_do_container(saida: SaidaBruta) -> float:
    envelope = json.loads(saida.stdout)
    assert envelope["status"] == "sucesso", envelope["status"]
    return float(envelope["resultado"]["totais"]["baseline"])


@pytest.mark.parametrize(
    "competencias", [["2025-11"], list(COMPETENCIAS)], ids=["novembro", "cinco competencias"]
)
def test_meta_igual_ao_total_historico_reapura_no_container_o_baseline_congelado(
    imagem: str, competencias: list[str]
) -> None:
    """Fator 1: o baseline reapurado dentro do container é o congelado, e a conferência passa."""
    saida, julgamento = executar_na_meta(
        EXEMPLO, imagem, competencias, meta_por_fator(competencias, "1")
    )

    assert baseline_do_container(saida) == float(carregar_baselines().total(competencias))
    assert (julgamento.classe, julgamento.motivo) == ("sucesso", "ok")


def test_na_meta_o_baseline_do_container_e_o_que_o_worker_reapurou(imagem: str) -> None:
    competencias = ["2025-11"]
    meta = meta_por_fator(competencias, "1.1")

    saida, julgamento = executar_na_meta(EXEMPLO, imagem, competencias, meta, orcamento=None)

    reapurado = carregar_bases().baseline_na_meta(competencias, meta)
    assert baseline_do_container(saida) == float(reapurado) == 558870.26
    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == ("sucesso", "ok", None)
    assert julgamento.totais is not None
    assert julgamento.totais["baseline"] == 558870.26
    assert julgamento.totais["vendas_historicas"] == 13271681.51
    assert erros_do_dominio("resultado-totais", dict(julgamento.totais)) == []


@pytest.mark.parametrize("orcamento", [999999999.0, None], ids=["com orcamento", "sem orcamento"])
def test_regra_que_infla_o_baseline_do_harness_na_meta_e_denunciada_pelo_worker(
    imagem: str, orcamento: float | None
) -> None:
    """Na meta não há total congelado: o que denuncia a regra que infla o baseline reapurado
    dentro do container é a reapuração que o worker faz por conta própria."""
    competencias = ["2025-11"]
    saida, julgamento = executar_na_meta(
        REGRA_QUE_INFLA_O_BASELINE_DO_HARNESS,
        imagem,
        competencias,
        meta_por_fator(competencias, "1.1"),
        orcamento=orcamento,
    )

    # Controle: para o harness e para a classificação isto é um sucesso, com o baseline 10% acima
    # do reapurado. Sem a conferência do worker, a economia inventada seguiria adiante.
    assert julgamento.desfecho is not None and julgamento.desfecho.classe == "sucesso"
    assert baseline_do_container(saida) == pytest.approx(558870.26 * 1.10, abs=1.0)
    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "baseline_divergente",
        "indeterminado",
    )
    linha = linha_do_julgamento(julgamento)
    assert (linha.status, linha.totais) == ("erro_codigo", None)


def test_regra_com_especificacoes_roda_na_meta_e_devolve_o_resultado_completo(
    imagem: str,
) -> None:
    """A referência do caso generico-admissao tem núcleo e um elemento de especificação: na meta,
    a cobertura é conferida como sempre, e o resultado sai com a decomposição inteira."""
    competencias = ["2025-11"]

    _, julgamento = executar_na_meta(
        REFERENCIA_ADMISSAO,
        imagem,
        competencias,
        meta_por_fator(competencias, "1.2"),
        elementos_exigidos=["nucleo.percentual", "elem.1"],
    )

    assert (julgamento.classe, julgamento.motivo) == ("sucesso", "ok")
    assert julgamento.resultado is not None
    decomposicao = julgamento.resultado["decomposicao"]
    assert set(decomposicao["elemento"]) == {"nucleo.percentual", "elem.1"}
    # As cinco quebras da diferença e as três absolutas da T-259, na meta como fora dela.
    assert set(decomposicao) == {
        "elemento",
        "loja",
        "marca",
        "cargo",
        "competencia",
        "matricula",
        "loja_absoluto",
        "competencia_absoluto",
    }
    assert list(decomposicao["competencia"]) == competencias
    assert list(decomposicao["competencia_absoluto"]) == competencias
    linha = linha_do_julgamento(julgamento)
    assert (
        erros_do_dominio(
            "resultado-simulacao",
            {
                "totais": linha.totais,
                "assercoes": linha.assercoes,
                "decomposicao": linha.decomposicao,
            },
        )
        == []
    )


def test_na_meta_as_cinco_competencias_cabem_no_prazo_do_container(imagem: str) -> None:
    """A reapuração dentro do container soma tempo ao da regra. O pior caso do dataset (o período
    inteiro) tem de caber com folga no prazo de 60 s do container."""
    competencias = list(COMPETENCIAS)

    saida, julgamento = executar_na_meta(
        EXEMPLO, imagem, competencias, meta_por_fator(competencias, "1.1")
    )

    assert julgamento.classe == "sucesso"
    assert saida.duracao_s < 20.0
