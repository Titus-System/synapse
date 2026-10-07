import logging
from asyncio import CancelledError
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import simplejson
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker
from prometheus_client.parser import text_string_to_metric_families

from app.contratos.mensagens import RegraSubmetida, SimulacaoConcluida
from app.core.logger import FormatadorJson, ManipuladorFilaContexto, job_id_ctx, no_ctx
from app.falhas import FalhaDoJobError
from app.graph.nodes.reject_rule import RegraComConflitoError, reject_rule
from app.mensageria.consumers import Consumer
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.regras import buscar_regra
from app.representacao_regra import RepresentacaoRegra
from app.sugestao_adaptacao import propor_alternativa
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.repositorio.test_regras import _sessionmaker
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


def regra(conflito: bool) -> RepresentacaoRegra:
    return RepresentacaoRegra.model_validate(
        {
            "nucleo": {"percentual": Decimal("0.025")},
            "especificacoes": [
                {
                    "ref": "elem.1",
                    "construto": "faixa_valor",
                    "descricao": "CONTEUDO_PRIVADO",
                    "limite_inferior": 50000 if conflito else 30000,
                    "limite_superior": 40000,
                    "efeito": {"tipo": "bonus_fixo", "valor": 3500},
                }
            ],
        }
    )


@pytest.mark.parametrize("conflito", [False, True])
async def test_regra_passa_pela_validacao_antes_de_qualquer_geracao(
    ambiente: ConfirmacaoFalsa, conflito: bool
) -> None:
    original = regra(conflito).para_contrato()
    ambiente.buscar_regra.return_value = regra(conflito)
    payload = exemplo("parametros-confirmados")
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    estado = (await ambiente.estado(payload)).values
    assert estado["representacao_regra"] == original
    assert estado["regra_liberada"] is not conflito
    assert estado["conflitos"] == (
        [{"elementos": ["elem.1"], "motivo": "limite inferior 50000 maior que o superior 40000"}]
        if conflito
        else []
    )
    inicio, trilha, proximo = ambiente.publicacoes[:3]
    assert inicio == (
        "etapa-alterada",
        {"job_id": payload["job_id"], "etapa": "validacao_dominio", "status": "iniciada"},
    )
    assert trilha[0] == "no-concluido"
    assert trilha[1]["no"] == "validacao_dominio"
    assert trilha[1]["regra_id"] == payload["regra_id"]
    assert trilha[1]["evento_id"] == str(
        id_do_evento_de_trilha(
            UUID(payload["job_id"]), "validacao_dominio", UUID(payload["regra_id"])
        )
    )
    assert "no_dominio" not in trilha[1]["conclusao"]
    assert trilha[1]["conclusao"]["resumo"] == (
        "Regra barrada: 1 conflito(s). Elementos: elem.1."
        if conflito
        else "Regra liberada pela validação de domínio."
    )
    assert proximo == (
        "etapa-alterada",
        {
            "job_id": payload["job_id"],
            "etapa": "validacao_dominio" if conflito else "geracao_codigo",
            "status": "erro" if conflito else "iniciada",
        },
    )
    if conflito:
        assert len(ambiente.publicacoes) == 3
        recebida.reject.assert_awaited_once_with(requeue=False)
        assert ambiente.modelo.seen_messages == []
        assert ambiente.banco.linhas == {}
    else:
        recebida.ack.assert_awaited_once_with()
        assert len(ambiente.modelo.seen_messages) == 1
        assert len(ambiente.banco.tabela("prompts")) == 1
        assert (await ambiente.estado(payload)).next == ("await_execution",)
    recebida.nack.assert_not_awaited()


@pytest.mark.parametrize("origem", ["texto", "voz", "reprocessamento", "formulario"])
async def test_toda_origem_de_regra_persistida_e_validada(
    ambiente: ConfirmacaoFalsa, origem: str
) -> None:
    payload = exemplo("regra-submetida") | {"origem": origem}
    ambiente.buscar_regra.return_value = regra(True)
    recebida = mensagem(payload)

    await Consumer(RegraSubmetida, "regra-submetida", ambiente.roteador).receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    assert ambiente.modelo.seen_messages == []
    assert (await ambiente.estado(payload)).values["regra_liberada"] is False


@pytest.mark.parametrize(
    "linha",
    [None, {"nucleo": {"percentual": "CONTEUDO_PRIVADO"}, "especificacoes": []}],
    ids=["inexistente", "fora-do-contrato"],
)
async def test_leitura_invalida_reporta_falha_da_validacao_apos_anuncio(
    ambiente: ConfirmacaoFalsa,
    linha: dict[str, Any] | None,
) -> None:
    async def buscar(_: object, job_id: UUID, regra_id: UUID) -> RepresentacaoRegra:
        return await buscar_regra(_sessionmaker(linha), job_id, regra_id)

    ambiente.buscar_regra.side_effect = buscar
    payload = exemplo("parametros-confirmados")
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    assert ambiente.publicacoes == [
        (
            "etapa-alterada",
            {"job_id": payload["job_id"], "etapa": "validacao_dominio", "status": status},
        )
        for status in ("iniciada", "erro")
    ]
    recebida.reject.assert_awaited_once_with(requeue=False)
    assert ambiente.modelo.seen_messages == []


