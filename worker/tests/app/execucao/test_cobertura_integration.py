"""A conferência de cobertura (T-241) pelo caminho real da coleta, contra a imagem do sandbox.

O código roda no container, e o desfecho sai da mesma sequência do consumidor: o comando
`executar-codigo` lido do JSON, `preparar_execucao`, `executar_no_sandbox`, `classificar`, `julgar`
com os elementos exigidos do comando e a linha que seria gravada. Cada critério de aceitação da
T-241 tem um teste aqui, e nada depende de Postgres nem de RabbitMQ.
"""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.execucao.baseline import carregar_baselines
from app.execucao.bases import carregar_bases
from app.execucao.coleta import classificar
from app.execucao.container import Limites, executar_no_sandbox
from app.execucao.preparo import preparar_execucao
from app.execucao.registro import linha_do_julgamento
from app.execucao.veredito import Julgamento, julgar
from app.mensageria.contracts import ExecutarCodigo
from app.repositorio.codigos_gerados import CodigoGerado
from tests.app.esquemas import erros_do_dominio
from tests.app.sandbox.test_harness import DECLARACAO_DO_EXEMPLO, EXEMPLO, EXEMPLO_SEM_DECLARACAO

pytestmark = pytest.mark.docker

CURTO = Limites(timeout_s=30.0)
ORCAMENTO = 485000.0
COMPETENCIAS = ["2025-11"]
# O exemplo do contrato apura 494.037,78 sobre o baseline congelado de 508.382,32 de novembro.
BASELINE_2025_11 = 508382.32
SIMULADO_DO_EXEMPLO = 494037.78

# O exemplo do contrato implementa nucleo.percentual, o declara e atribui a ele toda contribuição.
EXEMPLO_COM_ELEM_1_SEM_CONTRIBUICAO = EXEMPLO.replace(
    DECLARACAO_DO_EXEMPLO, '        "elementos_implementados": [_ELEMENTO, "elem.1"],\n'
)
EXEMPLO_QUE_ATRIBUI_A_ELEM_9 = EXEMPLO.replace(
    'contribuicoes["elemento_ref"] = _ELEMENTO', 'contribuicoes["elemento_ref"] = "elem.9"'
)
EXEMPLO_COM_DECLARACAO_QUE_NAO_E_LISTA = EXEMPLO.replace(
    DECLARACAO_DO_EXEMPLO, '        "elementos_implementados": "nucleo.percentual",\n'
)

# Contribuições a elem.9, que a regra não tem, acrescentadas a uma linha do baseline sem mudar o
# total dela: duas que se anulam, ou uma de delta zero. A decomposição as reconcilia, e elem.9 só
# aparece nela com zero.
FILTRO_DO_EXEMPLO = (
    '    contribuicoes = contribuicoes[contribuicoes["delta"] != 0.0].reset_index(drop=True)\n'
)
ELEM_9_NA_PRIMEIRA_LINHA = """
    elem_9 = apuracao_base[
        ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]
    ].iloc[%(linhas)s].copy()
    elem_9["elemento_ref"] = "elem.9"
    elem_9["delta"] = %(deltas)s
    contribuicoes = pd.concat([contribuicoes, elem_9], ignore_index=True)
"""
EXEMPLO_COM_ELEM_9_QUE_SE_ANULA = EXEMPLO.replace(
    FILTRO_DO_EXEMPLO,
    FILTRO_DO_EXEMPLO + ELEM_9_NA_PRIMEIRA_LINHA % {"linhas": "[0, 0]", "deltas": "[1.0, -1.0]"},
)
EXEMPLO_COM_ELEM_9_DE_DELTA_ZERO = EXEMPLO.replace(
    FILTRO_DO_EXEMPLO,
    FILTRO_DO_EXEMPLO + ELEM_9_NA_PRIMEIRA_LINHA % {"linhas": "[0]", "deltas": "[0.0]"},
)

# A referência do caso generico-admissao (T-243) divide a contribuição entre nucleo.percentual e
# elem.1, e declara os dois. Sem elem.1 na declaração, ele tem contribuição e não está declarado.
REFERENCIA_ADMISSAO = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "casos_geracao"
    / "generico-admissao"
    / "referencia.py"
).read_text(encoding="utf-8")
ADMISSAO_SEM_DECLARAR_ELEM_1 = REFERENCIA_ADMISSAO.replace(
    '"elementos_implementados": [_NUCLEO, _ADMISSAO],', '"elementos_implementados": [_NUCLEO],'
)


