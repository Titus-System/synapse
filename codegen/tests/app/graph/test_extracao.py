import asyncio
import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import simplejson
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker
from langchain_core.messages import AIMessage
from prometheus_client.parser import text_string_to_metric_families

from app.contratos.mensagens import RegraSubmetida
from app.core.logger import FormatadorJson, ManipuladorFilaContexto, job_id_ctx, no_ctx
from app.mensageria.consumers import Consumer
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.extracao_falsa import BancoExtracaoFalso
from tests.app.graph.conftest import FakeChatModel
from tests.app.test_mensageria import CONTRATOS

TEXTO = "Pague 2,5% na loja 13. REGRA_PRIVADA"
NUCLEO = {"percentual": Decimal("0.025"), "loja": ["13"]}
SAIDA = {"nucleo": NUCLEO, "elementos": []}


@pytest.fixture
def logs() -> Iterator[list[dict[str, Any]]]:
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


class AmbienteExtracao(ConfirmacaoFalsa):
    def __init__(self, monkeypatch: pytest.MonkeyPatch, saidas: list[Any] | None = None) -> None:
        super().__init__(monkeypatch)
        self.banco = BancoExtracaoFalso()
        self.roteador.sessoes = self.banco
        self.producers.regra_extraida = AsyncMock(side_effect=self._publicador("regra-extraida"))
        self.modelo_extracao = FakeChatModel(
            messages=iter(
                [
                    AIMessage(
                        content=s if isinstance(s, str) else simplejson.dumps(s, use_decimal=True)
                    )
                    for s in (saidas if saidas is not None else [SAIDA] * 4)
                ]
            )
        )
        monkeypatch.setattr("app.graph.core.llm.registry.get_model", lambda _: self.modelo_extracao)
        self.consumer = Consumer(RegraSubmetida, "regra-submetida", self.roteador)

    def entrada(self, origem: str = "texto") -> dict[str, Any]:
        payload = {
            "job_id": str(uuid4()),
            "submissao_id": str(uuid4()),
            "origem": origem,
            "competencias": ["2025-11"],
            "orcamento": Decimal("500"),
        }
        self.banco.transcricoes[UUID(payload["submissao_id"])] = TEXTO
        return payload


