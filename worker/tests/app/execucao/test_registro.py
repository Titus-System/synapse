"""Do julgamento à linha de `resultados_simulacao` e ao evento `simulacao-concluida` (T-067).

A linha guarda o resultado inteiro e, num `erro_codigo`, o diagnóstico da falha (T-204); o
evento, só a referência e os agregados do schema. Os dois saem de `ResultadoGravado`, o mesmo para
o resultado recém-gravado e para o que uma reentrega encontra já gravado.
"""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.execucao.coleta import DesfechoClassificado, Motivo
from app.execucao.registro import (
    DiagnosticoForaDoContratoError,
    diagnostico_do_julgamento,
    evento_de,
    linha_do_julgamento,
)
from app.execucao.veredito import CoberturaIncompleta, Julgamento, julgamento_de_infra
from app.repositorio.resultados import ResultadoGravado
from tests.app.esquemas import erros_do_dominio, erros_do_evento
from tests.app.execucao.envelopes import ASSERCAO_OK, ASSERCAO_VIOLADA, FALHA
from tests.app.execucao.test_veredito import BASELINE_2025_11, julgar_2025_11, sucesso

JOB_ID = uuid4()
CAMPOS_DO_EVENTO_DE_SUCESSO = {
    "job_id",
    "resultado_id",
    "status",
    "veredito",
    "total_baseline",
    "total_simulado",
    "diferenca_abs",
    "diferenca_pct",
}


def julgamento_de_sucesso(orcamento: float) -> Julgamento:
    return julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"), orcamento)  # type: ignore[no-any-return]


def gravado_de(julgamento: Julgamento) -> ResultadoGravado:
    linha = linha_do_julgamento(julgamento)
    return ResultadoGravado(
        id=uuid4(), job_id=JOB_ID, status=linha.status, veredito=linha.veredito, totais=linha.totais
    )


def corpo_do_evento(gravado: ResultadoGravado) -> dict[str, object]:
    corpo: dict[str, object] = json.loads(evento_de(gravado).model_dump_json(exclude_none=True))
    return corpo


NAO_SUCESSOS = [
    Julgamento(
        "assercao_violada",
        "assercao",
        "indeterminado",
        desfecho=DesfechoClassificado("assercao_violada", "assercao", [ASSERCAO_VIOLADA]),
    ),
    Julgamento(
        "erro_codigo",
        "excecao",
        "indeterminado",
        desfecho=DesfechoClassificado("erro_codigo", "excecao", [], erro=FALHA),
    ),
    Julgamento(
        "erro_codigo",
        "baseline_divergente",
        "indeterminado",
        desfecho=DesfechoClassificado("sucesso", "ok", [ASSERCAO_OK]),
    ),
    Julgamento(
        "erro_codigo",
        "timeout",
        "indeterminado",
        desfecho=DesfechoClassificado("erro_codigo", "timeout"),
    ),
    julgamento_de_infra(),
]
IDS_DOS_NAO_SUCESSOS = ["assercao_violada", "excecao", "baseline_divergente", "timeout", "infra"]


# ---- a linha ----


@pytest.mark.parametrize(("orcamento", "veredito"), [(600000.0, "viavel"), (485000.0, "inviavel")])
def test_sucesso_grava_o_resultado_inteiro(orcamento: float, veredito: str) -> None:
    julgamento = julgamento_de_sucesso(orcamento)

    linha = linha_do_julgamento(julgamento)

    assert julgamento.resultado is not None
    assert (linha.status, linha.veredito) == ("sucesso", veredito)
    assert linha.totais == julgamento.resultado["totais"]
    assert linha.totais is not None and linha.totais["orcamento"] == orcamento
    assert linha.assercoes == [ASSERCAO_OK]
    assert linha.decomposicao == julgamento.resultado["decomposicao"]


def test_sucesso_sem_orcamento_grava_o_resultado_sem_veredito_e_sem_totais_orcamento() -> None:
    """Job sem orçamento (T-281): a linha é a do resultado conferido, sem o critério que não
    existe e sem o veredito que dependeria dele."""
    julgamento = julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"), None)

    linha = linha_do_julgamento(julgamento)

    assert julgamento.resultado is not None
    assert (linha.status, linha.veredito, linha.diagnostico) == ("sucesso", None, None)
    assert linha.totais == julgamento.resultado["totais"]
    assert linha.totais is not None and "orcamento" not in linha.totais
    assert erros_do_dominio("resultado-totais", linha.totais) == []
    assert linha.decomposicao == julgamento.resultado["decomposicao"]


