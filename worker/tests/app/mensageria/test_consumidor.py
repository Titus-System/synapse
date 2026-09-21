import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aio_pika import Message
from pamqp.commands import Basic

from app.execucao.container import SaidaBruta, SandboxInfraError
from app.execucao.preparo import PayloadContainer
from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker
from app.mensageria.consumidor import consumir_fila_execucao
from app.mensageria.retry import HEADER_RETRY
from app.repositorio.codigos_gerados import CodigoGerado, CodigoNaoEncontradoError
from tests.app.execucao.envelopes import saida as _saida
from tests.app.mensageria.sandbox_falso import SandboxFalso, saida_para


class MensagemFalsa(Message):
    def __init__(self, body: bytes, headers: dict[str, Any] | None = None) -> None:
        super().__init__(body=body, headers=headers)
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


def _codigo(**mudancas: Any) -> CodigoGerado:
    campos: dict[str, Any] = {
        "id": uuid4(),
        "job_id": uuid4(),
        "linguagem": "python",
        "fonte": "def aplicar_regra(bases, apuracao_base, competencias):\n    return {}\n",
    }
    return CodigoGerado(**(campos | mudancas))


def _preparar(
    monkeypatch: pytest.MonkeyPatch,
    mensagens: list[MensagemFalsa],
    codigo: CodigoGerado,
) -> tuple[ConexaoBroker, MagicMock]:
    monkeypatch.setattr(consumidor, "buscar_codigo", AsyncMock(return_value=codigo))
    monkeypatch.setattr(consumidor, "get_sessionmaker", lambda: _SessionmakerFalso())
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock(return_value=Basic.Ack())
    broker = ConexaoBroker(
        conexao=AsyncMock(),
        canal=canal,
        fila=FilaFalsa(mensagens),  # type: ignore[arg-type]
    )
    return broker, canal


async def test_comando_valido_executa_o_codigo_lido_do_banco_no_sandbox(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso
) -> None:
    job_id, codigo = uuid4(), _codigo()
    mensagem = MensagemFalsa(
        body=_corpo_comando(
            job_id=str(job_id),
            codigo_gerado_id=str(codigo.id),
            competencias=["2025-08", "2025-11"],
        )
    )
    broker, canal = _preparar(monkeypatch, [mensagem], codigo)

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == [
        PayloadContainer(
            job_id=job_id,
            codigo_gerado_id=codigo.id,
            linguagem="python",
            fonte=codigo.fonte,
            competencias=["2025-08", "2025-11"],
        )
    ]
    assert mensagem.aceita is True
    canal.default_exchange.publish.assert_not_awaited()


async def test_o_sandbox_roda_fora_da_thread_do_loop(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso
) -> None:
    """Numa chamada direta o loop ficaria até 60 s sem atender o heartbeat do RabbitMQ, e o
    broker derrubaria a conexão no meio da execução."""
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    assert len(sandbox.threads) == 1
    assert sandbox.threads[0] != threading.get_ident()


async def test_falha_de_infra_no_sandbox_republica_o_comando_na_mesma_fila(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso
) -> None:
    sandbox.erro = SandboxInfraError("daemon indisponível")
    mensagem = MensagemFalsa(body=_corpo_comando())
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    canal.default_exchange.publish.assert_awaited_once()
    copia = canal.default_exchange.publish.call_args.args[0]
    assert canal.default_exchange.publish.call_args.kwargs["routing_key"] == "executar-codigo"
    assert copia.headers[HEADER_RETRY] == 1
    assert copia.body == mensagem.body
    assert mensagem.aceita is True


async def test_falha_de_infra_no_sandbox_com_tentativas_esgotadas_vai_a_dlq(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso
) -> None:
    sandbox.erro = SandboxInfraError("daemon indisponível")
    mensagem = MensagemFalsa(body=_corpo_comando(), headers={HEADER_RETRY: 2})
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    canal.default_exchange.publish.assert_awaited_once()
    assert canal.default_exchange.publish.call_args.kwargs["routing_key"] == "executar-codigo.dlq"
    assert mensagem.aceita is True


async def test_erro_inesperado_no_sandbox_e_terminal(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso
) -> None:
    """Bug de programação não é presumido transitório (DEC-091): vai à DLQ para diagnóstico,
    em vez de ser repetido três vezes."""
    sandbox.erro = RuntimeError("bug")
    mensagem = MensagemFalsa(body=_corpo_comando())
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    assert canal.default_exchange.publish.call_args.kwargs["routing_key"] == "executar-codigo.dlq"
    assert mensagem.aceita is True


