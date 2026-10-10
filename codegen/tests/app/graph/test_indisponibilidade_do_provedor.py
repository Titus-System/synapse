"""Indisponibilidade do provedor de LLM (T-268): classificação, espera, aviso e encerramento."""

import logging
from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson
from google.genai.errors import ClientError, ServerError
from httpx import AsyncClient, ConnectError, ReadTimeout
from jsonschema import Draft202012Validator, FormatChecker
from langchain_core.messages import AIMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from prometheus_client.parser import text_string_to_metric_families

from app.contratos.mensagens import EtapaAlterada
from app.core.logger import FormatadorJson, ManipuladorFilaContexto, job_id_ctx, no_ctx
from app.graph.core.llm import disponibilidade
from app.graph.core.llm.disponibilidade import (
    JobEncerradoDuranteEsperaError,
    chamar_com_espera_do_provedor,
    e_indisponibilidade_do_provedor,
)
from app.graph.nodes.code_generation import (
    ProvedorIndisponivelGeracaoError,
    code_generation,
)
from app.graph.nodes.extract_rule import ProvedorIndisponivelExtracaoError
from tests.app.confirmacao_falsa import mensagem
from tests.app.graph.conftest import FakeChatModel
from tests.app.graph.test_extracao import SAIDA, AmbienteExtracao
from tests.app.test_mensageria import CONTRATOS

SEGREDO = "SEGREDO_DO_PROVEDOR"


def _servidor(codigo: int = 503) -> ServerError:
    return ServerError(codigo, {"error": {"message": SEGREDO, "status": "UNAVAILABLE"}})


def _cliente(codigo: int) -> ClientError:
    return ClientError(codigo, {"error": {"message": SEGREDO, "status": "ERRO"}})


class Relogio:
    """Relógio e `sleep` falsos: dormir só adianta o tempo, então nada espera de verdade."""

    def __init__(self) -> None:
        self.instante = 0.0
        self.esperas: list[float] = []

    def agora(self) -> float:
        return self.instante

    async def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.instante += segundos


@pytest.fixture
def relogio(monkeypatch: pytest.MonkeyPatch) -> Relogio:
    falso = Relogio()
    monkeypatch.setattr(disponibilidade, "_dormir", falso.dormir)
    monkeypatch.setattr(disponibilidade, "_agora", falso.agora)
    return falso


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


async def _nunca_encerrado() -> bool:
    return False


def _roteirizada(*resultados: Any) -> tuple[Callable[[], Awaitable[str]], list[int]]:
    chamadas: list[int] = []
    restantes = list(resultados)

    async def chamada() -> str:
        chamadas.append(1)
        proximo = restantes.pop(0)
        if isinstance(proximo, Exception):
            raise proximo
        return str(proximo)

    return chamada, chamadas


# --- classificação -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "erro",
    [
        _servidor(500),
        _servidor(502),
        _servidor(503),
        _servidor(504),
        _cliente(429),
        ReadTimeout("x"),
        ConnectError("x"),
        TimeoutError("x"),
        ConnectionError("x"),
    ],
)
def test_classifica_como_indisponibilidade_do_provedor(erro: Exception) -> None:
    assert e_indisponibilidade_do_provedor(erro)


def test_classifica_o_erro_embrulhado_pelo_langchain() -> None:
    try:
        try:
            raise _servidor(503)
        except ServerError as original:
            raise ChatGoogleGenerativeAIError("Error calling model") from original
    except ChatGoogleGenerativeAIError as embrulhado:
        assert e_indisponibilidade_do_provedor(embrulhado)


@pytest.mark.parametrize(
    "erro",
    [
        _cliente(400),
        _cliente(401),
        _cliente(403),
        _cliente(404),
        RuntimeError("x"),
        ValueError("x"),
        ChatGoogleGenerativeAIError("sem causa"),
    ],
)
def test_nao_classifica_configuracao_invalida_nem_outras_falhas(erro: Exception) -> None:
    assert not e_indisponibilidade_do_provedor(erro)


# --- helper de espera --------------------------------------------------------------------


