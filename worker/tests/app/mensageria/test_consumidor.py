import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker
from app.mensageria.consumidor import consumir_fila_execucao
from app.repositorio.codigos_gerados import CodigoGerado, CodigoNaoEncontradoError


class _ProcessoFalso:
    """Reproduz o essencial de aio_pika.message.ProcessContext: aceita em sucesso,
    rejeita (sem requeue) e deixa a exceção propagar quando o corpo do `async with`
    falha"""

    def __init__(self, mensagem: "MensagemFalsa") -> None:
        self._mensagem = mensagem

    async def __aenter__(self) -> "MensagemFalsa":
        return self._mensagem

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc_type is None:
            self._mensagem.aceita = True
        else:
            self._mensagem.rejeitada = True
        return False


@dataclass
class MensagemFalsa:
    body: bytes
    aceita: bool = field(default=False, init=False)
    rejeitada: bool = field(default=False, init=False)

    def process(self, requeue: bool = False) -> _ProcessoFalso:
        assert requeue is False
        return _ProcessoFalso(self)


class FilaFalsa:
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


async def test_mensagem_invalida_e_rejeitada_e_nao_interrompe_a_fila(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalida = MensagemFalsa(body=b"{}")
    valida = MensagemFalsa(body=_corpo_comando())
    codigo = CodigoGerado(id=uuid4(), job_id=uuid4(), linguagem="python", fonte="pass")
    monkeypatch.setattr(consumidor, "buscar_codigo", AsyncMock(return_value=codigo))
    monkeypatch.setattr(consumidor, "get_sessionmaker", lambda: _SessionmakerFalso())

    fila = FilaFalsa([invalida, valida])
    broker = ConexaoBroker(conexao=AsyncMock(), canal=AsyncMock(), fila=fila)  # type: ignore[arg-type]

    await consumir_fila_execucao(broker)

    assert invalida.rejeitada is True
    assert valida.aceita is True


async def test_codigo_nao_encontrado_rejeita_a_mensagem_com_erro_especifico(
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
    broker = ConexaoBroker(conexao=AsyncMock(), canal=AsyncMock(), fila=fila)  # type: ignore[arg-type]

    await consumir_fila_execucao(broker)

    assert mensagem.rejeitada is True
    assert mensagem.aceita is False


async def test_dois_comandos_sao_processados_um_de_cada_vez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordem: list[str] = []

    async def _processar_instrumentado(mensagem: MensagemFalsa) -> None:
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
