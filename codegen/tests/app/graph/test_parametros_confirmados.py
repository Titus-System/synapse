import logging
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import simplejson
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker
from prometheus_client.parser import text_string_to_metric_families

from app.contratos.mensagens import SimulacaoConcluida
from app.core.logger import FormatadorJson, ManipuladorFilaContexto, job_id_ctx, no_ctx
from app.mensageria.consumers import Consumer
from app.repositorio.encerramentos import EstadoDoEncerramento
from app.representacao_regra import RepresentacaoRegra
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.test_mensageria import CONTRATOS, exemplo


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> ConfirmacaoFalsa:
    return ConfirmacaoFalsa(monkeypatch)


@pytest.fixture
def logs() -> Any:
    envelopes: list[dict[str, Any]] = []

    class Captura(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            preparado = ManipuladorFilaContexto(None).prepare(record)
            envelopes.append(simplejson.loads(FormatadorJson().format(preparado)))

    logger = logging.getLogger("app")
    handler = Captura()
    nivel = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield envelopes
    finally:
        logger.removeHandler(handler)
        logger.setLevel(nivel)


async def test_confirmacao_abre_load_rule_e_delega_contexto_exato(
    ambiente: ConfirmacaoFalsa,
) -> None:
    payload = exemplo("parametros-confirmados") | {"orcamento": Decimal("485000.123456789012345")}
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    recebida.reject.assert_not_awaited()
    recebida.nack.assert_not_awaited()
    ambiente.buscar_regra.assert_awaited_once_with(
        ambiente.banco, UUID(payload["job_id"]), UUID(payload["regra_id"])
    )
    estado = await ambiente.estado(payload)
    assert estado.next == ("await_execution",)
    assert estado.values["job_id"] == payload["job_id"]
    assert estado.values["regra_id"] == payload["regra_id"]
    assert estado.values["competencias"] == payload["competencias"]
    assert estado.values["orcamento"] == str(payload["orcamento"])
    assert "origem" not in estado.values
    assert [nome for nome, _ in ambiente.publicacoes] == [
        "etapa-alterada",
        "no-concluido",
        "etapa-alterada",
        "executar-codigo",
        "no-concluido",
    ]
    [comando] = ambiente.producers.executar_codigo.await_args.args
    assert comando.competencias == payload["competencias"]
    assert comando.orcamento == payload["orcamento"]
    assert len(ambiente.modelo.seen_messages) == 1
    assert len(ambiente.banco.tabela("codigos_gerados")) == 1


@pytest.mark.parametrize("concluido", [False, True])
async def test_reentrega_na_pausa_ou_apos_fim_nao_repete_efeitos(
    ambiente: ConfirmacaoFalsa,
    monkeypatch: pytest.MonkeyPatch,
    concluido: bool,
    cliente: AsyncClient,
) -> None:
    payload = exemplo("parametros-confirmados")
    await ambiente.consumer.receber(mensagem(payload))
    if concluido:
        monkeypatch.setattr(
            "app.mensageria.roteamento.buscar_regra_do_resultado",
            AsyncMock(return_value=UUID(payload["regra_id"])),
        )
        resultado = exemplo("simulacao-concluida") | {
            "job_id": payload["job_id"],
            "veredito": "viavel",
        }
        await Consumer(SimulacaoConcluida, "simulacao-concluida", ambiente.roteador).receber(
            mensagem(resultado)
        )
        assert (await ambiente.estado(payload)).next == ()
    publicacoes = list(ambiente.publicacoes)
    linhas = {nome: list(ambiente.banco.tabela(nome)) for nome in ambiente.banco.linhas}
    repetida = mensagem(payload)
    antes = amostras((await cliente.get("/metrics")).text)

    await ambiente.consumer.receber(repetida)

    repetida.ack.assert_awaited_once_with()
    repetida.nack.assert_not_awaited()
    assert ambiente.publicacoes == publicacoes
    assert {nome: ambiente.banco.tabela(nome) for nome in linhas} == linhas
    assert len(ambiente.modelo.seen_messages) == 1
    depois = amostras((await cliente.get("/metrics")).text)
    assert {nome: depois[nome] - antes[nome] for nome in antes} == {
        "ciclo_aberto": 0,
        "reentrega_ignorada": 1,
        "descartada": 0,
    }


async def test_outra_versao_do_mesmo_job_tem_ciclo_proprio(ambiente: ConfirmacaoFalsa) -> None:
    primeira = exemplo("parametros-confirmados")
    segunda = primeira | {"regra_id": str(uuid4()), "competencias": ["2025-11"]}

    await ambiente.consumer.receber(mensagem(primeira))
    ambiente.buscar_regra.return_value = RepresentacaoRegra.model_validate(
        {"nucleo": {"percentual": Decimal("0.03")}, "especificacoes": []}
    )
    await ambiente.consumer.receber(mensagem(segunda))

    assert len(ambiente.modelo.seen_messages) == 2
    assert (await ambiente.estado(primeira)).values["competencias"] == primeira["competencias"]
    assert (await ambiente.estado(segunda)).values["competencias"] == segunda["competencias"]
    assert len(ambiente.banco.tabela("codigos_gerados")) == 2
    assert {str(c["regra_id"]) for c in ambiente.banco.tabela("codigos_gerados")} == {
        primeira["regra_id"],
        segunda["regra_id"],
    }


async def test_sem_competencias_descarta_sem_grafo_nem_erro_do_job(
    ambiente: ConfirmacaoFalsa, logs: list[dict[str, Any]]
) -> None:
    payload = exemplo("parametros-confirmados")
    del payload["competencias"]
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    recebida.nack.assert_not_awaited()
    recebida.ack.assert_not_awaited()
    assert (await ambiente.estado(payload)).values == {}
    assert ambiente.publicacoes == []
    assert ambiente.banco.sql_executado == []
    ambiente.buscar_regra.assert_not_awaited()
    [descarte] = [log for log in logs if log.get("extra", {}).get("causa") == "contexto_ausente"]
    assert descarte["extra"]["resultado"] == "descartada"
    assert descarte["extra"]["regra_id"] == payload["regra_id"]


@pytest.mark.parametrize("encerramento", list(EstadoDoEncerramento))
@pytest.mark.parametrize("tem_contexto", [False, True])
async def test_job_encerrado_confirma_sem_recriar_checkpoint(
    ambiente: ConfirmacaoFalsa, encerramento: EstadoDoEncerramento, tem_contexto: bool
) -> None:
    ambiente.limpeza.encerramento = encerramento
    payload = exemplo("parametros-confirmados")
    if not tem_contexto:
        del payload["competencias"]
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    recebida.reject.assert_not_awaited()
    recebida.nack.assert_not_awaited()
    assert (await ambiente.estado(payload)).values == {}
    assert ambiente.publicacoes == []


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("competencias", []),
        ("competencias", ["2025-13"]),
        ("competencias", None),
        ("orcamento", None),
        ("orcamento", "100"),
        ("orcamento", -1),
        ("orcamento", True),
    ],
)
async def test_schema_recusa_contexto_invalido_antes_do_grafo(
    ambiente: ConfirmacaoFalsa, campo: str, valor: Any
) -> None:
    payload = exemplo("parametros-confirmados") | {campo: valor}
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    recebida.nack.assert_not_awaited()
    assert ambiente.publicacoes == []
    assert (await ambiente.estado(payload)).values == {}