@pytest.mark.parametrize("julgamento", NAO_SUCESSOS, ids=IDS_DOS_NAO_SUCESSOS)
def test_o_que_nao_e_sucesso_grava_so_o_status_e_as_assercoes(julgamento: Julgamento) -> None:
    linha = linha_do_julgamento(julgamento)

    assert linha.status == julgamento.classe
    assert linha.veredito is None
    assert linha.totais is None and linha.decomposicao is None
    assert linha.assercoes == (julgamento.desfecho.assercoes if julgamento.desfecho else [])


def test_erro_infra_grava_assercoes_vazias() -> None:
    assert linha_do_julgamento(julgamento_de_infra()).assercoes == []


def test_a_linha_de_assercao_violada_leva_a_assercao_que_falhou() -> None:
    linha = linha_do_julgamento(NAO_SUCESSOS[0])

    assert [a["resultado"] for a in linha.assercoes] == ["violada"]


@pytest.mark.parametrize("julgamento", [*NAO_SUCESSOS, julgamento_de_sucesso(1.0)])
def test_o_indeterminado_interno_nunca_e_gravado(julgamento: Julgamento) -> None:
    """A api lê `sucesso` + `indeterminado` como número confiável ainda sem julgamento, e o
    contrato declara o veredito nulo fora de `sucesso`."""
    assert linha_do_julgamento(julgamento).veredito != "indeterminado"


def test_um_sucesso_sem_resultado_ou_indeterminado_e_um_erro_de_programacao() -> None:
    with pytest.raises(ValueError, match="sucesso"):
        linha_do_julgamento(Julgamento("sucesso", "ok", "indeterminado"))
    with pytest.raises(ValueError, match="sucesso"):
        linha_do_julgamento(Julgamento("sucesso", "ok", "viavel"))


# ---- o diagnóstico ----

PROBLEMAS = (
    {"caminho": "$.decomposicao", "palavra_chave": "required"},
    {"caminho": "$.totais.orcamento", "palavra_chave": "fornecido_pelo_container"},
)
# As causas decididas fora do código gerado: não há exceção capturada para guardar.
CAUSAS_SEM_EXCECAO: list[Motivo] = [
    "timeout",
    "memoria",
    "saida_truncada",
    "sem_envelope",
    "envelope_invalido",
    "envelope_de_outra_execucao",
    "codigo_de_saida_divergente",
]


def erro_codigo(motivo: Motivo, **desfecho: object) -> Julgamento:
    return Julgamento(
        "erro_codigo",
        motivo,
        "indeterminado",
        desfecho=DesfechoClassificado("erro_codigo", motivo, **desfecho),  # type: ignore[arg-type]
    )


def test_a_excecao_da_regra_e_conservada_como_o_sandbox_a_capturou() -> None:
    linha = linha_do_julgamento(NAO_SUCESSOS[1])

    assert linha.diagnostico == {"causa": "excecao", "falha": FALHA}


@pytest.mark.parametrize("causa", CAUSAS_SEM_EXCECAO)
def test_causa_sem_excecao_guarda_so_a_causa(causa: Motivo) -> None:
    """Timeout, memória e saída inválida não têm exceção: nenhuma é inventada para eles."""
    assert linha_do_julgamento(erro_codigo(causa)).diagnostico == {"causa": causa}


def test_baseline_divergente_guarda_so_a_causa_do_julgamento() -> None:
    """O desfecho do container era `sucesso`: a causa é a do julgamento, não a da coleta."""
    assert linha_do_julgamento(NAO_SUCESSOS[2]).diagnostico == {"causa": "baseline_divergente"}


def test_resultado_fora_do_schema_guarda_os_problemas() -> None:
    linha = linha_do_julgamento(erro_codigo("resultado_fora_do_schema", problemas=PROBLEMAS))

    assert linha.diagnostico == {"causa": "resultado_fora_do_schema", "problemas": list(PROBLEMAS)}


