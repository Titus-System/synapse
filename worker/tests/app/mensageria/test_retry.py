import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractIncomingMessage
from pamqp.commands import Basic
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.execucao.preparo import ExecucaoPreparada, PayloadContainer
from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker
from app.mensageria.contracts import ExecutarCodigo
from tests.app.mensageria.test_consumidor import FilaFalsa, _corpo_comando, _SessionmakerFalso


@pytest.fixture
def mensagem() -> MagicMock:
    original = Message(
        body=_corpo_comando(),
        headers={"traceparent": "contexto", "custom": {"chave": "valor"}},
        content_type="application/json",
        content_encoding="utf-8",
        correlation_id="correlacao",
        message_id="mensagem",
        type="executar-codigo",
        app_id="synapse-codegen",
        reply_to="resposta",
        priority=3,
        timestamp=datetime(2026, 9, 15, tzinfo=UTC),
    )
    mensagem = MagicMock(spec=AbstractIncomingMessage)
    for campo in (
        "body",
        "headers",
        "content_type",
        "content_encoding",
        "correlation_id",
        "message_id",
        "type",
        "app_id",
        "reply_to",
        "priority",
        "timestamp",
        "expiration",
    ):
        setattr(mensagem, campo, getattr(original, campo))
    mensagem.ack = AsyncMock()
    mensagem.nack = AsyncMock()
    return mensagem


@pytest.fixture
def broker(mensagem: MagicMock, monkeypatch: pytest.MonkeyPatch) -> ConexaoBroker:
    fila = FilaFalsa([mensagem])
    fila.name = "executar-codigo"
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock(return_value=Basic.Ack())
    monkeypatch.setattr(consumidor, "get_sessionmaker", lambda: _SessionmakerFalso())
    monkeypatch.setattr(consumidor, "buscar_codigo", AsyncMock())
    monkeypatch.setattr(consumidor, "preparar_execucao", MagicMock())
    return ConexaoBroker(conexao=AsyncMock(), canal=canal, fila=fila)  # type: ignore[arg-type]


async def test_sucesso_confirma_sem_republicar(broker: ConexaoBroker, mensagem: MagicMock) -> None:
    """A execução preparada é real: o resultado do sandbox é classificado contra o payload e o
    orçamento dela, e um `MagicMock` no lugar não montaria um envelope."""
    consumidor.preparar_execucao.return_value = ExecucaoPreparada(
        payload=PayloadContainer(
            job_id=uuid4(),
            codigo_gerado_id=uuid4(),
            linguagem="python",
            fonte="def aplicar_regra(b, a, c): ...",
            competencias=["2025-08"],
        ),
        orcamento=100000.0,
    )

    await consumidor.consumir_fila_execucao(broker)

    mensagem.ack.assert_awaited_once_with()
    mensagem.nack.assert_not_awaited()
    broker.canal.default_exchange.publish.assert_not_awaited()


@pytest.mark.parametrize("contador", [-1, True, "1", 1.5, None])
async def test_header_invalido_nao_reinicia_tentativas(
    broker: ConexaoBroker,
    mensagem: MagicMock,
    contador: Any,
) -> None:
    mensagem.headers["synapse_retry_count"] = contador
    consumidor.buscar_codigo.side_effect = ConnectionError()

    await consumidor.consumir_fila_execucao(broker)

    publicacao = broker.canal.default_exchange.publish
    assert publicacao.call_args.kwargs["routing_key"] == "executar-codigo.dlq"
    assert publicacao.call_args.args[0].headers == mensagem.headers
    mensagem.ack.assert_awaited_once_with()


@pytest.mark.parametrize(
    "erro",
    [
        ConnectionRefusedError(),
        TimeoutError(),
        PoolTimeoutError(),
        DBAPIError(None, None, Exception(), connection_invalidated=True),
    ],
)
async def test_falhas_de_acesso_ao_banco_recebem_retry(
    broker: ConexaoBroker,
    erro: Exception,
) -> None:
    consumidor.buscar_codigo.side_effect = erro

    await consumidor.consumir_fila_execucao(broker)

    publicacao = broker.canal.default_exchange.publish
    assert publicacao.call_args.kwargs["routing_key"] == "executar-codigo"
    assert publicacao.call_args.args[0].headers["synapse_retry_count"] == 1


