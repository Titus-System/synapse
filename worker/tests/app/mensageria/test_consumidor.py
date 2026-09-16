import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aio_pika import Message
from pamqp.commands import Basic

from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker
from app.mensageria.consumidor import consumir_fila_execucao
from app.repositorio.codigos_gerados import CodigoGerado, CodigoNaoEncontradoError


class MensagemFalsa(Message):
    def __init__(self, body: bytes) -> None:
        super().__init__(body=body)
        self.aceita = False
        self.requeued = False

    async def ack(self) -> None:
        self.aceita = True

    async def nack(self, requeue: bool) -> None:
        self.requeued = requeue


class FilaFalsa:
    name = "executar-codigo"

    def __init__(self, mensagens: list[MensagemFalsa]) -> None:
        self._mensagens = mensagens

    def iterator(self) -> "FilaFalsa":
        return self

    async def __aenter__(self) -> AsyncIterator[MensagemFalsa]:
        return self._gerador()

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def _gerador(self) -> AsyncIterator[MensagemFalsa]:
        for mensagem in self._mensagens:
            yield mensagem


def _corpo_comando(**overrides: Any) -> bytes:
    dados: dict[str, Any] = {
        "job_id": str(uuid4()),
        "codigo_gerado_id": str(uuid4()),
        "competencias": ["2025-08"],
        "orcamento": 100000.0,
    }
    dados.update(overrides)
    return json.dumps(dados).encode("utf-8")


async def test_mensagem_invalida_vai_a_dlq_e_nao_interrompe_a_fila(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalida = MensagemFalsa(body=b"{}")
    valida = MensagemFalsa(body=_corpo_comando())
    codigo = CodigoGerado(id=uuid4(), job_id=uuid4(), linguagem="python", fonte="pass")
    monkeypatch.setattr(consumidor, "buscar_codigo", AsyncMock(return_value=codigo))
    monkeypatch.setattr(consumidor, "get_sessionmaker", lambda: _SessionmakerFalso())

    fila = FilaFalsa([invalida, valida])
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock(return_value=Basic.Ack())
    broker = ConexaoBroker(conexao=AsyncMock(), canal=canal, fila=fila)  # type: ignore[arg-type]

    await consumir_fila_execucao(broker)

    assert invalida.aceita is True
    canal.default_exchange.publish.assert_awaited_once()
    assert canal.default_exchange.publish.call_args.kwargs["routing_key"] == "executar-codigo.dlq"
    assert valida.aceita is True


async def test_codigo_nao_encontrado_vai_direto_a_dlq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codigo_gerado_id = uuid4()
    monkeypatch.setattr(
        consumidor,
        "buscar_codigo",
        AsyncMock(side_effect=CodigoNaoEncontradoError(codigo_gerado_id)),
    )
    monkeypatch.setattr(consumidor, "get_sessionmaker", lambda: _SessionmakerFalso())

    mensagem = MensagemFalsa(body=_corpo_comando(codigo_gerado_id=str(codigo_gerado_id)))
    fila = FilaFalsa([mensagem])
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock(return_value=Basic.Ack())
    broker = ConexaoBroker(conexao=AsyncMock(), canal=canal, fila=fila)  # type: ignore[arg-type]

    await consumir_fila_execucao(broker)

    assert mensagem.aceita is True
    canal.default_exchange.publish.assert_awaited_once()
    assert canal.default_exchange.publish.call_args.kwargs["routing_key"] == "executar-codigo.dlq"
    copia = canal.default_exchange.publish.call_args.args[0]
    assert copia.body == mensagem.body
    assert copia.headers == {}


async def test_dois_comandos_sao_processados_um_de_cada_vez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordem: list[str] = []

    async def _processar_instrumentado(mensagem: MensagemFalsa, broker: ConexaoBroker) -> None:
        identificador = mensagem.body.decode()
        ordem.append(f"entrou:{identificador}")
        await asyncio.sleep(0.01)
        ordem.append(f"saiu:{identificador}")

    monkeypatch.setattr(consumidor, "_processar", _processar_instrumentado)

    mensagens = [MensagemFalsa(body=b"1"), MensagemFalsa(body=b"2")]
    fila = FilaFalsa(mensagens)
    broker = ConexaoBroker(conexao=AsyncMock(), canal=AsyncMock(), fila=fila)  # type: ignore[arg-type]

    await consumir_fila_execucao(broker)

    assert ordem == ["entrou:1", "saiu:1", "entrou:2", "saiu:2"]


class _SessaoFalsa:
    async def __aenter__(self) -> "_SessaoFalsa":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _SessionmakerFalso:
    def __call__(self) -> _SessaoFalsa:
        return _SessaoFalsa()