def test_as_variacoes_do_exemplo_mudam_o_que_dizem_mudar() -> None:
    """Sem isso, um `replace` que não casasse rodaria o exemplo intacto e o teste passaria pelo
    motivo errado."""
    for variacao in (
        EXEMPLO_SEM_DECLARACAO,
        EXEMPLO_COM_ELEM_1_SEM_CONTRIBUICAO,
        EXEMPLO_QUE_ATRIBUI_A_ELEM_9,
        EXEMPLO_COM_DECLARACAO_QUE_NAO_E_LISTA,
        EXEMPLO_COM_ELEM_9_QUE_SE_ANULA,
        EXEMPLO_COM_ELEM_9_DE_DELTA_ZERO,
    ):
        assert variacao != EXEMPLO
    assert ADMISSAO_SEM_DECLARAR_ELEM_1 != REFERENCIA_ADMISSAO


def executar(fonte: str, imagem: str, elementos_exigidos: list[str] | None) -> Julgamento:
    """O caminho do consumidor, do comando ao julgamento, com o container de verdade."""
    job_id, codigo_id = uuid4(), uuid4()
    corpo: dict[str, Any] = {
        "job_id": str(job_id),
        "codigo_gerado_id": str(codigo_id),
        "competencias": COMPETENCIAS,
        "orcamento": ORCAMENTO,
    }
    if elementos_exigidos is not None:
        corpo["elementos_exigidos"] = elementos_exigidos
    comando = ExecutarCodigo.model_validate_json(json.dumps(corpo))
    codigo = CodigoGerado(id=codigo_id, job_id=job_id, linguagem="python", fonte=fonte)
    execucao = preparar_execucao(comando, codigo)

    saida = executar_no_sandbox(execucao.payload, imagem=imagem, limites=CURTO)
    desfecho = classificar(saida, execucao.payload, execucao.orcamento)
    return julgar(
        desfecho,
        execucao.payload.competencias,
        execucao.orcamento,
        carregar_baselines(),
        elementos_exigidos=execucao.elementos_exigidos,
        bases=carregar_bases(),
    )


def contribuicoes(julgamento: Julgamento) -> set[str]:
    """Os elementos com contribuição na decomposição que saiu do container."""
    assert julgamento.desfecho is not None and julgamento.desfecho.resultado is not None
    return set(julgamento.desfecho.resultado["decomposicao"]["elemento"])


def test_codigo_que_declara_e_cobre_os_elementos_segue_para_o_veredito_como_antes(
    imagem: str,
) -> None:
    conferido = executar(EXEMPLO, imagem, ["nucleo.percentual"])
    sem_conferencia = executar(EXEMPLO, imagem, None)

    assert (conferido.classe, conferido.motivo, conferido.veredito) == (
        "sucesso",
        "ok",
        "inviavel",
    )
    assert conferido.cobertura is None
    assert conferido.resultado == sem_conferencia.resultado
    assert conferido.veredito == sem_conferencia.veredito
    assert conferido.totais is not None
    assert (conferido.totais["baseline"], conferido.totais["simulado"]) == (
        BASELINE_2025_11,
        SIMULADO_DO_EXEMPLO,
    )


def test_codigo_que_nao_declara_um_elemento_exigido_para_com_o_elemento_no_diagnostico(
    imagem: str,
) -> None:
    julgamento = executar(EXEMPLO, imagem, ["nucleo.percentual", "elem.1"])

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "cobertura_incompleta",
        "indeterminado",
    )
    assert julgamento.resultado is None
    linha = linha_do_julgamento(julgamento)
    assert (linha.status, linha.veredito, linha.totais, linha.decomposicao) == (
        "erro_codigo",
        None,
        None,
        None,
    )
    assert linha.diagnostico == {"causa": "cobertura_incompleta", "elementos_ausentes": ["elem.1"]}
    assert erros_do_dominio("resultado-diagnostico", linha.diagnostico) == []


