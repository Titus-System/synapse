import logging
from asyncio import CancelledError
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import simplejson
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker

from app.contratos.mensagens import EtapaAlterada
from app.core.logger import FormatadorJson, ManipuladorFilaContexto, job_id_ctx, no_ctx
from app.representacao_regra import RepresentacaoRegra
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.graph.test_validacao_principal import amostra
from tests.app.test_mensageria import CONTRATOS, exemplo

CONFLITOS = [
    {"elementos": ["nucleo.percentual"], "motivo": "percentual ausente"},
    {"elementos": ["elem.1"], "motivo": "limite inferior 50000 maior que o superior 40000"},
]


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> ConfirmacaoFalsa:
    """A regra padrão tem dois conflitos: o percentual ausente e uma faixa invertida."""
    confirmacao = ConfirmacaoFalsa(monkeypatch)
    confirmacao.buscar_regra.return_value = RepresentacaoRegra.model_validate(
        {
            "nucleo": {},
            "especificacoes": [
                {
                    "ref": "elem.1",
                    "construto": "faixa_valor",
                    "descricao": "CONTEUDO_PRIVADO",
                    "limite_inferior": 50000,
                    "limite_superior": 40000,
                    "efeito": {"tipo": "bonus_fixo", "valor": 3500},
                }
            ],
        }
    )
    return confirmacao


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