async def test_erro_fora_do_acesso_ao_banco_nao_e_infra(broker: ConexaoBroker) -> None:
    consumidor.preparar_execucao.side_effect = OSError()

    await consumidor.consumir_fila_execucao(broker)

    assert (
        broker.canal.default_exchange.publish.call_args.kwargs["routing_key"]
        == "executar-codigo.dlq"
    )


async def test_validation_error_do_artefato_vai_a_dlq(broker: ConexaoBroker) -> None:
    with pytest.raises(ValidationError) as erro:
        ExecutarCodigo.model_validate_json(b"{}")
    consumidor.buscar_codigo.side_effect = erro.value

    await consumidor.consumir_fila_execucao(broker)

    assert (
        broker.canal.default_exchange.publish.call_args.kwargs["routing_key"]
        == "executar-codigo.dlq"
    )


@pytest.mark.parametrize("durante_publicacao", [False, True])
async def test_cancelamento_nao_confirma_original(
    broker: ConexaoBroker,
    mensagem: MagicMock,
    durante_publicacao: bool,
) -> None:
    if durante_publicacao:
        consumidor.buscar_codigo.side_effect = ConnectionError()
        broker.canal.default_exchange.publish.side_effect = asyncio.CancelledError()
    else:
        consumidor.buscar_codigo.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await consumidor.consumir_fila_execucao(broker)

    mensagem.ack.assert_not_awaited()
    mensagem.nack.assert_not_awaited()


async def test_falha_de_ack_nao_republica_novamente(
    broker: ConexaoBroker, mensagem: MagicMock
) -> None:
    consumidor.buscar_codigo.side_effect = ConnectionError()
    mensagem.ack.side_effect = ConnectionError()

    with pytest.raises(ConnectionError):
        await consumidor.consumir_fila_execucao(broker)

    broker.canal.default_exchange.publish.assert_awaited_once()
    mensagem.nack.assert_not_awaited()