async def test_recupera_apos_duas_falhas_e_avisa_uma_vez(
    relogio: Relogio, logs: list[dict[str, Any]], cliente: AsyncClient
) -> None:
    chamada, chamadas = _roteirizada(_servidor(), _servidor(), "ok")
    avisar = AsyncMock()
    antes = (await cliente.get("/metrics")).text

    resultado = await chamar_com_espera_do_provedor(
        chamada,
        no="geracao_codigo",
        esgotada=ProvedorIndisponivelGeracaoError,
        avisar=avisar,
        encerrado=_nunca_encerrado,
    )

    assert resultado == "ok"
    assert len(chamadas) == 3
    assert relogio.esperas == [30, 60]
    avisar.assert_awaited_once_with()
    depois = (await cliente.get("/metrics")).text
    rotulos = {"no": "geracao_codigo", "desfecho": "recuperado"}
    assert (
        amostra(depois, "llm_provider_failures_total", rotulos)
        - amostra(antes, "llm_provider_failures_total", rotulos)
        == 1
    )
    assert amostra(depois, "llm_provider_failures_total", {**rotulos, "desfecho": "esgotado"}) == (
        amostra(antes, "llm_provider_failures_total", {**rotulos, "desfecho": "esgotado"})
    )
    espera = {"no": "geracao_codigo"}
    assert (
        amostra(depois, "llm_provider_wait_seconds_count", espera)
        - amostra(antes, "llm_provider_wait_seconds_count", espera)
        == 1
    )
    assert amostra(depois, "llm_provider_wait_seconds_sum", espera) - amostra(
        antes, "llm_provider_wait_seconds_sum", espera
    ) == pytest.approx(90)
    mensagens = [log["message"] for log in logs]
    assert mensagens == [
        "provider unavailable, waiting to retry",
        "provider unavailable, retrying after wait",
        "provider unavailable, retrying after wait",
        "provider recovered",
    ]
    assert all(log["extra"]["causa"] == "provedor_indisponivel" for log in logs)
    assert SEGREDO not in simplejson.dumps(logs)


async def test_esgota_a_janela_com_esperas_de_30_60_120_e_depois_120(
    relogio: Relogio, logs: list[dict[str, Any]], cliente: AsyncClient
) -> None:
    chamada, chamadas = _roteirizada(*[_servidor() for _ in range(20)])
    avisar = AsyncMock()
    antes = (await cliente.get("/metrics")).text

    with pytest.raises(ProvedorIndisponivelGeracaoError) as falha:
        await chamar_com_espera_do_provedor(
            chamada,
            no="geracao_codigo",
            esgotada=ProvedorIndisponivelGeracaoError,
            avisar=avisar,
            encerrado=_nunca_encerrado,
        )

    assert relogio.esperas == [30, 60, 120, 120, 120, 120]
    assert len(chamadas) == 7
    assert relogio.instante <= 600
    avisar.assert_awaited_once_with()
    assert falha.value.causa == "provedor_indisponivel"
    assert falha.value.etapa == "geracao_codigo"
    assert falha.value.__cause__ is None
    assert not falha.value.__suppress_context__ or falha.value.__context__ is None
    depois = (await cliente.get("/metrics")).text
    rotulos = {"no": "geracao_codigo", "desfecho": "esgotado"}
    assert (
        amostra(depois, "llm_provider_failures_total", rotulos)
        - amostra(antes, "llm_provider_failures_total", rotulos)
        == 1
    )
    espera = {"no": "geracao_codigo"}
    assert amostra(depois, "llm_provider_wait_seconds_sum", espera) - amostra(
        antes, "llm_provider_wait_seconds_sum", espera
    ) == pytest.approx(570)
    assert logs[-1]["message"] == "provider unavailable, retry window exhausted"
    assert logs[-1]["level"].lower() == "error"
    assert SEGREDO not in simplejson.dumps(logs)


async def test_o_tempo_das_chamadas_conta_na_janela(relogio: Relogio) -> None:
    async def chamada() -> str:
        relogio.instante += 200  # cada chamada demora 200 s antes de falhar
        raise _servidor()

    with pytest.raises(ProvedorIndisponivelExtracaoError):
        await chamar_com_espera_do_provedor(
            chamada,
            no="extracao_parametros",
            esgotada=ProvedorIndisponivelExtracaoError,
            avisar=AsyncMock(),
            encerrado=_nunca_encerrado,
        )

    assert relogio.esperas == [30, 60]


@pytest.mark.parametrize("erro", [_cliente(400), _cliente(401), RuntimeError("x")])
async def test_outras_falhas_sobem_sem_espera_nem_aviso(
    relogio: Relogio, cliente: AsyncClient, erro: Exception
) -> None:
    chamada, chamadas = _roteirizada(erro)
    avisar = AsyncMock()
    antes = (await cliente.get("/metrics")).text

    with pytest.raises(type(erro)) as subiu:
        await chamar_com_espera_do_provedor(
            chamada,
            no="geracao_codigo",
            esgotada=ProvedorIndisponivelGeracaoError,
            avisar=avisar,
            encerrado=_nunca_encerrado,
        )

    assert subiu.value is erro
    assert len(chamadas) == 1
    assert relogio.esperas == []
    avisar.assert_not_awaited()
    assert (await cliente.get("/metrics")).text.count("llm_provider_failures_total") == (
        antes.count("llm_provider_failures_total")
    )


async def test_job_encerrado_durante_a_espera_nao_recebe_nova_tentativa(
    relogio: Relogio,
) -> None:
    chamada, chamadas = _roteirizada(_servidor(), "nunca")

    async def encerrado() -> bool:
        return True

    with pytest.raises(JobEncerradoDuranteEsperaError):
        await chamar_com_espera_do_provedor(
            chamada,
            no="geracao_codigo",
            esgotada=ProvedorIndisponivelGeracaoError,
            avisar=AsyncMock(),
            encerrado=encerrado,
        )

    assert len(chamadas) == 1
    assert relogio.esperas == [30]