def pausa(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return (
        "etapa-alterada",
        {
            "job_id": payload["job_id"],
            "etapa": "confirmacao",
            "status": "aguardando_correcao",
            "regra_id": payload["regra_id"],
            "conflitos": CONFLITOS,
        },
    )


def falhar_uma_vez_na_pausa(ambiente: ConfirmacaoFalsa) -> None:
    publicar = ambiente.producers.etapa_alterada.side_effect
    falhou = False

    async def etapa_alterada(dto: EtapaAlterada) -> None:
        nonlocal falhou
        if dto.status == "aguardando_correcao" and not falhou:
            falhou = True
            raise RuntimeError("CONTEUDO_PRIVADO")
        await publicar(dto)

    ambiente.producers.etapa_alterada.side_effect = etapa_alterada


def delta(antes: str, depois: str, nome: str, labels: dict[str, str]) -> float:
    return amostra(depois, nome, labels) - amostra(antes, nome, labels)


async def test_regra_barrada_publica_a_pausa_e_encerra_o_ciclo_sem_falha(
    ambiente: ConfirmacaoFalsa,
) -> None:
    payload = exemplo("parametros-confirmados")
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    inicio, trilha, ultima = ambiente.publicacoes
    assert inicio == (
        "etapa-alterada",
        {"job_id": payload["job_id"], "etapa": "validacao_dominio", "status": "iniciada"},
    )
    assert (trilha[0], trilha[1]["no"]) == ("no-concluido", "validacao_dominio")
    assert ultima == pausa(payload)
    recebida.ack.assert_awaited_once_with()
    recebida.reject.assert_not_awaited()
    recebida.nack.assert_not_awaited()
    assert ambiente.modelo.seen_messages == []
    assert ambiente.banco.linhas == {}
    assert (await ambiente.estado(payload)).next == ()


async def test_regra_liberada_segue_para_a_geracao_sem_publicar_a_pausa(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient
) -> None:
    ambiente.buscar_regra.return_value = RepresentacaoRegra.model_validate(
        {"nucleo": {"percentual": Decimal("0.025")}, "especificacoes": []}
    )
    payload = exemplo("parametros-confirmados")
    antes = (await cliente.get("/metrics")).text

    await ambiente.consumer.receber(mensagem(payload))

    depois = (await cliente.get("/metrics")).text
    assert delta(antes, depois, "job_runs_total", {"job_name": "report_conflicts"}) == 0
    assert all(p["etapa"] != "confirmacao" for _, p in ambiente.publicacoes if "etapa" in p)
    assert (await ambiente.estado(payload)).next == ("await_execution",)


async def test_falha_ao_publicar_a_pausa_reenfileira_e_conta_falha_do_no(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    falhar_uma_vez_na_pausa(ambiente)
    payload = exemplo("parametros-confirmados")
    recebida = mensagem(payload)
    antes = (await cliente.get("/metrics")).text

    await ambiente.consumer.receber(recebida)

    recebida.nack.assert_awaited_once_with(requeue=True)
    recebida.ack.assert_not_awaited()
    recebida.reject.assert_not_awaited()
    depois = (await cliente.get("/metrics")).text
    for nome in ("job_runs_total", "job_failures_total", "job_duration_seconds_count"):
        assert delta(antes, depois, nome, {"job_name": "report_conflicts"}) == 1
    assert [p["status"] for nome, p in ambiente.publicacoes if nome == "etapa-alterada"] == [
        "iniciada"
    ]
    eventos = [log for log in logs if log.get("no") == "confirmacao"]
    assert [(log["level"], log["message"]) for log in eventos] == [
        ("ERROR", "conflict report failed")
    ]
    assert eventos[0]["job_id"] == payload["job_id"]
    assert eventos[0]["extra"] == {"classe": "falha_na_operacao"}
    for privado in ("CONTEUDO_PRIVADO", "percentual ausente", "limite inferior"):
        assert privado not in simplejson.dumps(logs)


async def test_reentrega_depois_da_falha_publica_so_a_pausa_sem_revalidar(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient
) -> None:
    falhar_uma_vez_na_pausa(ambiente)
    payload = exemplo("parametros-confirmados")
    await ambiente.consumer.receber(mensagem(payload))
    publicadas = len(ambiente.publicacoes)
    antes = (await cliente.get("/metrics")).text
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert ambiente.publicacoes[publicadas:] == [pausa(payload)]
    depois = (await cliente.get("/metrics")).text
    assert delta(antes, depois, "job_runs_total", {"job_name": "validate_domain"}) == 0
    resultado = {"resultado": "barrada"}
    assert delta(antes, depois, "codegen_validacao_dominio_resultados_total", resultado) == 0
    assert delta(antes, depois, "job_runs_total", {"job_name": "report_conflicts"}) == 1
    assert (await ambiente.estado(payload)).next == ()


async def test_reentrega_depois_do_fim_do_ciclo_nao_publica_de_novo(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient
) -> None:
    payload = exemplo("parametros-confirmados")
    await ambiente.consumer.receber(mensagem(payload))
    publicadas = list(ambiente.publicacoes)
    antes = (await cliente.get("/metrics")).text
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert ambiente.publicacoes == publicadas
    depois = (await cliente.get("/metrics")).text
    assert delta(antes, depois, "job_runs_total", {"job_name": "report_conflicts"}) == 0


async def test_logs_e_metricas_da_pausa_no_caminho_real_sem_vazamento(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    antes = (await cliente.get("/metrics")).text
    jobs: list[dict[str, Any]] = []
    for _ in range(2):
        payload = exemplo("parametros-confirmados") | {
            "job_id": str(uuid4()),
            "regra_id": str(uuid4()),
        }
        jobs.append(payload)
        await ambiente.consumer.receber(mensagem(payload))
        assert job_id_ctx.get() is None
        assert no_ctx.get() is None
    depois = (await cliente.get("/metrics")).text

    for nome in ("job_runs_total", "job_duration_seconds_count"):
        assert delta(antes, depois, nome, {"job_name": "report_conflicts"}) == 2
    assert delta(antes, depois, "job_failures_total", {"job_name": "report_conflicts"}) == 0
    resultado = {"resultado": "barrada"}
    assert delta(antes, depois, "codegen_validacao_dominio_resultados_total", resultado) == 2
    eventos = [log for log in logs if log.get("no") == "confirmacao"]
    assert [(log["job_id"], log["level"], log["message"]) for log in eventos] == [
        (job["job_id"], "INFO", "domain conflicts published") for job in jobs
    ]
    assert [log["extra"] for log in eventos] == [
        {"quantidade_conflitos": 2, "elementos": ["nucleo.percentual", "elem.1"]} for _ in jobs
    ]
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    for log in logs:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(log)
    serializados = simplejson.dumps(logs)
    for privado in ("CONTEUDO_PRIVADO", "percentual ausente", "50000", "40000", "limite inferior"):
        assert privado not in serializados


@pytest.mark.parametrize("cancelamento", [False, True])
async def test_erro_inesperado_ou_cancelamento_ao_publicar_e_sanitizado(
    ambiente: ConfirmacaoFalsa, cancelamento: bool
) -> None:
    from app.graph.nodes.report_conflicts import report_conflicts

    erro = CancelledError("CONTEUDO_PRIVADO") if cancelamento else RuntimeError("CONTEUDO_PRIVADO")
    ambiente.producers.etapa_alterada.side_effect = erro
    estado = {
        "job_id": str(uuid4()),
        "regra_id": str(uuid4()),
        "conflitos": [{"elementos": ["elem.1"], "motivo": "CONTEUDO_PRIVADO"}],
    }
    token = no_ctx.set("contexto-anterior")
    try:
        with pytest.raises(CancelledError if cancelamento else RuntimeError) as capturado:
            await report_conflicts(estado, {"configurable": {"producers": ambiente.producers}})
        assert str(capturado.value) == (
            "Conflict report cancelled" if cancelamento else "Conflict report failed"
        )
        assert capturado.value.__suppress_context__ is True
        assert no_ctx.get() == "contexto-anterior"
    finally:
        no_ctx.reset(token)


async def test_regra_id_publicado_e_o_da_versao_analisada_no_ciclo(
    ambiente: ConfirmacaoFalsa,
) -> None:
    analisada = uuid4()
    payload = exemplo("parametros-confirmados") | {"regra_id": str(analisada)}

    await ambiente.consumer.receber(mensagem(payload))

    ambiente.buscar_regra.assert_awaited_once_with(
        ambiente.banco, UUID(payload["job_id"]), analisada
    )
    assert ambiente.publicacoes[-1][1]["regra_id"] == str(analisada)