@pytest.mark.parametrize("origem", ["voz", "texto"])
async def test_extracao_persiste_publica_ids_e_termina_ciclo(
    monkeypatch: pytest.MonkeyPatch,
    origem: str,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada(origem)
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert [nome for nome, _ in ambiente.publicacoes] == [
        "etapa-alterada",
        "regra-extraida",
        "no-concluido",
    ]
    [prompt] = ambiente.banco.tabela("prompts")
    [resposta] = ambiente.banco.tabela("respostas_modelo")
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    assert prompt["no"] == "extracao_parametros"
    assert resposta["prompt_id"] == prompt["id"]
    assert simplejson.loads(extracao["representacao"], use_decimal=True) == {
        "nucleo": NUCLEO,
        "especificacoes": [],
    }
    assert ambiente.publicacoes[1][1] == {
        "job_id": payload["job_id"],
        "submissao_id": payload["submissao_id"],
        "extracao_id": str(extracao["id"]),
    }
    trilha = ambiente.publicacoes[2][1]
    assert trilha["prompt_id"] == str(prompt["id"])
    assert trilha["no"] == "extracao_parametros"
    assert "regra_id" not in trilha
    assert trilha["conclusao"]["elementos_extraidos"] == ["nucleo.percentual", "nucleo.loja"]
    estado = await ambiente.estado(payload)
    assert estado.next == ()
    assert estado.values["prompt_id"] == str(prompt["id"])
    assert estado.values["resposta_id"] == str(resposta["id"])
    assert estado.values["submissao_id"] == payload["submissao_id"]
    for artefato in ("representacao_regra", "prompt_enviado", "resposta_bruta", "messages"):
        assert artefato not in estado.values or not estado.values[artefato]


@pytest.mark.parametrize("texto", [None, "", " \n\t"])
async def test_transcricao_indisponivel_rejeita_sem_modelo(
    monkeypatch: pytest.MonkeyPatch,
    texto: str | None,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = texto
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    assert ambiente.modelo_extracao.seen_messages == []
    assert ambiente.publicacoes[-1][1]["etapa"] == "extracao_parametros"
    assert ambiente.publicacoes[-1][1]["status"] == "erro"
    assert ambiente.banco.tabela("prompts") == []


async def test_saida_invalida_encerra_job_sem_publicar_extracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch, ["RESPOSTA_PRIVADA_INVALIDA"])
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    assert len(ambiente.modelo_extracao.seen_messages) == 1
    ambiente.producers.regra_extraida.assert_not_awaited()
    assert ambiente.banco.tabela("prompts") == []
    assert ambiente.publicacoes[-1][1]["status"] == "erro"


async def test_falha_transitoria_reentrega_sem_erro_do_job(monkeypatch: pytest.MonkeyPatch) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada()
    ambiente.banco.falhar_em = ("extracoes_regras",)
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.nack.assert_awaited_once_with(requeue=True)
    assert ambiente.banco.tabela("prompts") == []
    assert all(p.get("status") != "erro" for _, p in ambiente.publicacoes)
    ambiente.banco.falhar_em = ()
    repetida = mensagem(payload)
    await ambiente.consumer.receber(repetida)
    repetida.ack.assert_awaited_once_with()


async def test_reentrega_apos_publicacao_reusa_artefato_e_nao_duplica_trilha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada()
    original = ambiente.producers.no_concluido.side_effect
    ambiente.producers.no_concluido.side_effect = RuntimeError("BROKER_PRIVADO")
    primeira = mensagem(payload)
    await ambiente.consumer.receber(primeira)
    primeira.nack.assert_awaited_once_with(requeue=True)
    primeiro_evento = ambiente.producers.no_concluido.await_args.args[0]
    ambiente.producers.no_concluido.side_effect = original

    segunda = mensagem(payload)
    await ambiente.consumer.receber(segunda)

    segunda.ack.assert_awaited_once_with()
    assert len(ambiente.modelo_extracao.seen_messages) == 1
    assert all(
        len(ambiente.banco.tabela(t)) == 1
        for t in ("prompts", "respostas_modelo", "extracoes_regras")
    )
    assert ambiente.producers.no_concluido.await_args.args[0].evento_id == primeiro_evento.evento_id
    anteriores = list(ambiente.publicacoes)
    terceira = mensagem(payload)
    await ambiente.consumer.receber(terceira)
    terceira.ack.assert_awaited_once_with()
    assert ambiente.publicacoes == anteriores
    assert len(ambiente.modelo_extracao.seen_messages) == 1


async def test_nao_descarta_elemento_generico(monkeypatch: pytest.MonkeyPatch) -> None:
    elemento = {
        "construto_pretendido": "forma_privada",
        "descricao": "PARAFRASE_PRIVADA",
        "trecho": TEXTO,
    }
    ambiente = AmbienteExtracao(monkeypatch, [{"nucleo": {}, "elementos": [elemento]}])
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(extracao["representacao"])["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": "PARAFRASE_PRIVADA"}
    ]


def amostra(texto: str, nome: str, rotulos: dict[str, str]) -> float:
    return next(
        (
            s.value
            for f in text_string_to_metric_families(texto)
            for s in f.samples
            if s.name == nome and s.labels == rotulos
        ),
        0.0,
    )