async def test_proposta_da_adaptacao_passa_pela_mesma_validacao(
    ambiente: ConfirmacaoFalsa,
) -> None:
    alternativa = propor_alternativa(
        {"nucleo": {"percentual": Decimal("0.025")}, "especificacoes": []},
        Decimal("492100"),
        Decimal("485000"),
        baseline=Decimal("480312"),
    )
    assert alternativa.representacao is not None
    ambiente.buscar_regra.return_value = RepresentacaoRegra.model_validate(
        alternativa.representacao
    )
    payload = exemplo("parametros-confirmados")

    await ambiente.consumer.receber(mensagem(payload))

    assert (await ambiente.estado(payload)).values["regra_liberada"] is True
    assert len(ambiente.modelo.seen_messages) == 1


@pytest.mark.parametrize("falha", ["verificacao", "publicacao"])
async def test_falha_do_no_conta_duracao_e_falha_sem_expor_conteudo(
    ambiente: ConfirmacaoFalsa,
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
    falha: str,
) -> None:
    erro = RuntimeError("CONTEUDO_PRIVADO")
    if falha == "publicacao":
        ambiente.producers.no_concluido.side_effect = erro
    else:
        monkeypatch.setattr(
            "app.nos.validacao_dominio.verificar", lambda _: (_ for _ in ()).throw(erro)
        )
    antes = (await cliente.get("/metrics")).text
    payload = exemplo("parametros-confirmados")
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)
    recebida.nack.assert_awaited_once_with(requeue=True)
    depois = (await cliente.get("/metrics")).text
    for nome in ("job_runs_total", "job_failures_total", "job_duration_seconds_count"):
        labels = {"job_name": "validate_domain"}
        assert amostra(depois, nome, labels) - amostra(antes, nome, labels) == 1
    for resultado in ("liberada", "barrada"):
        labels = {"resultado": resultado}
        nome = "codegen_validacao_dominio_resultados_total"
        assert amostra(depois, nome, labels) == amostra(antes, nome, labels)
    eventos = [log for log in logs if log.get("no") == "validacao_dominio"]
    assert [log["message"] for log in eventos] == [
        "domain validation started",
        "domain validation failed",
    ]
    assert all(log["job_id"] == payload["job_id"] for log in eventos)
    assert "CONTEUDO_PRIVADO" not in simplejson.dumps(logs)
    assert ambiente.modelo.seen_messages == []
    assert no_ctx.get() is None
    assert job_id_ctx.get() is None


async def test_reject_rule_lanca_falha_permanente_com_mensagem_fixa() -> None:
    with pytest.raises(RegraComConflitoError) as erro:
        await reject_rule({"conflitos": [{"elementos": ["elem.1"], "motivo": "CONTEUDO_PRIVADO"}]})

    assert erro.value.etapa == "validacao_dominio"
    assert isinstance(erro.value, FalhaDoJobError)
    assert str(erro.value) == "Rule rejected by domain validation"


@pytest.mark.parametrize("cancelamento", [False, True])
async def test_erro_inesperado_ou_cancelamento_do_no_e_sanitizado_e_medido(
    ambiente: ConfirmacaoFalsa,
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    cancelamento: bool,
) -> None:
    from app.graph.nodes.validate_domain import validate_domain

    erro = CancelledError("CONTEUDO_PRIVADO") if cancelamento else RuntimeError("CONTEUDO_PRIVADO")
    monkeypatch.setattr(
        "app.nos.validacao_dominio.verificar", lambda _: (_ for _ in ()).throw(erro)
    )
    payload = exemplo("parametros-confirmados")
    estado = {
        "job_id": payload["job_id"],
        "regra_id": payload["regra_id"],
        "representacao_regra": regra(False).para_contrato(),
    }
    antes = (await cliente.get("/metrics")).text
    token = no_ctx.set("contexto-anterior")
    try:
        with pytest.raises(CancelledError if cancelamento else RuntimeError) as capturado:
            await validate_domain(estado, {"configurable": {"producers": ambiente.producers}})
        assert str(capturado.value) == (
            "Domain validation cancelled" if cancelamento else "Domain validation failed"
        )
        assert capturado.value.__suppress_context__ is True
        assert no_ctx.get() == "contexto-anterior"
    finally:
        no_ctx.reset(token)
    depois = (await cliente.get("/metrics")).text
    for nome in ("job_runs_total", "job_failures_total", "job_duration_seconds_count"):
        labels = {"job_name": "validate_domain"}
        assert amostra(depois, nome, labels) - amostra(antes, nome, labels) == 1