@pytest.mark.parametrize("sem_orcamento", [False, True])
async def test_falha_permanente_do_ciclo_publica_erro_e_rejeita(
    monkeypatch: pytest.MonkeyPatch,
    sem_orcamento: bool,
    logs: list[dict[str, Any]],
    cliente: AsyncClient,
) -> None:
    ambiente = (
        ConfirmacaoFalsa(monkeypatch)
        if sem_orcamento
        else ConfirmacaoFalsa(monkeypatch, "```python\nsegredo_da_resposta(\n```")
    )
    payload = exemplo("parametros-confirmados")
    if sem_orcamento:
        del payload["orcamento"]
    recebida = mensagem(payload)
    antes = amostras((await cliente.get("/metrics")).text)

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    recebida.nack.assert_not_awaited()
    etapa = "delegacao_worker" if sem_orcamento else "geracao_codigo"
    assert ambiente.publicacoes[-1] == (
        "etapa-alterada",
        {"job_id": payload["job_id"], "etapa": etapa, "status": "erro"},
    )
    assert len(ambiente.modelo.seen_messages) == 1
    ambiente.producers.executar_codigo.assert_not_awaited()
    assert "segredo_da_resposta" not in simplejson.dumps(logs)
    depois = amostras((await cliente.get("/metrics")).text)
    assert {nome: depois[nome] - antes[nome] for nome in antes} == {
        "ciclo_aberto": 0,
        "reentrega_ignorada": 0,
        "descartada": 1,
    }
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    for log in logs:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(log)
        assert log["job_id"] == payload["job_id"]
    [descarte] = [log for log in logs if log.get("extra", {}).get("resultado") == "descartada"]
    assert descarte["extra"]["causa"] == "falha_do_job"
    assert descarte["extra"]["regra_id"] == payload["regra_id"]
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None