@pytest.mark.parametrize(
    "falha",
    [
        None,
        "transcricao_indisponivel",
        "saida_invalida",
        "provedor",
        "persistencia",
        "publicacao",
        "cancelamento",
    ],
)
async def test_logs_e_metricas_pelo_caminho_real_em_sucesso_e_falha(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
    falha: str | None,
) -> None:
    elemento = {
        "construto_pretendido": "FORMA_PRIVADA",
        "descricao": "PARAFRASE_PRIVADA",
        "trecho": TEXTO,
    }
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": NUCLEO, "elementos": [elemento, {"trecho": TEXTO}]}]
    )
    payload = ambiente.entrada()
    aguardando = asyncio.Event()
    if falha == "transcricao_indisponivel":
        ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = ""
    elif falha == "saida_invalida":
        ambiente.modelo_extracao.messages = iter([AIMessage(content="RESPOSTA_PRIVADA_INVALIDA")])
    elif falha in ("provedor", "cancelamento"):

        async def falhar(*args: Any, **kwargs: Any) -> Any:
            if falha == "cancelamento":
                aguardando.set()
                await asyncio.Event().wait()
            raise ConnectionError("TRANSCRICAO_PRIVADA_DO_PROVEDOR")

        monkeypatch.setattr(FakeChatModel, "ainvoke", falhar)
    elif falha == "publicacao":
        ambiente.producers.regra_extraida.side_effect = RuntimeError("BROKER_PRIVADO")
    elif falha == "persistencia":
        ambiente.banco.falhar_em = ("extracoes_regras",)
    antes = (await cliente.get("/metrics")).text
    recebida = mensagem(payload)

    if falha == "cancelamento":
        tarefa = asyncio.create_task(ambiente.consumer.receber(recebida))
        await asyncio.wait_for(aguardando.wait(), timeout=5)
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa
    else:
        await ambiente.consumer.receber(recebida)

    depois = (await cliente.get("/metrics")).text
    for nome, esperado in (
        ("job_runs_total", 1),
        ("job_failures_total", 1 if falha else 0),
        ("job_duration_seconds_count", 1),
    ):
        rotulos = {"job_name": "extract_rule"}
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == esperado
    assert amostra(depois, "job_duration_seconds_sum", rotulos) > amostra(
        antes, "job_duration_seconds_sum", rotulos
    )
    for nome, label, valor in (
        ("codegen_extracao_elementos_total", "construto", "generico"),
        ("codegen_extracao_rebaixamentos_total", "motivo", "construto_nao_habilitado"),
        ("codegen_extracao_rebaixamentos_total", "motivo", "campo_obrigatorio_ausente"),
    ):
        rotulos = {label: valor}
        quantidade = 2 if label == "construto" else 1
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == (
            0 if falha else quantidade
        )
    if falha:
        rotulos = {"classe": falha}
        assert (
            amostra(depois, "codegen_extracao_falhas_total", rotulos)
            - amostra(antes, "codegen_extracao_falhas_total", rotulos)
            == 1
        )
    else:
        anteriores = depois
        await ambiente.consumer.receber(mensagem(payload))
        posteriores = (await cliente.get("/metrics")).text
        assert amostra(posteriores, "job_runs_total", {"job_name": "extract_rule"}) == amostra(
            anteriores, "job_runs_total", {"job_name": "extract_rule"}
        )
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    validador = Draft202012Validator(schema, format_checker=FormatChecker())
    do_no = [log for log in logs if log.get("no") == "extracao_parametros"]
    assert [log["message"] for log in do_no] == [
        "extraction started",
        "extraction failed" if falha else "extraction finished",
    ]
    for log in logs:
        validador.validate(log)
        assert log["job_id"] == payload["job_id"]
    for privado in (
        TEXTO,
        "PARAFRASE_PRIVADA",
        "FORMA_PRIVADA",
        "RESPOSTA_PRIVADA",
        "TRANSCRICAO_PRIVADA",
        "BROKER_PRIVADO",
        "representacao",
    ):
        assert privado not in simplejson.dumps(logs)
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None