@pytest.fixture
def job_aberto(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    encerrado = AsyncMock(return_value=False)
    monkeypatch.setattr("app.repositorio.encerramentos.foi_encerrado", encerrado)
    return encerrado


# --- nó code_generation ------------------------------------------------------------------


async def test_code_generation_conclui_depois_de_dois_503_com_um_unico_aviso(
    monkeypatch: pytest.MonkeyPatch, relogio: Relogio, job_aberto: AsyncMock
) -> None:
    resposta = AIMessage(
        content="```python\ndef aplicar_regra(): ...\n```",
        response_metadata={"finish_reason": "STOP"},
    )
    modelo = MagicMock()
    modelo.ainvoke = AsyncMock(side_effect=[_servidor(), _servidor(), resposta])
    monkeypatch.setattr("app.graph.nodes.code_generation.get_model", lambda _: modelo)
    producers = MagicMock(etapa_alterada=AsyncMock())
    job_id = uuid4()
    estado: Any = {
        "job_id": str(job_id),
        "representacao_regra": {"nucleo": {}, "especificacoes": []},
    }

    update = await code_generation(
        estado, {"configurable": {"producers": producers, "sessoes": object()}}
    )

    assert "def aplicar_regra" in update["resposta_bruta"]
    assert modelo.ainvoke.await_count == 3
    producers.etapa_alterada.assert_awaited_once_with(
        EtapaAlterada(job_id=job_id, etapa="geracao_codigo", status="aguardando_provedor")
    )
    assert no_ctx.get() is None


# --- nó extract_rule, pelo consumer ------------------------------------------------------


async def test_extracao_recupera_apos_503_e_publica_um_unico_aviso(
    monkeypatch: pytest.MonkeyPatch, relogio: Relogio, job_aberto: AsyncMock
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada()
    resposta = AIMessage(
        content=simplejson.dumps(SAIDA, use_decimal=True),
        response_metadata={"finish_reason": "STOP"},
    )
    monkeypatch.setattr(
        FakeChatModel,
        "ainvoke",
        AsyncMock(side_effect=[_servidor(), _servidor(), resposta]),
    )
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    status = [p["status"] for nome, p in ambiente.publicacoes if nome == "etapa-alterada"]
    assert status == ["iniciada", "aguardando_provedor"]
    assert relogio.esperas == [30, 60]


async def test_extracao_esgotada_publica_erro_com_causa_e_rejeita_sem_requeue(
    monkeypatch: pytest.MonkeyPatch,
    relogio: Relogio,
    job_aberto: AsyncMock,
    logs: list[dict[str, Any]],
    cliente: AsyncClient,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada()
    monkeypatch.setattr(FakeChatModel, "ainvoke", AsyncMock(side_effect=_servidor()))
    recebida = mensagem(payload)
    antes = (await cliente.get("/metrics")).text

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    recebida.nack.assert_not_awaited()
    etapas = [p for nome, p in ambiente.publicacoes if nome == "etapa-alterada"]
    assert [(p["status"], p.get("causa")) for p in etapas] == [
        ("iniciada", None),
        ("aguardando_provedor", None),
        ("erro", "provedor_indisponivel"),
    ]
    assert etapas[-1]["etapa"] == "extracao_parametros"
    depois = (await cliente.get("/metrics")).text
    rotulos = {"no": "extracao_parametros", "desfecho": "esgotado"}
    assert (
        amostra(depois, "llm_provider_failures_total", rotulos)
        - amostra(antes, "llm_provider_failures_total", rotulos)
        == 1
    )
    esquema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    validador = Draft202012Validator(esquema, format_checker=FormatChecker())
    do_provedor = [log for log in logs if log["message"].startswith("provider ")]
    assert do_provedor
    for log in do_provedor:
        validador.validate(log)
        assert log["job_id"] == payload["job_id"]
        assert log["no"] == "extracao_parametros"
        assert log["extra"]["causa"] == "provedor_indisponivel"
    assert SEGREDO not in simplejson.dumps(logs)
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None


async def test_job_encerrado_na_espera_descarta_a_mensagem_sem_avisar_erro(
    monkeypatch: pytest.MonkeyPatch, relogio: Relogio
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    monkeypatch.setattr(FakeChatModel, "ainvoke", AsyncMock(side_effect=_servidor()))
    monkeypatch.setattr("app.repositorio.encerramentos.foi_encerrado", AsyncMock(return_value=True))
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    status = [p["status"] for nome, p in ambiente.publicacoes if nome == "etapa-alterada"]
    assert "erro" not in status
    assert relogio.esperas == [30]


def test_exemplos_dos_contratos_novos_validam_no_modelo() -> None:
    exemplo = {
        "job_id": UUID(int=1),
        "etapa": "geracao_codigo",
        "status": "erro",
        "causa": "provedor_indisponivel",
    }
    assert EtapaAlterada.model_validate(exemplo).causa == "provedor_indisponivel"
    assert EtapaAlterada.model_validate({**exemplo, "causa": None, "status": "x"}).causa is None