@pytest.mark.parametrize(
    ("fonte", "exigidos", "com_contribuicao", "diagnostico"),
    [
        pytest.param(
            ADMISSAO_SEM_DECLARAR_ELEM_1,
            ["nucleo.percentual", "elem.1"],
            "elem.1",
            {"causa": "cobertura_incompleta", "elementos_ausentes": ["elem.1"]},
            id="exigido com contribuicao e sem declaracao",
        ),
        pytest.param(
            EXEMPLO_QUE_ATRIBUI_A_ELEM_9,
            ["nucleo.percentual"],
            "elem.9",
            {"causa": "cobertura_incompleta", "elementos_fora_da_regra": ["elem.9"]},
            id="contribuicao de elemento que a regra nao tem",
        ),
    ],
)
def test_contribuicao_de_elemento_nao_declarado_para_o_job(
    imagem: str,
    fonte: str,
    exigidos: list[str],
    com_contribuicao: str,
    diagnostico: dict[str, object],
) -> None:
    julgamento = executar(fonte, imagem, exigidos)

    # Controle: o elemento tem mesmo contribuição na decomposição que saiu do container.
    assert com_contribuicao in contribuicoes(julgamento)
    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "cobertura_incompleta")
    diagnostico_gravado = linha_do_julgamento(julgamento).diagnostico
    assert diagnostico_gravado == diagnostico
    assert erros_do_dominio("resultado-diagnostico", diagnostico_gravado) == []


@pytest.mark.parametrize(
    "fonte",
    [EXEMPLO_COM_ELEM_9_QUE_SE_ANULA, EXEMPLO_COM_ELEM_9_DE_DELTA_ZERO],
    ids=["contribuicoes que se anulam", "contribuicao de delta zero"],
)
def test_contribuicao_que_soma_zero_de_elemento_que_a_regra_nao_tem_para_o_job(
    imagem: str, fonte: str
) -> None:
    """A condição é sobre o elemento estar em contribuicoes, não sobre o valor que ele soma: uma
    atribuição a elem.9 descreve uma parte que a regra não tem, mesmo sem mudar o número."""
    julgamento = executar(fonte, imagem, ["nucleo.percentual"])

    # Controle: elem.9 chegou à decomposição, e com zero.
    assert julgamento.desfecho is not None and julgamento.desfecho.resultado is not None
    assert julgamento.desfecho.resultado["decomposicao"]["elemento"]["elem.9"] == 0.0
    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "cobertura_incompleta")
    assert linha_do_julgamento(julgamento).diagnostico == {
        "causa": "cobertura_incompleta",
        "elementos_fora_da_regra": ["elem.9"],
    }


def test_elemento_declarado_sem_contribuicao_e_aceito(imagem: str) -> None:
    julgamento = executar(
        EXEMPLO_COM_ELEM_1_SEM_CONTRIBUICAO, imagem, ["nucleo.percentual", "elem.1"]
    )

    assert "elem.1" not in contribuicoes(julgamento)
    assert (julgamento.classe, julgamento.motivo) == ("sucesso", "ok")


def test_comando_sem_elementos_exigidos_executa_codigo_sem_declaracao_como_hoje(
    imagem: str,
) -> None:
    antigo = executar(EXEMPLO_SEM_DECLARACAO, imagem, None)
    declarado = executar(EXEMPLO, imagem, None)

    assert antigo.desfecho is not None and antigo.desfecho.elementos_implementados is None
    assert (antigo.classe, antigo.motivo, antigo.veredito) == ("sucesso", "ok", "inviavel")
    assert antigo.resultado == declarado.resultado
    assert antigo.totais is not None
    assert (antigo.totais["baseline"], antigo.totais["simulado"]) == (
        BASELINE_2025_11,
        SIMULADO_DO_EXEMPLO,
    )


def test_codigo_sem_declaracao_num_comando_que_exige_elementos_e_cobertura_incompleta(
    imagem: str,
) -> None:
    julgamento = executar(EXEMPLO_SEM_DECLARACAO, imagem, ["nucleo.percentual"])

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "cobertura_incompleta")
    assert linha_do_julgamento(julgamento).diagnostico == {
        "causa": "cobertura_incompleta",
        "elementos_ausentes": ["nucleo.percentual"],
    }


def test_declaracao_fora_do_contrato_e_recusada_pelo_harness(imagem: str) -> None:
    """Uma chave que não é lista de identificadores é saída fora do contrato, como uma tabela sem
    as colunas exigidas: a regra falhou, e a conferência nem chega a rodar."""
    julgamento = executar(EXEMPLO_COM_DECLARACAO_QUE_NAO_E_LISTA, imagem, ["nucleo.percentual"])

    assert (julgamento.classe, julgamento.motivo) == ("erro_codigo", "excecao")
    assert julgamento.desfecho is not None and julgamento.desfecho.erro is not None
    assert julgamento.desfecho.erro["tipo"] == "SaidaForaDoContratoError"