async def test_reentrega_apos_falha_transitoria_continua_sem_repetir_modelo(
    ambiente: ConfirmacaoFalsa,
) -> None:
    ambiente.banco.falhar_em = ("codigos_gerados",)
    recebida = mensagem()

    await ambiente.consumer.receber(recebida)

    recebida.nack.assert_awaited_once_with(requeue=True)
    recebida.reject.assert_not_awaited()
    assert all(p.get("status") != "erro" for _, p in ambiente.publicacoes)
    ambiente.banco.falhar_em = ()
    repetida = mensagem()
    await ambiente.consumer.receber(repetida)
    repetida.ack.assert_awaited_once_with()
    assert len(ambiente.modelo.seen_messages) == 1
    assert len(ambiente.banco.tabela("prompts")) == 1
    assert len(ambiente.banco.tabela("respostas_modelo")) == 1
    assert len(ambiente.banco.tabela("codigos_gerados")) == 1
    ambiente.producers.executar_codigo.assert_awaited_once()


def amostras(texto: str) -> dict[str, float]:
    amostras_do_consumo = [
        amostra
        for familia in text_string_to_metric_families(texto)
        for amostra in familia.samples
        if amostra.name == "codegen_parametros_confirmados_total"
    ]
    assert all(set(amostra.labels) == {"resultado"} for amostra in amostras_do_consumo)
    return {amostra.labels["resultado"]: amostra.value for amostra in amostras_do_consumo}


async def test_metricas_e_logs_dos_tres_resultados_passam_pelo_roteador_real(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    antes = amostras((await cliente.get("/metrics")).text)
    assert set(antes) == {"ciclo_aberto", "reentrega_ignorada", "descartada"}
    primeiro = exemplo("parametros-confirmados")
    segundo = primeiro | {"job_id": str(uuid4()), "regra_id": str(uuid4())}
    del segundo["competencias"]

    await ambiente.consumer.receber(mensagem(primeiro))
    assert job_id_ctx.get() is None
    await ambiente.consumer.receber(mensagem(primeiro))
    await ambiente.consumer.receber(mensagem(segundo))
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None

    depois = amostras((await cliente.get("/metrics")).text)
    assert {nome: depois[nome] - antes[nome] for nome in antes} == {
        "ciclo_aberto": 1,
        "reentrega_ignorada": 1,
        "descartada": 1,
    }
    resultados = [log for log in logs if "resultado" in log.get("extra", {})]
    assert [
        (log["extra"]["resultado"], log["job_id"], log["extra"]["regra_id"]) for log in resultados
    ] == [
        ("ciclo_aberto", primeiro["job_id"], primeiro["regra_id"]),
        ("reentrega_ignorada", primeiro["job_id"], primeiro["regra_id"]),
        ("descartada", segundo["job_id"], segundo["regra_id"]),
    ]
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    validador = Draft202012Validator(schema, format_checker=FormatChecker())
    for log in logs:
        validador.validate(log)
        assert log["job_id"] in {primeiro["job_id"], segundo["job_id"]}
        assert log["service.name"] == "synapse-codegen"
    assert "aplicar_regra" not in simplejson.dumps(logs)
    assert "representacao_regra" not in simplejson.dumps(logs)


async def test_correlacao_anterior_e_restaurada_em_sucesso_e_descarte(
    ambiente: ConfirmacaoFalsa,
) -> None:
    token = job_id_ctx.set("contexto-anterior")
    try:
        await ambiente.consumer.receber(mensagem())
        assert job_id_ctx.get() == "contexto-anterior"
        payload = exemplo("parametros-confirmados")
        del payload["competencias"]
        await ambiente.consumer.receber(mensagem(payload))
        assert job_id_ctx.get() == "contexto-anterior"
    finally:
        job_id_ctx.reset(token)