@pytest.mark.parametrize(
    "resposta",
    [
        lambda p: saida_para(p, "assercao_violada"),
        lambda p: saida_para(p, "erro_codigo"),
        lambda _p: _saida(b"", 137, estourou_timeout=True),
        lambda _p: _saida(b"", 137, oom_killed=True),
    ],
    ids=["assercao", "erro_codigo", "timeout", "oom"],
)
async def test_desfecho_do_codigo_gerado_nao_e_repetido(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    resposta: Callable[[PayloadContainer], SaidaBruta],
) -> None:
    """Erro do código gerado não é erro de infraestrutura: repetir o comando reexecutaria o
    mesmo código com o mesmo resultado. Quem trata é a regeneração, no codegen."""
    sandbox.resposta = resposta
    mensagem = MensagemFalsa(body=_corpo_comando())
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    assert len(sandbox.payloads) == 1
    canal.default_exchange.publish.assert_not_awaited()
    assert mensagem.aceita is True


def _desfecho_registrado(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    registros = [r for r in caplog.records if r.getMessage() == "execução classificada"]
    assert len(registros) == 1, [r.getMessage() for r in caplog.records]
    return registros[0]


@pytest.mark.parametrize(
    "resposta,classe,motivo",
    [
        (saida_para, "sucesso", "ok"),
        (lambda p: saida_para(p, "assercao_violada"), "assercao_violada", "assercao"),
        (lambda p: saida_para(p, "erro_codigo"), "erro_codigo", "excecao"),
        (
            lambda _p: _saida(b"", 137, estourou_timeout=True),
            "erro_codigo",
            "timeout",
        ),
        (lambda _p: _saida(b"", 1), "erro_codigo", "sem_envelope"),
    ],
    ids=["sucesso", "assercao_violada", "excecao", "timeout", "sem_envelope"],
)
async def test_o_desfecho_classificado_vai_ao_log(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    caplog: pytest.LogCaptureFixture,
    resposta: Callable[[PayloadContainer], SaidaBruta],
    classe: str,
    motivo: str,
) -> None:
    """O comando do teste tem orçamento 100000.0: o resultado de sucesso só valida se o
    consumidor entregou esse orçamento ao classificador, porque o container não o tem."""
    sandbox.resposta = resposta
    mensagem = MensagemFalsa(body=_corpo_comando())
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())
    caplog.set_level(logging.INFO)

    await consumir_fila_execucao(broker)

    registro = _desfecho_registrado(caplog)
    assert (registro.classe, registro.motivo) == (classe, motivo)  # type: ignore[attr-defined]
    assert mensagem.aceita is True
    canal.default_exchange.publish.assert_not_awaited()


async def test_falha_de_infra_e_classificada_como_erro_infra_e_repetida(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sandbox.erro = SandboxInfraError("daemon indisponível")
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    caplog.set_level(logging.INFO)

    await consumir_fila_execucao(broker)

    registro = _desfecho_registrado(caplog)
    assert (registro.classe, registro.motivo) == ("erro_infra", "infra")  # type: ignore[attr-defined]
    assert registro.levelno == logging.WARNING
    assert canal.default_exchange.publish.call_args.kwargs["routing_key"] == "executar-codigo"


async def test_o_log_nao_carrega_conteudo_do_container(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stdout, stderr e a mensagem de erro da regra são texto não confiável e não vão a log."""
    sandbox.resposta = lambda p: saida_para(
        p,
        "erro_codigo",
        stderr=b"STDERR-DA-REGRA",
        erro={"tipo": "ValueError", "mensagem": "MENSAGEM-DA-REGRA", "traceback": "TRACE-DA-REGRA"},
    )
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    caplog.set_level(logging.DEBUG)

    await consumir_fila_execucao(broker)

    for conteudo in ("STDERR-DA-REGRA", "MENSAGEM-DA-REGRA", "TRACE-DA-REGRA"):
        assert conteudo not in caplog.text


async def test_comando_invalido_nao_chega_ao_sandbox(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso
) -> None:
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=b"{}")], _codigo())

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == []


async def test_codigo_nao_encontrado_nao_chega_ao_sandbox(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso
) -> None:
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    monkeypatch.setattr(
        consumidor, "buscar_codigo", AsyncMock(side_effect=CodigoNaoEncontradoError(uuid4()))
    )

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == []


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