def cobertura_incompleta(
    ausentes: tuple[str, ...] = (), fora_da_regra: tuple[str, ...] = ()
) -> Julgamento:
    """Como `julgar` o devolve: o desfecho do container era `sucesso`, e a causa é do julgamento."""
    return Julgamento(
        "erro_codigo",
        "cobertura_incompleta",
        "indeterminado",
        desfecho=DesfechoClassificado("sucesso", "ok", [ASSERCAO_OK]),
        cobertura=CoberturaIncompleta(ausentes=ausentes, fora_da_regra=fora_da_regra),
    )


@pytest.mark.parametrize(
    ("julgamento", "diagnostico"),
    [
        (
            cobertura_incompleta(ausentes=("nucleo.percentual", "elem.2")),
            {
                "causa": "cobertura_incompleta",
                "elementos_ausentes": ["nucleo.percentual", "elem.2"],
            },
        ),
        (
            cobertura_incompleta(fora_da_regra=("elem.9",)),
            {"causa": "cobertura_incompleta", "elementos_fora_da_regra": ["elem.9"]},
        ),
        (
            cobertura_incompleta(ausentes=("elem.1",), fora_da_regra=("elem.9",)),
            {
                "causa": "cobertura_incompleta",
                "elementos_ausentes": ["elem.1"],
                "elementos_fora_da_regra": ["elem.9"],
            },
        ),
    ],
    ids=["ausentes", "fora da regra", "os dois"],
)
def test_cobertura_incompleta_guarda_os_elementos_que_a_reprovaram(
    julgamento: Julgamento, diagnostico: dict[str, object]
) -> None:
    """A lista vazia fica de fora: o contrato só a admite com item."""
    linha = linha_do_julgamento(julgamento)

    assert linha.diagnostico == diagnostico
    assert erros_do_dominio("resultado-diagnostico", linha.diagnostico) == []


@pytest.mark.parametrize(
    "julgamento",
    [NAO_SUCESSOS[0], julgamento_de_infra(), julgamento_de_sucesso(600000.0)],
    ids=["assercao_violada", "infra", "sucesso"],
)
def test_so_erro_codigo_tem_diagnostico(julgamento: Julgamento) -> None:
    assert linha_do_julgamento(julgamento).diagnostico is None


@pytest.mark.parametrize(
    "julgamento",
    [
        NAO_SUCESSOS[1],
        NAO_SUCESSOS[2],
        *(erro_codigo(causa) for causa in CAUSAS_SEM_EXCECAO),
        erro_codigo("resultado_fora_do_schema", problemas=PROBLEMAS),
    ],
)
def test_todo_diagnostico_gravado_valida_contra_o_contrato(julgamento: Julgamento) -> None:
    """Conferido por um validador do teste, e não pelo mesmo que o worker usa ao montar."""
    diagnostico = diagnostico_do_julgamento(julgamento)

    assert diagnostico is not None
    assert erros_do_dominio("resultado-diagnostico", diagnostico) == []


@pytest.mark.parametrize(
    ("julgamento", "problema"),
    [
        (erro_codigo("excecao"), {"caminho": "$", "palavra_chave": "required"}),
        (erro_codigo("timeout", erro=FALHA), {"caminho": "$", "palavra_chave": "not"}),
        (
            erro_codigo("excecao", erro={**FALHA, "traceback": None}),
            {"caminho": "$.falha.traceback", "palavra_chave": "type"},
        ),
        (cobertura_incompleta(), {"caminho": "$", "palavra_chave": "anyOf"}),
    ],
    ids=[
        "excecao sem falha",
        "falha fora de excecao",
        "falha mal formada",
        "cobertura sem elemento",
    ],
)
def test_diagnostico_incoerente_e_erro_do_worker_e_nao_e_gravado(
    julgamento: Julgamento, problema: dict[str, str]
) -> None:
    with pytest.raises(DiagnosticoForaDoContratoError) as erro:
        linha_do_julgamento(julgamento)

    assert problema in erro.value.problemas