async def test_trilha_reexecutada_mantem_identidade_da_versao(
    ambiente: ConfirmacaoFalsa,
) -> None:
    from app.graph.nodes.validate_domain import validate_domain

    payload = exemplo("parametros-confirmados")
    estado = {
        "job_id": payload["job_id"],
        "regra_id": payload["regra_id"],
        "representacao_regra": regra(True).para_contrato(),
    }
    config = {"configurable": {"producers": ambiente.producers}}

    await validate_domain(estado, config)
    await validate_domain(estado, config)

    primeira, segunda = [p for _, p in ambiente.publicacoes]
    assert primeira["evento_id"] == segunda["evento_id"]
    assert primeira["regra_id"] == segunda["regra_id"] == payload["regra_id"]
    assert primeira["conclusao"] == segunda["conclusao"]


async def test_percentual_ausente_barrado_nomeia_elemento_sem_modelo(
    ambiente: ConfirmacaoFalsa,
) -> None:
    ambiente.buscar_regra.return_value = RepresentacaoRegra.model_validate(
        {"nucleo": {}, "especificacoes": []}
    )
    payload = exemplo("parametros-confirmados")

    await ambiente.consumer.receber(mensagem(payload))

    assert (await ambiente.estado(payload)).values["conflitos"] == [
        {"elementos": ["nucleo.percentual"], "motivo": "percentual ausente"}
    ]
    assert (
        ambiente.publicacoes[1][1]["conclusao"]["resumo"]
        == "Regra barrada: 1 conflito(s). Elementos: nucleo.percentual."
    )
    assert ambiente.modelo.seen_messages == []


def amostra(texto: str, nome: str, labels: dict[str, str]) -> float:
    return next(
        (
            a.value
            for f in text_string_to_metric_families(texto)
            for a in f.samples
            if a.name == nome and a.labels == labels
        ),
        0.0,
    )


async def test_metricas_e_logs_dos_desfechos_no_caminho_real_sem_vazamento(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    antes = (await cliente.get("/metrics")).text
    jobs: list[str] = []
    for conflito in (False, True):
        payload = exemplo("parametros-confirmados") | {
            "job_id": str(uuid4()),
            "regra_id": str(uuid4()),
        }
        jobs.append(payload["job_id"])
        ambiente.buscar_regra.return_value = regra(conflito)
        await ambiente.consumer.receber(mensagem(payload))
        assert job_id_ctx.get() is None
        assert no_ctx.get() is None
    depois = (await cliente.get("/metrics")).text

    for nome in ("job_runs_total", "job_duration_seconds_count"):
        labels = {"job_name": "validate_domain"}
        assert amostra(depois, nome, labels) - amostra(antes, nome, labels) == 2
    labels = {"job_name": "validate_domain"}
    assert amostra(depois, "job_failures_total", labels) == amostra(
        antes, "job_failures_total", labels
    )
    for resultado in ("liberada", "barrada"):
        labels = {"resultado": resultado}
        assert (
            amostra(depois, "codegen_validacao_dominio_resultados_total", labels)
            - amostra(antes, "codegen_validacao_dominio_resultados_total", labels)
            == 1
        )
    eventos = [log for log in logs if log.get("no") == "validacao_dominio"]
    assert [log["job_id"] for log in eventos] == [jobs[0], jobs[0], jobs[1], jobs[1]]
    assert [log["message"] for log in eventos] == [
        "domain validation started",
        "domain validation finished",
    ] * 2
    assert eventos[-1]["extra"] == {
        "resultado": "barrada",
        "quantidade_conflitos": 1,
        "elementos": ["elem.1"],
    }
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    for log in logs:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(log)
    serializados = simplejson.dumps(logs)
    for privado in ("CONTEUDO_PRIVADO", "50000", "40000", "limite inferior", "representacao_regra"):
        assert privado not in serializados


async def test_reentrega_apos_fim_nao_revalida_nem_conta_execucao(
    ambiente: ConfirmacaoFalsa, monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient
) -> None:
    payload = exemplo("parametros-confirmados")
    await ambiente.consumer.receber(mensagem(payload))
    monkeypatch.setattr(
        "app.mensageria.roteamento.buscar_regra_do_resultado",
        AsyncMock(return_value=UUID(payload["regra_id"])),
    )
    monkeypatch.setattr("app.graph.nodes.decision.tem_sugestao", AsyncMock(return_value=False))
    resultado = exemplo("simulacao-concluida") | {"job_id": payload["job_id"], "veredito": "viavel"}
    await Consumer(SimulacaoConcluida, "simulacao-concluida", ambiente.roteador).receber(
        mensagem(resultado)
    )
    antes = (await cliente.get("/metrics")).text
    eventos = list(ambiente.publicacoes)

    await ambiente.consumer.receber(mensagem(payload))

    depois = (await cliente.get("/metrics")).text
    labels = {"job_name": "validate_domain"}
    assert (await ambiente.estado(payload)).values["regra_liberada"] is True
    assert amostra(depois, "job_runs_total", labels) == amostra(antes, "job_runs_total", labels)
    assert ambiente.publicacoes == eventos
    assert len(ambiente.modelo.seen_messages) == 1