async def test_retry_preserva_contexto_sem_expor_excecao(
    broker: ConexaoBroker,
    mensagem: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.core.logger import job_id_ctx

    consumidor.buscar_codigo.side_effect = ConnectionError("conteudo-confidencial")
    publicacao = broker.canal.default_exchange.publish
    contextos = []

    async def publicar(*args: object, **kwargs: object) -> Basic.Ack:
        contextos.append(job_id_ctx.get())
        return Basic.Ack()

    publicacao.side_effect = publicar
    token = job_id_ctx.set("contexto-anterior")
    try:
        await consumidor.consumir_fila_execucao(broker)
        assert job_id_ctx.get() == "contexto-anterior"
    finally:
        job_id_ctx.reset(token)

    assert contextos == [str(ExecutarCodigo.model_validate_json(mensagem.body).job_id)]
    assert "conteudo-confidencial" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize(
    "contador,destino,esperado",
    [
        (None, "executar-codigo", 1),
        (1, "executar-codigo", 2),
        (2, "executar-codigo.dlq", 2),
        (3, "executar-codigo.dlq", 3),
    ],
)
async def test_infra_respeita_limite_e_preserva_comando(
    broker: ConexaoBroker,
    mensagem: MagicMock,
    contador: int | None,
    destino: str,
    esperado: int,
) -> None:
    if contador is not None:
        mensagem.headers["synapse_retry_count"] = contador
    headers_originais = dict(mensagem.headers)
    consumidor.buscar_codigo.side_effect = OperationalError(None, None, Exception("segredo"))

    await consumidor.consumir_fila_execucao(broker)

    publicacao = broker.canal.default_exchange.publish
    publicacao.assert_awaited_once()
    copia = publicacao.call_args.args[0]
    assert publicacao.call_args.kwargs == {"routing_key": destino, "mandatory": True}
    assert copia.headers == {**headers_originais, "synapse_retry_count": esperado}
    assert mensagem.headers == headers_originais
    assert copia.delivery_mode == DeliveryMode.PERSISTENT
    for campo in (
        "body",
        "content_type",
        "content_encoding",
        "correlation_id",
        "message_id",
        "type",
        "app_id",
        "reply_to",
        "priority",
        "timestamp",
    ):
        assert getattr(copia, campo) == getattr(mensagem, campo)
    mensagem.ack.assert_awaited_once_with()
    mensagem.nack.assert_not_awaited()


@pytest.mark.parametrize("corpo", [b"{}", b"json invalido", b'"segredo"'])
async def test_dto_invalido_vai_direto_a_dlq(
    broker: ConexaoBroker,
    mensagem: MagicMock,
    corpo: bytes,
) -> None:
    mensagem.body = corpo

    await consumidor.consumir_fila_execucao(broker)

    publicacao = broker.canal.default_exchange.publish
    assert publicacao.call_args.kwargs["routing_key"] == "executar-codigo.dlq"
    assert publicacao.call_args.args[0].body == corpo
    assert publicacao.call_args.args[0].headers == mensagem.headers
    consumidor.buscar_codigo.assert_not_awaited()
    mensagem.ack.assert_awaited_once_with()


@pytest.mark.parametrize(
    "erro",
    [
        TypeError("segredo"),
        AssertionError("segredo"),
        ProgrammingError(None, None, Exception("segredo")),
    ],
)
async def test_bug_nao_recebe_retry(
    broker: ConexaoBroker,
    mensagem: MagicMock,
    erro: Exception,
) -> None:
    consumidor.buscar_codigo.side_effect = erro

    await consumidor.consumir_fila_execucao(broker)

    publicacao = broker.canal.default_exchange.publish
    assert publicacao.call_args.kwargs["routing_key"] == "executar-codigo.dlq"
    assert publicacao.call_args.args[0].headers == mensagem.headers
    mensagem.ack.assert_awaited_once_with()


@pytest.mark.parametrize("permanente", [False, True])
@pytest.mark.parametrize("retorno", [RuntimeError("segredo"), Basic.Nack(), Basic.Reject(), None])
async def test_publicacao_sem_confirmacao_requeue_original(
    broker: ConexaoBroker,
    mensagem: MagicMock,
    permanente: bool,
    retorno: Any,
) -> None:
    if permanente:
        mensagem.body = b"{}"
    else:
        consumidor.buscar_codigo.side_effect = ConnectionError("segredo")
    publicacao = broker.canal.default_exchange.publish
    if isinstance(retorno, Exception):
        publicacao.side_effect = retorno
    else:
        publicacao.return_value = retorno

    await consumidor.consumir_fila_execucao(broker)

    publicacao.assert_awaited_once()
    mensagem.ack.assert_not_awaited()
    mensagem.nack.assert_awaited_once_with(requeue=True)


@pytest.mark.parametrize("permanente", [False, True])
async def test_ack_espera_confirmacao_do_broker(
    broker: ConexaoBroker,
    mensagem: MagicMock,
    permanente: bool,
) -> None:
    if permanente:
        mensagem.body = b"{}"
    else:
        consumidor.buscar_codigo.side_effect = ConnectionError("segredo")
    iniciou = asyncio.Event()
    confirmou = asyncio.Event()

    async def publicar(*args: object, **kwargs: object) -> Basic.Ack:
        iniciou.set()
        await confirmou.wait()
        return Basic.Ack()

    broker.canal.default_exchange.publish.side_effect = publicar
    tarefa = asyncio.create_task(consumidor.consumir_fila_execucao(broker))
    try:
        await asyncio.wait_for(iniciou.wait(), timeout=2)
        mensagem.ack.assert_not_awaited()
        confirmou.set()
        await asyncio.wait_for(tarefa, timeout=2)
    finally:
        tarefa.cancel()
        await asyncio.gather(tarefa, return_exceptions=True)

    mensagem.ack.assert_awaited_once_with()