def test_o_repr_da_linha_nao_carrega_a_falha_da_regra() -> None:
    """Quem registrar a linha inteira num log não pode vazar a mensagem nem o traceback."""
    linha = linha_do_julgamento(NAO_SUCESSOS[1])

    assert FALHA["mensagem"] not in repr(linha)
    assert FALHA["traceback"] not in repr(linha)


# ---- o evento ----


@pytest.mark.parametrize("orcamento", [600000.0, 485000.0])
def test_evento_de_sucesso_leva_veredito_e_agregados(orcamento: float) -> None:
    julgamento = julgamento_de_sucesso(orcamento)
    gravado = gravado_de(julgamento)

    corpo = corpo_do_evento(gravado)

    assert set(corpo) == CAMPOS_DO_EVENTO_DE_SUCESSO
    assert corpo["resultado_id"] == str(gravado.id)
    assert corpo["job_id"] == str(JOB_ID)
    assert corpo["status"] == "sucesso"
    assert corpo["veredito"] == ("viavel" if orcamento == 600000.0 else "inviavel")
    assert corpo["total_baseline"] == 508382.32
    assert corpo["total_simulado"] == 520000.0
    assert corpo["diferenca_abs"] == 11617.68
    assert erros_do_evento("simulacao-concluida", corpo) == []


def test_evento_de_sucesso_sem_orcamento_leva_os_agregados_sem_veredito() -> None:
    """O veredito fica ausente do evento, não `null`: é o que a api lê como resultado sem
    orçamento (T-281)."""
    gravado = gravado_de(julgar_2025_11(sucesso(BASELINE_2025_11, "520000.00"), None))

    corpo = corpo_do_evento(gravado)

    assert set(corpo) == CAMPOS_DO_EVENTO_DE_SUCESSO - {"veredito"}
    assert corpo["status"] == "sucesso"
    assert corpo["total_simulado"] == 520000.0
    assert erros_do_evento("simulacao-concluida", corpo) == []


@pytest.mark.parametrize("julgamento", NAO_SUCESSOS, ids=IDS_DOS_NAO_SUCESSOS)
def test_evento_de_erro_so_leva_a_referencia_e_o_status(julgamento: Julgamento) -> None:
    """O schema declara veredito e agregados ausentes fora de `sucesso`: não há número que os
    sustente."""
    gravado = gravado_de(julgamento)

    corpo = corpo_do_evento(gravado)

    assert corpo == {
        "job_id": str(JOB_ID),
        "resultado_id": str(gravado.id),
        "status": julgamento.classe,
    }
    assert erros_do_evento("simulacao-concluida", corpo) == []


def test_o_evento_nao_leva_o_conteudo_da_linha() -> None:
    """Claim-check (ARCHITECTURE.md §6.1): a decomposição e as asserções ficam no Postgres."""
    corpo = corpo_do_evento(gravado_de(julgamento_de_sucesso(600000.0)))

    assert not {"decomposicao", "assercoes", "totais", "resultado", "erro"} & set(corpo)


def test_a_linha_reentregue_publica_o_mesmo_evento_que_a_recem_gravada() -> None:
    """Os dois caminhos montam o evento de `ResultadoGravado`: o que a consulta devolve do banco
    é indistinguível do que a gravação acabou de produzir."""
    recem_gravado = gravado_de(julgamento_de_sucesso(485000.0))
    do_banco = ResultadoGravado(
        id=recem_gravado.id,
        job_id=recem_gravado.job_id,
        status=recem_gravado.status,
        veredito=recem_gravado.veredito,
        totais=json.loads(json.dumps(recem_gravado.totais)),
    )

    assert evento_de(do_banco) == evento_de(recem_gravado)


@pytest.mark.parametrize(
    ("status", "veredito"), [("talvez", None), ("sucesso", "quase"), ("erro", None)]
)
def test_linha_com_vocabulario_fora_do_schema_nao_vira_evento(
    status: str, veredito: str | None
) -> None:
    gravado = ResultadoGravado(
        id=uuid4(),
        job_id=JOB_ID,
        status=status,
        veredito=veredito,
        totais={"baseline": 1.0, "simulado": 1.0, "diferenca_abs": 0.0, "diferenca_pct": 0.0},
    )

    with pytest.raises(ValidationError):
        evento_de(gravado)