@pytest.mark.parametrize(
    "nucleo",
    [
        {},
        {"percentual": Decimal("0.025")},
        {"vigencia": {"inicio": "2025-11", "fim": "2025-11"}},
        {"vigencia": {"inicio": "2025-08", "fim": "2025-12"}},
        {"vigencia": {"inicio": "2025-12", "fim": "2025-08"}, "percentual": Decimal("-0.1")},
        {
            "vigencia": {"inicio": "2025-11", "fim": "2025-11"},
            "loja": ["13"],
            "marca": ["10"],
            "cargo": ["100"],
            "percentual": Decimal("0.025000000000000000001"),
        },
    ],
)
async def test_casos_de_nucleo_da_t203_chegam_ao_artefato_sem_alteracao(
    monkeypatch: pytest.MonkeyPatch,
    nucleo: dict[str, Any],
) -> None:
    ambiente = AmbienteExtracao(monkeypatch, [{"nucleo": nucleo, "elementos": []}])
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [artefato] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(artefato["representacao"], use_decimal=True) == {
        "nucleo": nucleo,
        "especificacoes": [],
    }


async def test_correlacao_e_restaurada_entre_dois_jobs(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    primeiro, segundo = ambiente.entrada(), ambiente.entrada()
    ambiente.banco.transcricoes[UUID(primeiro["submissao_id"])] = ""
    token_job = job_id_ctx.set("contexto_anterior")
    token_no = no_ctx.set("decisao")
    try:
        await ambiente.consumer.receber(mensagem(primeiro))
        assert job_id_ctx.get() == "contexto_anterior"
        assert no_ctx.get() == "decisao"
        await ambiente.consumer.receber(mensagem(segundo))
        assert job_id_ctx.get() == "contexto_anterior"
        assert no_ctx.get() == "decisao"
    finally:
        no_ctx.reset(token_no)
        job_id_ctx.reset(token_job)
    assert [
        (log["job_id"], log["message"]) for log in logs if log.get("no") == "extracao_parametros"
    ] == [
        (primeiro["job_id"], "extraction started"),
        (primeiro["job_id"], "extraction failed"),
        (segundo["job_id"], "extraction started"),
        (segundo["job_id"], "extraction finished"),
    ]


@pytest.mark.parametrize("origem", ["formulario", "reprocessamento", "texto"])
async def test_guarda_do_no_recusa_entrada_invalida_pelo_grafo(
    monkeypatch: pytest.MonkeyPatch,
    origem: str,
) -> None:
    from app.falhas import FalhaDoJobError
    from app.graph.entrypoint import run_to_completion

    ambiente = AmbienteExtracao(monkeypatch)
    state: Any = {"job_id": str(uuid4()), "origem": origem, "competencias": ["2025-11"]}
    if origem != "texto":
        state["submissao_id"] = str(uuid4())

    with pytest.raises(FalhaDoJobError) as falha:
        await run_to_completion(
            state["job_id"], state, sessoes=ambiente.banco, producers=ambiente.producers
        )

    assert falha.value.etapa == "extracao_parametros"
    assert ambiente.modelo_extracao.seen_messages == []
    assert ambiente.banco.sql_executado == []


async def test_regra_gravada_abre_outro_ciclo_sem_repetir_extracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    entrada = ambiente.entrada()
    await ambiente.consumer.receber(mensagem(entrada))
    versao = {**entrada, "regra_id": str(uuid4())}
    recebida = mensagem(versao)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert len(ambiente.modelo_extracao.seen_messages) == 1
    assert len(ambiente.modelo.seen_messages) == 1
    assert (await ambiente.estado(entrada)).next == ()
    assert (await ambiente.estado(versao)).next == ("await_execution",)
    assert (await ambiente.estado(entrada)).values.get("regra_id") is None
    assert (await ambiente.estado(versao)).values["regra_id"] == versao["regra_id"]
    ambiente.producers.regra_extraida.assert_awaited_once()
    ambiente.producers.executar_codigo.assert_awaited_once()
