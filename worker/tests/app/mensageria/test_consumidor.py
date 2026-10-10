import asyncio
import json
import logging
import re
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from queue import Queue
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from aio_pika import Message
from aio_pika.exceptions import DeliveryError
from httpx import AsyncClient
from pamqp.commands import Basic
from prometheus_client import REGISTRY
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.logger import ContextQueueHandler, JsonFormatter
from app.execucao.bases import carregar_bases
from app.execucao.coleta import DesfechoClassificado
from app.execucao.container import SaidaBruta, SandboxCanceladoError, SandboxInfraError
from app.execucao.preparo import PayloadContainer
from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker
from app.mensageria.consumidor import consumir_fila_execucao
from app.mensageria.retry import HEADER_RETRY
from app.repositorio.codigos_gerados import CodigoGerado, CodigoNaoEncontradoError
from app.repositorio.resultados import ResultadoGravado
from tests.app.esquemas import erros_do_dominio, erros_do_evento, erros_do_log
from tests.app.execucao.envelopes import FALHA, resultado_para
from tests.app.execucao.envelopes import saida as _saida
from tests.app.mensageria.resultado_falso import DIARIO, BancoDeResultadosFalso, ExchangeFalsa
from tests.app.mensageria.sandbox_falso import SandboxFalso, saida_para


class MensagemFalsa(Message):
    def __init__(self, body: bytes, headers: dict[str, Any] | None = None) -> None:
        super().__init__(body=body, headers=headers)
        self.aceita = False
        self.requeued = False

    async def ack(self) -> None:
        DIARIO.append("ack")
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


def _do_job_do_comando(mensagens: list[MensagemFalsa], codigo: CodigoGerado) -> CodigoGerado:
    """O código lido do banco é do job do comando (o consumidor recusa o par incoerente). Um
    corpo que não é comando não tem job, e o código fica como está."""
    try:
        job_id = UUID(json.loads(mensagens[0].body)["job_id"])
    except (KeyError, ValueError, IndexError):
        return codigo
    return codigo.model_copy(update={"job_id": job_id})


def _preparar(
    monkeypatch: pytest.MonkeyPatch,
    mensagens: list[MensagemFalsa],
    codigo: CodigoGerado,
    *,
    do_job_do_comando: bool = True,
) -> tuple[ConexaoBroker, MagicMock]:
    if do_job_do_comando:
        codigo = _do_job_do_comando(mensagens, codigo)
    monkeypatch.setattr(consumidor, "buscar_codigo", AsyncMock(return_value=codigo))
    monkeypatch.setattr(consumidor, "get_sessionmaker", lambda: _SessionmakerFalso())
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock(return_value=Basic.Ack())
    broker = ConexaoBroker(
        conexao=AsyncMock(),
        canal=canal,
        fila=FilaFalsa(mensagens),  # type: ignore[arg-type]
        exchange=ExchangeFalsa(),  # type: ignore[arg-type]
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


def _julgamento_registrado(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    registros = [r for r in caplog.records if r.getMessage() == "execução julgada"]
    assert len(registros) == 1, [r.getMessage() for r in caplog.records]
    return registros[0]


@pytest.mark.parametrize(
    "resposta,classe,motivo,veredito",
    [
        (saida_para, "sucesso", "ok", "inviavel"),
        (
            lambda p: saida_para(p, "assercao_violada"),
            "assercao_violada",
            "assercao",
            "indeterminado",
        ),
        (lambda p: saida_para(p, "erro_codigo"), "erro_codigo", "excecao", "indeterminado"),
        (
            lambda _p: _saida(b"", 137, estourou_timeout=True),
            "erro_codigo",
            "timeout",
            "indeterminado",
        ),
        (lambda _p: _saida(b"", 1), "erro_codigo", "sem_envelope", "indeterminado"),
    ],
    ids=["sucesso", "assercao_violada", "excecao", "timeout", "sem_envelope"],
)
async def test_o_julgamento_vai_ao_log(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    caplog: pytest.LogCaptureFixture,
    resposta: Callable[[PayloadContainer], SaidaBruta],
    classe: str,
    motivo: str,
    veredito: str,
) -> None:
    """O comando do teste tem orçamento 100000.0 e o baseline de 2025-08 é 363021,46: o
    resultado de sucesso passa do orçamento, e só o consumidor tem esse número para julgar."""
    sandbox.resposta = resposta
    mensagem = MensagemFalsa(body=_corpo_comando())
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())
    caplog.set_level(logging.INFO)

    await consumir_fila_execucao(broker)

    registro = _julgamento_registrado(caplog)
    assert (registro.classe, registro.motivo, registro.veredito) == (  # type: ignore[attr-defined]
        classe,
        motivo,
        veredito,
    )
    assert mensagem.aceita is True
    canal.default_exchange.publish.assert_not_awaited()


@pytest.mark.parametrize(
    "orcamento,veredito",
    [(100000.0, "inviavel"), (364021.45, "inviavel"), (364021.46, "viavel"), (500000.0, "viavel")],
)
async def test_o_orcamento_do_comando_decide_o_veredito(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    orcamento: float,
    veredito: str,
) -> None:
    """O container falso devolve sempre o mesmo resultado (baseline 363021,46 mais 1.000,00), e
    só o orçamento do comando muda. O total exatamente igual ao orçamento é viável (DEC-093)."""
    mensagem = MensagemFalsa(body=_corpo_comando(orcamento=orcamento))
    broker, _ = _preparar(monkeypatch, [mensagem], _codigo())
    caplog.set_level(logging.INFO)

    await consumir_fila_execucao(broker)

    registro = _julgamento_registrado(caplog)
    assert (registro.classe, registro.veredito) == ("sucesso", veredito)  # type: ignore[attr-defined]


async def test_total_que_nao_e_o_baseline_do_worker_e_erro_do_codigo_no_log(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sandbox.resposta = lambda p: saida_para(p, resultado=_com_baseline_adulterado(p))
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    caplog.set_level(logging.INFO)

    await consumir_fila_execucao(broker)

    registro = _julgamento_registrado(caplog)
    assert (registro.classe, registro.motivo, registro.veredito) == (  # type: ignore[attr-defined]
        "erro_codigo",
        "baseline_divergente",
        "indeterminado",
    )


def _com_baseline_adulterado(payload: PayloadContainer) -> dict[str, object]:
    resultado = resultado_para(payload.competencias)
    resultado["totais"]["baseline"] += 0.01  # type: ignore[index]
    return resultado


async def test_falha_de_infra_e_classificada_como_erro_infra_e_repetida(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sandbox.erro = SandboxInfraError("daemon indisponível")
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    caplog.set_level(logging.INFO)

    await consumir_fila_execucao(broker)

    registro = _julgamento_registrado(caplog)
    assert (registro.classe, registro.motivo, registro.veredito) == (  # type: ignore[attr-defined]
        "erro_infra",
        "infra",
        "indeterminado",
    )
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


async def test_o_log_nao_carrega_os_numeros_do_resultado(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Os números são artefato e vivem no Postgres (T-067); o log leva o veredito, e só ele."""
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    caplog.set_level(logging.DEBUG)

    await consumir_fila_execucao(broker)

    assert _julgamento_registrado(caplog).veredito == "inviavel"  # type: ignore[attr-defined]
    for numero in ("363021.46", "364021.46", "1000.0", "100000"):
        assert numero not in caplog.text


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
    codigo = CodigoGerado(
        id=uuid4(),
        job_id=UUID(json.loads(valida.body)["job_id"]),
        linguagem="python",
        fonte="pass",
    )
    monkeypatch.setattr(consumidor, "buscar_codigo", AsyncMock(return_value=codigo))
    monkeypatch.setattr(consumidor, "get_sessionmaker", lambda: _SessionmakerFalso())

    fila = FilaFalsa([invalida, valida])
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock(return_value=Basic.Ack())
    broker = ConexaoBroker(conexao=AsyncMock(), canal=canal, fila=fila, exchange=ExchangeFalsa())  # type: ignore[arg-type]

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
    broker = ConexaoBroker(conexao=AsyncMock(), canal=canal, fila=fila, exchange=ExchangeFalsa())  # type: ignore[arg-type]

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
    broker = ConexaoBroker(
        conexao=AsyncMock(), canal=AsyncMock(), fila=fila, exchange=ExchangeFalsa()
    )  # type: ignore[arg-type]

    await consumir_fila_execucao(broker)

    assert ordem == ["entrou:1", "saiu:1", "entrou:2", "saiu:2"]


class _SessaoFalsa:
    def begin(self) -> "_SessaoFalsa":
        return self

    async def __aenter__(self) -> "_SessaoFalsa":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _SessionmakerFalso:
    def __call__(self) -> _SessaoFalsa:
        return _SessaoFalsa()


# ---- gravar e publicar (T-067) ----


def _publicados(broker: ConexaoBroker) -> list[dict[str, Any]]:
    return [json.loads(m.body) for m in broker.exchange.publicadas]  # type: ignore[attr-defined]


def _rota_da_republicacao(canal: MagicMock) -> str:
    return str(canal.default_exchange.publish.call_args.kwargs["routing_key"])


async def test_grava_antes_de_publicar_e_so_entao_da_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    """Um evento que referencia uma linha inexistente é pior que um evento perdido."""
    mensagem = MensagemFalsa(body=_corpo_comando())
    broker, _ = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    assert DIARIO == ["gravar", "publicar", "ack"]


async def test_a_linha_gravada_e_a_do_julgamento_do_comando(
    monkeypatch: pytest.MonkeyPatch, banco: BancoDeResultadosFalso
) -> None:
    job_id, codigo = uuid4(), _codigo()
    mensagem = MensagemFalsa(
        body=_corpo_comando(job_id=str(job_id), codigo_gerado_id=str(codigo.id), orcamento=100000.0)
    )
    broker, _ = _preparar(monkeypatch, [mensagem], codigo)

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert (linha["job_id"], linha["codigo_gerado_id"]) == (job_id, codigo.id)
    assert (linha["status"], linha["veredito"]) == ("sucesso", "inviavel")
    assert linha["totais"]["orcamento"] == 100000.0
    assert linha["totais"]["baseline"] == 363021.46
    assert linha["assercoes"] and linha["decomposicao"]


async def test_o_evento_publicado_referencia_a_linha_gravada(
    monkeypatch: pytest.MonkeyPatch, banco: BancoDeResultadosFalso
) -> None:
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    (evento,) = _publicados(broker)
    assert evento["resultado_id"] == str(banco.retornados[0].id)
    assert evento["status"] == "sucesso" and evento["veredito"] == "inviavel"
    assert erros_do_evento("simulacao-concluida", evento) == []
    assert broker.exchange.chamadas == [{"routing_key": "", "mandatory": True}]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("resposta", "status"),
    [
        (lambda p: saida_para(p, "assercao_violada"), "assercao_violada"),
        (lambda p: saida_para(p, "erro_codigo"), "erro_codigo"),
        (lambda _p: _saida(b"", 137, estourou_timeout=True), "erro_codigo"),
        (lambda p: saida_para(p, resultado=_com_baseline_adulterado(p)), "erro_codigo"),
    ],
    ids=["assercao_violada", "excecao", "timeout", "baseline_divergente"],
)
async def test_o_que_nao_e_sucesso_e_gravado_e_publicado_sem_veredito(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    resposta: Callable[[PayloadContainer], SaidaBruta],
    status: str,
) -> None:
    sandbox.resposta = resposta
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert linha["status"] == status
    assert (linha["veredito"], linha["totais"], linha["decomposicao"]) == (None, None, None)
    (evento,) = _publicados(broker)
    assert set(evento) == {"job_id", "resultado_id", "status"}
    assert evento["status"] == status


# ---- o diagnóstico de um erro_codigo vai na linha, e só nela ----


def _sem_a_quebra_por_loja(payload: PayloadContainer) -> dict[str, object]:
    resultado = resultado_para(payload.competencias)
    del resultado["decomposicao"]["loja"]  # type: ignore[attr-defined]
    return resultado


@pytest.mark.parametrize(
    ("resposta", "diagnostico"),
    [
        (lambda p: saida_para(p, "erro_codigo"), {"causa": "excecao", "falha": FALHA}),
        (lambda _p: _saida(b"", 137, estourou_timeout=True), {"causa": "timeout"}),
        (lambda _p: _saida(b"", 137, oom_killed=True), {"causa": "memoria"}),
        (lambda _p: _saida(b"", 1), {"causa": "sem_envelope"}),
        (
            lambda p: saida_para(p, resultado=_sem_a_quebra_por_loja(p)),
            {
                "causa": "resultado_fora_do_schema",
                "problemas": [{"caminho": "$.decomposicao", "palavra_chave": "required"}],
            },
        ),
        (
            lambda p: saida_para(p, resultado=_com_baseline_adulterado(p)),
            {"causa": "baseline_divergente"},
        ),
        (saida_para, None),
        (lambda p: saida_para(p, "assercao_violada"), None),
    ],
    ids=[
        "excecao",
        "timeout",
        "memoria",
        "sem_envelope",
        "resultado_fora_do_schema",
        "baseline_divergente",
        "sucesso",
        "assercao_violada",
    ],
)
async def test_o_diagnostico_e_gravado_com_o_resultado(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    resposta: Callable[[PayloadContainer], SaidaBruta],
    diagnostico: dict[str, object] | None,
) -> None:
    sandbox.resposta = resposta
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert linha["diagnostico"] == diagnostico
    if diagnostico is not None:
        assert erros_do_dominio("resultado-diagnostico", linha["diagnostico"]) == []
    (evento,) = _publicados(broker)
    assert not {"diagnostico", "falha", "problemas", "causa"} & set(evento)
    assert DIARIO == ["gravar", "publicar", "ack"]


async def test_a_falha_da_regra_vai_para_a_linha_e_nao_para_o_log(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    caplog: pytest.LogCaptureFixture,
) -> None:
    falha = {"tipo": "ValueError", "mensagem": "MENSAGEM-DA-REGRA", "traceback": "TRACE-DA-REGRA"}
    sandbox.resposta = lambda p: saida_para(p, "erro_codigo", erro=falha)
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    caplog.set_level(logging.DEBUG)

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert linha["diagnostico"] == {"causa": "excecao", "falha": falha}
    gravado = next(r for r in caplog.records if r.getMessage() == "resultado gravado")
    assert gravado.com_diagnostico is True  # type: ignore[attr-defined]
    for conteudo in ("MENSAGEM-DA-REGRA", "TRACE-DA-REGRA"):
        assert conteudo not in caplog.text
        assert conteudo not in _publicados(broker)[0].values()


async def test_o_log_diz_que_o_sucesso_foi_gravado_sem_diagnostico(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    caplog.set_level(logging.INFO)

    await consumir_fila_execucao(broker)

    gravado = next(r for r in caplog.records if r.getMessage() == "resultado gravado")
    assert gravado.com_diagnostico is False  # type: ignore[attr-defined]


async def test_diagnostico_fora_do_contrato_vai_a_dlq_sem_gravar_nem_publicar(
    monkeypatch: pytest.MonkeyPatch,
    banco: BancoDeResultadosFalso,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Uma exceção sem a falha que a sustenta é incoerência do worker: gravar sem diagnóstico
    perderia o que ele existe para guardar, e repetir daria o mesmo."""
    monkeypatch.setattr(
        consumidor, "classificar", lambda *_: DesfechoClassificado("erro_codigo", "excecao")
    )
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    caplog.set_level(logging.INFO)

    await consumir_fila_execucao(broker)

    assert banco.gravados == [] and _publicados(broker) == []
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"
    (registro,) = [
        r
        for r in caplog.records
        if r.getMessage() == "diagnóstico fora do contrato; encaminhando para DLQ"
    ]
    assert registro.levelno == logging.ERROR
    assert registro.problemas == ["$: required"]  # type: ignore[attr-defined]


async def test_falha_transitoria_ao_gravar_o_diagnostico_nao_publica_nada(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    """A linha e o diagnóstico entram juntos ou não entram: sem a transação confirmada, não há
    evento que os referencie."""
    sandbox.resposta = lambda p: saida_para(p, "erro_codigo")
    banco.erro_gravacao = OperationalError("INSERT", {}, Exception("conexão caiu"))
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    assert "publicar" not in DIARIO
    assert _publicados(broker) == []
    assert _rota_da_republicacao(canal) == "executar-codigo"


# ---- as falhas: cada uma vai para onde a DEC-091 manda ----


async def test_falha_transitoria_de_gravacao_repete_o_comando_sem_publicar(
    monkeypatch: pytest.MonkeyPatch, banco: BancoDeResultadosFalso
) -> None:
    banco.erro_gravacao = OperationalError("INSERT", {}, Exception("conexão caiu"))
    mensagem = MensagemFalsa(body=_corpo_comando())
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    assert "publicar" not in DIARIO
    assert _publicados(broker) == []
    assert _rota_da_republicacao(canal) == "executar-codigo"
    assert canal.default_exchange.publish.call_args.args[0].headers[HEADER_RETRY] == 1


async def test_gravacao_recusada_pelo_banco_nao_e_repetida_e_vai_a_dlq(
    monkeypatch: pytest.MonkeyPatch, banco: BancoDeResultadosFalso
) -> None:
    """Violação de integridade não some numa nova tentativa: quem trata é o diagnóstico."""
    banco.erro_gravacao = IntegrityError("INSERT", {}, Exception("fk_resultados_simulacao_job_id"))
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    assert _publicados(broker) == []
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"


@pytest.mark.parametrize(
    "falha",
    [DeliveryError(None, None), ConnectionError("caiu"), "nack"],
    ids=["sem rota", "conexao", "nack"],
)
async def test_falha_de_publicacao_repete_o_comando_com_a_linha_ja_gravada(
    monkeypatch: pytest.MonkeyPatch, banco: BancoDeResultadosFalso, falha: object
) -> None:
    """A linha existe e o evento não saiu: a próxima tentativa a encontra e só republica."""
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    if falha == "nack":
        broker.exchange.confirmacao = Basic.Nack()  # type: ignore[attr-defined]
    else:
        broker.exchange.erro = falha  # type: ignore[attr-defined]

    await consumir_fila_execucao(broker)

    assert len(banco.gravados) == 1
    assert DIARIO == ["gravar", "publicar", "ack"]
    assert _rota_da_republicacao(canal) == "executar-codigo"


# ---- a reentrega não executa de novo ----


@pytest.mark.parametrize("status", ["sucesso", "assercao_violada", "erro_codigo"])
async def test_resultado_ja_gravado_republica_o_evento_sem_executar_de_novo(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    status: str,
) -> None:
    job_id, codigo = uuid4(), _codigo()
    banco.existente = ResultadoGravado(
        id=uuid4(),
        job_id=job_id,
        status=status,
        veredito="viavel" if status == "sucesso" else None,
        totais={"baseline": 100.0, "simulado": 90.0, "diferenca_abs": -10.0, "diferenca_pct": -0.1}
        if status == "sucesso"
        else None,
    )
    mensagem = MensagemFalsa(
        body=_corpo_comando(job_id=str(job_id), codigo_gerado_id=str(codigo.id))
    )
    broker, canal = _preparar(monkeypatch, [mensagem], codigo)

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == []
    assert banco.gravados == []
    assert banco.consultas == [(job_id, codigo.id, None, "simulacao")]
    (evento,) = _publicados(broker)
    assert evento["resultado_id"] == str(banco.existente.id) and evento["status"] == status
    assert erros_do_evento("simulacao-concluida", evento) == []
    assert DIARIO == ["publicar", "ack"]
    canal.default_exchange.publish.assert_not_awaited()


async def test_resultado_ja_gravado_cuja_publicacao_falha_repete_o_comando(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    banco.existente = ResultadoGravado(
        id=uuid4(), job_id=uuid4(), status="erro_codigo", veredito=None, totais=None
    )
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    broker.exchange.erro = DeliveryError(None, None)  # type: ignore[attr-defined]

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == [] and banco.gravados == []
    assert _rota_da_republicacao(canal) == "executar-codigo"


async def test_falha_transitoria_na_consulta_repete_o_comando(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    banco.erro_consulta = OperationalError("SELECT", {}, Exception("conexão caiu"))
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == []
    assert _rota_da_republicacao(canal) == "executar-codigo"


async def test_codigo_de_outro_job_vai_a_dlq_sem_consultar_nem_executar(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    """O par (job, código) é incoerente: gravar uma linha que aponta os dois seria gravar uma
    mentira que a tabela INSERT-only não deixa corrigir."""
    broker, canal = _preparar(
        monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo(), do_job_do_comando=False
    )

    await consumir_fila_execucao(broker)

    assert banco.consultas == [] and banco.gravados == []
    assert sandbox.payloads == []
    assert _publicados(broker) == []
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"


# ---- esgotamento de erro_infra: grava e publica antes da DLQ (DEC-094) ----


async def test_erro_infra_esgotado_grava_publica_e_so_entao_vai_a_dlq(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    sandbox.erro = SandboxInfraError("daemon indisponível")
    mensagem = MensagemFalsa(body=_corpo_comando(), headers={HEADER_RETRY: 2})
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert linha["status"] == "erro_infra"
    assert (linha["veredito"], linha["totais"], linha["decomposicao"]) == (None, None, None)
    assert linha["assercoes"] == []
    (evento,) = _publicados(broker)
    assert set(evento) == {"job_id", "resultado_id", "status"} and evento["status"] == "erro_infra"
    assert erros_do_evento("simulacao-concluida", evento) == []
    assert DIARIO == ["gravar", "publicar", "ack"]
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"


@pytest.mark.parametrize("tentativa", [0, 1])
async def test_erro_infra_com_tentativas_sobrando_nao_grava_nem_publica(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    tentativa: int,
) -> None:
    """A linha de `erro_infra` só existe no esgotamento: gravá-la a cada tentativa daria ao job
    um desfecho de erro enquanto o comando ainda pode dar certo."""
    sandbox.erro = SandboxInfraError("daemon indisponível")
    mensagem = MensagemFalsa(body=_corpo_comando(), headers={HEADER_RETRY: tentativa})
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    assert banco.gravados == [] and _publicados(broker) == []
    assert _rota_da_republicacao(canal) == "executar-codigo"


async def test_metadata_de_retry_invalida_conta_como_esgotada(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    sandbox.erro = SandboxInfraError("daemon indisponível")
    mensagem = MensagemFalsa(body=_corpo_comando(), headers={HEADER_RETRY: "x"})
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    assert [g["status"] for g in banco.gravados] == ["erro_infra"]
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"


async def test_esgotamento_com_o_banco_fora_ainda_envia_a_dlq(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    """Perder o registro do erro não pode reter o comando: a DLQ é o que resta para diagnóstico."""
    sandbox.erro = SandboxInfraError("daemon indisponível")
    banco.erro_gravacao = OperationalError("INSERT", {}, Exception("conexão caiu"))
    mensagem = MensagemFalsa(body=_corpo_comando(), headers={HEADER_RETRY: 2})
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())

    await consumir_fila_execucao(broker)

    assert _publicados(broker) == []
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"
    assert mensagem.aceita is True


async def test_esgotamento_com_a_publicacao_falhando_ainda_envia_a_dlq(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    sandbox.erro = SandboxInfraError("daemon indisponível")
    mensagem = MensagemFalsa(body=_corpo_comando(), headers={HEADER_RETRY: 2})
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())
    broker.exchange.erro = DeliveryError(None, None)  # type: ignore[attr-defined]

    await consumir_fila_execucao(broker)

    assert len(banco.gravados) == 1
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"
    assert mensagem.aceita is True


# ---- o log ----


async def test_o_log_da_gravacao_e_da_publicacao_so_leva_referencias(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, banco: BancoDeResultadosFalso
) -> None:
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())
    caplog.set_level(logging.INFO)

    await consumir_fila_execucao(broker)

    mensagens = [r.getMessage() for r in caplog.records]
    assert "resultado gravado" in mensagens
    gravado = next(r for r in caplog.records if r.getMessage() == "resultado gravado")
    assert gravado.resultado_id == str(banco.retornados[0].id)  # type: ignore[attr-defined]


# ---- o encerramento do worker no meio de uma execução ----


async def test_cancelar_o_consumidor_no_meio_da_execucao_manda_matar_o_container(
    monkeypatch: pytest.MonkeyPatch, banco: BancoDeResultadosFalso
) -> None:
    """O cancelamento vai à thread, que mata e remove o container; e só depois de ela terminar o
    cancelamento segue. Senão o processo sairia antes da limpeza, e o container ficaria rodando
    sem quem lhe imponha o prazo. O comando não é confirmado, nem rejeitado: o broker o devolve."""
    iniciou, terminou = threading.Event(), threading.Event()
    recebido: list[threading.Event | None] = []

    def executar_que_espera(payload: PayloadContainer, *, cancelar: Any = None) -> SaidaBruta:
        recebido.append(cancelar)
        iniciou.set()
        assert cancelar is not None and cancelar.wait(timeout=10), "ninguém pediu o cancelamento"
        time.sleep(0.3)  # matar e remover o container leva tempo
        terminou.set()
        raise SandboxCanceladoError

    monkeypatch.setattr(consumidor, "executar_no_sandbox", executar_que_espera)
    mensagem = MensagemFalsa(body=_corpo_comando())
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())
    tarefa = asyncio.create_task(consumir_fila_execucao(broker))
    assert await asyncio.to_thread(iniciou.wait, 5)

    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa

    assert terminou.is_set(), "o cancelamento seguiu antes de a thread limpar o container"
    assert (mensagem.aceita, mensagem.requeued) == (False, False)
    assert banco.gravados == [] and _publicados(broker) == []
    canal.default_exchange.publish.assert_not_awaited()


async def test_sem_cancelamento_o_pedido_nunca_e_marcado(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso
) -> None:
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    (cancelar,) = sandbox.cancelamentos
    assert cancelar is not None and not cancelar.is_set()


async def test_falha_ao_matar_no_encerramento_nao_troca_o_cancelamento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O worker está saindo: se matar o container falhar, o cancelamento segue mesmo assim, e o
    comando não vai para o retry nem para a DLQ."""
    iniciou = threading.Event()

    def executar_que_falha_ao_cancelar(payload: PayloadContainer, *, cancelar: Any = None) -> Any:
        iniciou.set()
        cancelar.wait(timeout=10)
        raise SandboxInfraError("o container do sandbox não morreu depois do SIGKILL")

    monkeypatch.setattr(consumidor, "executar_no_sandbox", executar_que_falha_ao_cancelar)
    mensagem = MensagemFalsa(body=_corpo_comando())
    broker, canal = _preparar(monkeypatch, [mensagem], _codigo())
    tarefa = asyncio.create_task(consumir_fila_execucao(broker))
    assert await asyncio.to_thread(iniciou.wait, 5)

    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa

    canal.default_exchange.publish.assert_not_awaited()
    assert mensagem.aceita is False


# ---- a conferência de cobertura (T-241) ----

# O container falso declara nucleo.percentual e elem.1, os dois elementos com contribuição na
# decomposição dele (tests/app/execucao/envelopes.py). O comando exige também elem.2.
EXIGIDOS_A_MAIS = ["nucleo.percentual", "elem.1", "elem.2"]
METRICA_COBERTURA = "worker_cobertura_incompleta_total"


@pytest.fixture
def linhas_de_log() -> Iterator[Callable[[], list[dict[str, Any]]]]:
    """As linhas JSON que o processo escreveria: o handler e o formatter de produção, na ordem
    em que o QueueListener os aplica, sem thread nem arquivo. O handler copia o `job_id` do
    contexto no instante do log, como em produção."""
    fila: Queue[logging.LogRecord] = Queue(-1)
    handler = ContextQueueHandler(fila)
    formatter = JsonFormatter()
    raiz = logging.getLogger("app")
    raiz.addHandler(handler)

    def ler() -> list[dict[str, Any]]:
        linhas: list[dict[str, Any]] = []
        while not fila.empty():
            linhas.append(json.loads(formatter.format(fila.get_nowait())))
        return linhas

    try:
        yield ler
    finally:
        raiz.removeHandler(handler)


def _contagem_de_cobertura() -> float:
    valor = REGISTRY.get_sample_value(METRICA_COBERTURA)
    assert valor is not None, f"{METRICA_COBERTURA} não está no registry exposto"
    return valor


def _contagem_em_metrics(texto: str) -> float:
    achado = re.search(rf"^{METRICA_COBERTURA} (\S+)$", texto, flags=re.MULTILINE)
    assert achado is not None, f"{METRICA_COBERTURA} não aparece em /metrics"
    return float(achado.group(1))


async def test_elemento_exigido_nao_declarado_grava_erro_codigo_com_o_elemento_no_diagnostico(
    monkeypatch: pytest.MonkeyPatch, banco: BancoDeResultadosFalso
) -> None:
    corpo = _corpo_comando(elementos_exigidos=EXIGIDOS_A_MAIS)
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert (linha["status"], linha["veredito"]) == ("erro_codigo", None)
    assert (linha["totais"], linha["decomposicao"]) == (None, None)
    assert linha["diagnostico"] == {
        "causa": "cobertura_incompleta",
        "elementos_ausentes": ["elem.2"],
    }
    assert erros_do_dominio("resultado-diagnostico", linha["diagnostico"]) == []
    (evento,) = _publicados(broker)
    assert set(evento) == {"job_id", "resultado_id", "status"}
    assert evento["status"] == "erro_codigo"
    assert DIARIO == ["gravar", "publicar", "ack"]


async def test_contribuicao_de_elemento_nao_declarado_grava_erro_codigo(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    """A decomposição tem elem.1, e a declaração não: elem.1 é exigido e ficou ausente."""
    sandbox.resposta = lambda p: saida_para(p, elementos_implementados=["nucleo.percentual"])
    corpo = _corpo_comando(elementos_exigidos=["nucleo.percentual", "elem.1"])
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert linha["status"] == "erro_codigo"
    assert linha["diagnostico"] == {
        "causa": "cobertura_incompleta",
        "elementos_ausentes": ["elem.1"],
    }


async def test_a_falha_de_cobertura_vai_ao_log_com_o_job_e_as_referencias_sem_conteudo(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    linhas_de_log: Callable[[], list[dict[str, Any]]],
) -> None:
    """Exige elem.2, que o código não declara; e elem.1 tem contribuição sem ser exigido. O log
    leva as ausentes, que vêm do comando, e só a quantidade das fora da regra, que vêm do
    código gerado."""
    sandbox.resposta = lambda p: saida_para(p, elementos_implementados=["nucleo.percentual"])
    job_id = uuid4()
    corpo = _corpo_comando(job_id=str(job_id), elementos_exigidos=["nucleo.percentual", "elem.2"])
    fonte = "# FONTE-DA-REGRA\ndef aplicar_regra(bases, apuracao_base, competencias): ...\n"
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo(fonte=fonte))

    await consumir_fila_execucao(broker)

    linhas = linhas_de_log()
    (julgada,) = [linha for linha in linhas if linha["message"] == "execução julgada"]
    assert erros_do_log(julgada) == []
    assert julgada["job_id"] == str(job_id)
    assert julgada["level"] == "INFO"
    assert julgada["extra"] == {
        "classe": "erro_codigo",
        "motivo": "cobertura_incompleta",
        "veredito": "indeterminado",
        "desfecho": "erro_codigo",
        "com_meta_venda": False,
        "proposito": "simulacao",
        "codigo_saida": 0,
        "elementos_ausentes": ["elem.2"],
        "quantidade_fora_da_regra": 1,
    }
    (preparada,) = [linha for linha in linhas if linha["message"] == "execução preparada"]
    assert preparada["extra"]["elementos_exigidos"] == ["nucleo.percentual", "elem.2"]
    assert all(linha["job_id"] == str(job_id) for linha in linhas)
    texto = json.dumps(linhas)
    assert "FONTE-DA-REGRA" not in texto, "o código gerado chegou ao log"
    assert "elem.1" not in texto, "uma referência vinda do código gerado chegou ao log"
    for numero in ("8200.0", "3588.0", "364021.46"):
        assert numero not in texto


async def test_a_falha_de_cobertura_incrementa_o_contador_exposto_em_metrics(
    monkeypatch: pytest.MonkeyPatch, client: AsyncClient
) -> None:
    antes = _contagem_em_metrics((await client.get("/metrics")).text)
    corpo = _corpo_comando(elementos_exigidos=EXIGIDOS_A_MAIS)
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    resposta = await client.get("/metrics")
    assert resposta.status_code == 200
    assert _contagem_em_metrics(resposta.text) == antes + 1


@pytest.mark.parametrize(
    "exigidos",
    [["nucleo.percentual", "elem.1"], None],
    ids=["cobertura completa", "comando sem elementos_exigidos"],
)
async def test_execucao_que_nao_falha_a_cobertura_nao_conta(
    monkeypatch: pytest.MonkeyPatch, banco: BancoDeResultadosFalso, exigidos: list[str] | None
) -> None:
    antes = _contagem_de_cobertura()
    corpo = _corpo_comando(**({"elementos_exigidos": exigidos} if exigidos else {}))
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert (linha["status"], linha["diagnostico"]) == ("sucesso", None)
    assert _contagem_de_cobertura() == antes


async def test_cobertura_completa_grava_a_mesma_linha_que_o_comando_sem_conferencia(
    monkeypatch: pytest.MonkeyPatch, banco: BancoDeResultadosFalso
) -> None:
    conferido = MensagemFalsa(
        body=_corpo_comando(elementos_exigidos=["nucleo.percentual", "elem.1"])
    )
    sem_conferencia = MensagemFalsa(body=_corpo_comando())
    for mensagem in (conferido, sem_conferencia):
        broker, _ = _preparar(monkeypatch, [mensagem], _codigo())
        await consumir_fila_execucao(broker)

    colunas = ("status", "veredito", "totais", "assercoes", "decomposicao", "diagnostico")
    primeira, segunda = banco.gravados
    assert {c: primeira[c] for c in colunas} == {c: segunda[c] for c in colunas}
    # O que o container falso devolve para 2025-08: o baseline congelado mais 1.000,00.
    assert (primeira["status"], primeira["veredito"]) == ("sucesso", "inviavel")
    assert (primeira["totais"]["baseline"], primeira["totais"]["simulado"]) == (
        363021.46,
        364021.46,
    )


async def test_comando_sem_elementos_exigidos_executa_codigo_sem_declaracao_como_antes(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    """Compatibilidade: um comando publicado antes do campo e um código gerado antes da
    declaração. Nada é conferido, e o desfecho é o de hoje."""
    sandbox.resposta = lambda p: saida_para(p, elementos_implementados=None)
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert (linha["status"], linha["veredito"], linha["diagnostico"]) == (
        "sucesso",
        "inviavel",
        None,
    )


async def test_codigo_sem_declaracao_num_comando_que_exige_elementos_e_cobertura_incompleta(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    sandbox.resposta = lambda p: saida_para(p, elementos_implementados=None)
    corpo = _corpo_comando(elementos_exigidos=["nucleo.percentual", "elem.1"])
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert linha["diagnostico"] == {
        "causa": "cobertura_incompleta",
        "elementos_ausentes": ["nucleo.percentual", "elem.1"],
    }


async def test_execucao_repetida_porque_a_gravacao_falhou_conta_a_cobertura_de_novo(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    """O contador conta execuções julgadas, e não jobs: a gravação que falha devolve o comando à
    fila sem linha, e a entrega seguinte executa e julga de novo."""
    antes = _contagem_de_cobertura()
    banco.erro_gravacao = OperationalError("INSERT", {}, Exception("conexão caiu"))
    corpo = _corpo_comando(elementos_exigidos=EXIGIDOS_A_MAIS)
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())
    await consumir_fila_execucao(broker)
    assert _rota_da_republicacao(canal) == "executar-codigo"
    republicada = canal.default_exchange.publish.call_args.args[0]
    banco.erro_gravacao = None
    reentregue = MensagemFalsa(body=republicada.body, headers=republicada.headers)
    broker, _ = _preparar(monkeypatch, [reentregue], _codigo())

    await consumir_fila_execucao(broker)

    assert len(sandbox.payloads) == 2
    assert len(banco.gravados) == 1
    assert _contagem_de_cobertura() == antes + 2


async def test_reentrega_de_um_resultado_ja_gravado_nao_conta_a_cobertura_de_novo(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    banco.existente = ResultadoGravado(
        id=uuid4(), job_id=uuid4(), status="erro_codigo", veredito=None, totais=None
    )
    antes = _contagem_de_cobertura()
    corpo = _corpo_comando(elementos_exigidos=EXIGIDOS_A_MAIS)
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == [] and banco.gravados == []
    assert _contagem_de_cobertura() == antes


@pytest.mark.parametrize(
    "exigidos",
    [["elem.1", "elem.1"], [], ["nucleo.Percentual"], "elem.1"],
    ids=["repetido", "vazio", "fora do padrao", "nao e lista"],
)
async def test_elementos_exigidos_fora_do_contrato_vao_a_dlq_sem_executar(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, exigidos: object
) -> None:
    broker, canal = _preparar(
        monkeypatch, [MensagemFalsa(body=_corpo_comando(elementos_exigidos=exigidos))], _codigo()
    )

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == []
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"


@pytest.mark.parametrize("orcamento", [None, -1.0], ids=["nulo", "negativo"])
async def test_orcamento_presente_e_invalido_vai_a_dlq_sem_executar_nem_virar_job_sem_orcamento(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    orcamento: object,
) -> None:
    """Só a ausência do campo é o job sem orçamento (T-281). Um `null` explícito é um produtor
    errado: lido como ausência, pularia em silêncio a verificação de orçamento que o comando
    devia pedir."""
    broker, canal = _preparar(
        monkeypatch, [MensagemFalsa(body=_corpo_comando(orcamento=orcamento))], _codigo()
    )

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == [] and banco.gravados == []
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"


# ---- job sem orçamento: a execução normal, sem veredito (T-281) ----

METRICA_EXECUCOES = "worker_execucoes_julgadas_total"


def _corpo_sem_orcamento(**overrides: Any) -> bytes:
    dados = json.loads(_corpo_comando(**overrides))
    del dados["orcamento"]
    return json.dumps(dados).encode("utf-8")


def _execucoes_julgadas(desfecho: str) -> float:
    valor = REGISTRY.get_sample_value(METRICA_EXECUCOES, {"desfecho": desfecho})
    assert valor is not None, f"{METRICA_EXECUCOES}{{desfecho={desfecho}}} não está no registry"
    return valor


def _execucoes_em_metrics(texto: str, desfecho: str) -> float:
    achado = re.search(
        rf'^{METRICA_EXECUCOES}{{desfecho="{desfecho}"}} (\S+)$', texto, flags=re.MULTILINE
    )
    assert achado is not None, f"{METRICA_EXECUCOES} de {desfecho} não aparece em /metrics"
    return float(achado.group(1))


async def test_comando_sem_orcamento_grava_e_publica_o_sucesso_sem_veredito(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    job_id, codigo = uuid4(), _codigo()
    corpo = _corpo_sem_orcamento(job_id=str(job_id), codigo_gerado_id=str(codigo.id))
    mensagem = MensagemFalsa(body=corpo)
    broker, _ = _preparar(monkeypatch, [mensagem], codigo)

    await consumir_fila_execucao(broker)

    (payload,) = sandbox.payloads
    assert not hasattr(payload, "orcamento")
    (linha,) = banco.gravados
    assert (linha["status"], linha["veredito"], linha["diagnostico"]) == ("sucesso", None, None)
    assert "orcamento" not in linha["totais"]
    assert linha["totais"]["baseline"] == 363021.46
    assert erros_do_dominio("resultado-totais", linha["totais"]) == []
    assert linha["assercoes"] and linha["decomposicao"]
    (evento,) = _publicados(broker)
    assert evento["status"] == "sucesso" and "veredito" not in evento
    assert evento["resultado_id"] == str(banco.retornados[0].id)
    assert erros_do_evento("simulacao-concluida", evento) == []
    assert DIARIO == ["gravar", "publicar", "ack"]
    assert mensagem.aceita is True


async def test_comando_sem_orcamento_com_baseline_adulterado_continua_baseline_divergente(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    sandbox.resposta = lambda p: saida_para(p, resultado=_com_baseline_adulterado(p))
    antes = _execucoes_julgadas("erro_codigo")
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_sem_orcamento())], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert (linha["status"], linha["veredito"], linha["totais"]) == ("erro_codigo", None, None)
    assert linha["diagnostico"] == {"causa": "baseline_divergente"}
    (evento,) = _publicados(broker)
    assert set(evento) == {"job_id", "resultado_id", "status"}
    assert _execucoes_julgadas("erro_codigo") == antes + 1


async def test_comando_sem_orcamento_vai_ao_log_e_a_metrica_como_execucao_normal(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    linhas_de_log: Callable[[], list[dict[str, Any]]],
) -> None:
    """A execução sem orçamento é uma execução como as outras: julgada, gravada e publicada, com
    o desfecho `sem_orcamento` no log e na métrica exposta em /metrics. O log diz se havia
    orçamento, nunca os números."""
    texto_antes = (await client.get("/metrics")).text
    sem_orcamento_antes = _execucoes_em_metrics(texto_antes, "sem_orcamento")
    inviavel_antes = _execucoes_em_metrics(texto_antes, "inviavel")
    job_id = uuid4()
    mensagens = [
        MensagemFalsa(body=_corpo_sem_orcamento(job_id=str(job_id))),
    ]
    broker, _ = _preparar(monkeypatch, mensagens, _codigo())

    await consumir_fila_execucao(broker)

    resposta = await client.get("/metrics")
    assert resposta.status_code == 200
    assert _execucoes_em_metrics(resposta.text, "sem_orcamento") == sem_orcamento_antes + 1
    assert _execucoes_em_metrics(resposta.text, "inviavel") == inviavel_antes
    linhas = linhas_de_log()
    assert all(erros_do_log(linha) == [] for linha in linhas)
    assert all(linha["job_id"] == str(job_id) for linha in linhas)
    (preparada,) = [linha for linha in linhas if linha["message"] == "execução preparada"]
    assert preparada["extra"]["com_orcamento"] is False
    (julgada,) = [linha for linha in linhas if linha["message"] == "execução julgada"]
    assert julgada["level"] == "INFO"
    assert julgada["extra"] == {
        "classe": "sucesso",
        "motivo": "ok",
        "veredito": None,
        "desfecho": "sem_orcamento",
        "com_meta_venda": False,
        "proposito": "simulacao",
        "codigo_saida": 0,
    }
    mensagens_registradas = [linha["message"] for linha in linhas]
    assert "resultado gravado" in mensagens_registradas
    assert "simulacao-concluida publicada" in mensagens_registradas
    texto = json.dumps(linhas)
    for numero in ("364021.46", "363021.46"):
        assert numero not in texto


@pytest.mark.parametrize(("orcamento", "desfecho"), [(100000.0, "inviavel"), (500000.0, "viavel")])
async def test_comando_com_orcamento_conta_a_execucao_pelo_veredito(
    monkeypatch: pytest.MonkeyPatch, orcamento: float, desfecho: str
) -> None:
    antes = _execucoes_julgadas(desfecho)
    sem_orcamento_antes = _execucoes_julgadas("sem_orcamento")
    corpo = _corpo_comando(orcamento=orcamento)
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    assert _execucoes_julgadas(desfecho) == antes + 1
    assert _execucoes_julgadas("sem_orcamento") == sem_orcamento_antes


async def test_reentrega_de_resultado_sem_orcamento_republica_sem_veredito_e_nao_conta_execucao(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    job_id, codigo = uuid4(), _codigo()
    banco.existente = ResultadoGravado(
        id=uuid4(),
        job_id=job_id,
        status="sucesso",
        veredito=None,
        totais={"baseline": 100.0, "simulado": 90.0, "diferenca_abs": -10.0, "diferenca_pct": -0.1},
    )
    antes = _execucoes_julgadas("sem_orcamento")
    corpo = _corpo_sem_orcamento(job_id=str(job_id), codigo_gerado_id=str(codigo.id))
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], codigo)

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == [] and banco.gravados == []
    (evento,) = _publicados(broker)
    assert evento["status"] == "sucesso" and "veredito" not in evento
    assert erros_do_evento("simulacao-concluida", evento) == []
    assert _execucoes_julgadas("sem_orcamento") == antes


# ---- execução na meta de venda: a reapuração do worker e a conferência (T-270) ----

METRICA_NA_META = "worker_execucoes_na_meta_total"
METRICA_REAPURACAO = "worker_baseline_na_meta_seconds_count"
# A soma de vlr_venda de 2025-08 é 10.311.513,36; a meta fica acima dela.
VENDAS_2025_08 = 10311513.36
META = 11000000.0


def _corpo_na_meta(**overrides: Any) -> bytes:
    return _corpo_comando(**({"meta_venda": META} | overrides))


def _amostra(nome: str, **rotulos: str) -> float:
    valor = REGISTRY.get_sample_value(nome, rotulos)
    assert valor is not None, f"{nome}{rotulos} não está no registry"
    return valor


def _amostra_em_metrics(texto: str, nome: str, **rotulos: str) -> float:
    # O formato de texto do prometheus_client escreve os rótulos em ordem alfabética.
    seletor = ",".join(f'{chave}="{valor}"' for chave, valor in sorted(rotulos.items()))
    achado = re.search(rf"^{nome}{{{seletor}}} (\S+)$", texto, flags=re.MULTILINE)
    assert achado is not None, f"{nome}{{{seletor}}} não aparece em /metrics"
    return float(achado.group(1))


class BasesQueRegistram:
    """As bases reais do worker, com a reapuração registrada no diário: é o que prova a ordem
    entre a conferência e o container."""

    def __init__(self) -> None:
        self._bases = carregar_bases()

    def baseline_na_meta(self, competencias: list[str], meta_venda: float) -> Any:
        DIARIO.append("reapurar")
        return self._bases.baseline_na_meta(competencias, meta_venda)

    def vendas_historicas(self, competencias: list[str]) -> Any:
        return self._bases.vendas_historicas(competencias)


@pytest.fixture
def bases_que_registram(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso
) -> BasesQueRegistram:
    bases = BasesQueRegistram()
    monkeypatch.setattr(consumidor, "carregar_bases", lambda: bases)
    responder = sandbox.resposta

    def registrar_container(payload: PayloadContainer) -> SaidaBruta:
        DIARIO.append("container")
        return responder(payload)

    sandbox.resposta = registrar_container
    return bases


@pytest.mark.parametrize(
    ("proposito", "no_evento"),
    [(None, None), ("simulacao", None), ("busca_meta", "busca_meta")],
    ids=["sem proposito", "simulacao", "busca_meta"],
)
async def test_na_meta_o_worker_reapura_antes_do_container_e_grava_e_publica_a_meta(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    bases_que_registram: BasesQueRegistram,
    proposito: str | None,
    no_evento: str | None,
) -> None:
    job_id, codigo = uuid4(), _codigo()
    extra = {} if proposito is None else {"proposito": proposito}
    corpo = _corpo_na_meta(job_id=str(job_id), codigo_gerado_id=str(codigo.id), **extra)
    mensagem = MensagemFalsa(body=corpo)
    broker, _ = _preparar(monkeypatch, [mensagem], codigo)

    await consumir_fila_execucao(broker)

    assert DIARIO == ["reapurar", "container", "gravar", "publicar", "ack"]
    (payload,) = sandbox.payloads
    assert payload.meta_venda == META and not hasattr(payload, "proposito")
    (linha,) = banco.gravados
    assert (linha["status"], linha["meta_venda"]) == ("sucesso", META)
    assert linha["proposito"] == (proposito or "simulacao")
    reapurado = float(carregar_bases().baseline_na_meta(["2025-08"], META))
    assert linha["totais"]["baseline"] == reapurado != 363021.46
    assert linha["totais"]["vendas_historicas"] == VENDAS_2025_08
    assert erros_do_dominio("resultado-totais", linha["totais"]) == []
    (evento,) = _publicados(broker)
    assert evento["meta_venda"] == META and evento.get("proposito") == no_evento
    assert erros_do_evento("simulacao-concluida", evento) == []
    assert banco.consultas == [(job_id, codigo.id, META, proposito or "simulacao")]


async def test_na_meta_o_baseline_historico_vindo_do_container_e_divergente(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxFalso, banco: BancoDeResultadosFalso
) -> None:
    """Um container que não simulou na meta devolve o baseline congelado: o worker o confere
    contra o que ele mesmo reapurou, e o número não segue."""
    sandbox.resposta = lambda p: saida_para(p, resultado=resultado_para(p.competencias))
    antes = _amostra(METRICA_NA_META, proposito="busca_meta", desfecho="erro_codigo")
    corpo = _corpo_na_meta(proposito="busca_meta")
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    (linha,) = banco.gravados
    assert (linha["status"], linha["totais"]) == ("erro_codigo", None)
    assert linha["diagnostico"] == {"causa": "baseline_divergente"}
    assert (linha["meta_venda"], linha["proposito"]) == (META, "busca_meta")
    (evento,) = _publicados(broker)
    assert evento == {
        "job_id": evento["job_id"],
        "resultado_id": evento["resultado_id"],
        "status": "erro_codigo",
        "meta_venda": META,
        "proposito": "busca_meta",
    }
    assert _amostra(METRICA_NA_META, proposito="busca_meta", desfecho="erro_codigo") == antes + 1


async def test_na_meta_o_log_e_as_metricas_contam_a_execucao_e_a_reapuracao(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    linhas_de_log: Callable[[], list[dict[str, Any]]],
) -> None:
    """A execução na meta conta no desfecho de sempre e, por propósito, na métrica da meta; a
    reapuração do worker é medida. O log diz que havia meta, nunca a meta nem os totais."""
    texto_antes = (await client.get("/metrics")).text
    na_meta_antes = _amostra_em_metrics(
        texto_antes, METRICA_NA_META, proposito="busca_meta", desfecho="viavel"
    )
    reapuracoes_antes = _amostra_em_metrics(texto_antes, METRICA_REAPURACAO, resultado="ok")
    viavel_antes = _execucoes_em_metrics(texto_antes, "viavel")
    job_id = uuid4()
    corpo = _corpo_na_meta(job_id=str(job_id), proposito="busca_meta", orcamento=999999.0)
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    texto = (await client.get("/metrics")).text
    assert (
        _amostra_em_metrics(texto, METRICA_NA_META, proposito="busca_meta", desfecho="viavel")
        == na_meta_antes + 1
    )
    assert _amostra_em_metrics(texto, METRICA_REAPURACAO, resultado="ok") == reapuracoes_antes + 1
    assert _execucoes_em_metrics(texto, "viavel") == viavel_antes + 1
    linhas = linhas_de_log()
    assert all(erros_do_log(linha) == [] for linha in linhas)
    assert all(linha["job_id"] == str(job_id) for linha in linhas)
    (preparada,) = [linha for linha in linhas if linha["message"] == "execução preparada"]
    assert (preparada["extra"]["com_meta_venda"], preparada["extra"]["proposito"]) == (
        True,
        "busca_meta",
    )
    (reapurado,) = [linha for linha in linhas if linha["message"] == "baseline na meta reapurado"]
    assert reapurado["extra"]["duracao_s"] >= 0
    (julgada,) = [linha for linha in linhas if linha["message"] == "execução julgada"]
    assert (julgada["extra"]["desfecho"], julgada["extra"]["com_meta_venda"]) == ("viavel", True)
    assert julgada["extra"]["proposito"] == "busca_meta"
    (gravado,) = [linha for linha in linhas if linha["message"] == "resultado gravado"]
    assert (gravado["extra"]["com_meta_venda"], gravado["extra"]["proposito"]) == (
        True,
        "busca_meta",
    )
    serializado = json.dumps(linhas)
    reapurado_total = str(float(carregar_bases().baseline_na_meta(["2025-08"], META)))
    for numero in ("11000000", reapurado_total, str(VENDAS_2025_08)):
        assert numero not in serializado


async def test_meta_que_nao_se_aplica_vai_a_dlq_sem_subir_o_container(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    linhas_de_log: Callable[[], list[dict[str, Any]]],
) -> None:
    """A regra nem rodou: não há resultado a gravar em nome dela, e repetir daria o mesmo. A
    falha é medida e registrada só pela classe."""
    falhas_antes = _amostra(METRICA_REAPURACAO, resultado="falha")
    corpo = _corpo_na_meta(competencias=["2026-01"])
    broker, canal = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], _codigo())

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == [] and banco.gravados == []
    assert _publicados(broker) == []
    assert _rota_da_republicacao(canal) == "executar-codigo.dlq"
    assert _amostra(METRICA_REAPURACAO, resultado="falha") == falhas_antes + 1
    (erro,) = [
        linha
        for linha in linhas_de_log()
        if linha["message"] == "baseline na meta não reapurado; encaminhando para DLQ"
    ]
    assert erro["level"] == "ERROR" and erro["extra"] == {"erro": "CompetenciaSemBaselineError"}
    assert erros_do_log(erro) == []


async def test_sem_meta_o_worker_nao_reapura(
    monkeypatch: pytest.MonkeyPatch,
    banco: BancoDeResultadosFalso,
    bases_que_registram: BasesQueRegistram,
) -> None:
    reapuracoes_antes = _amostra(METRICA_REAPURACAO, resultado="ok")
    na_meta_antes = _amostra(METRICA_NA_META, proposito="simulacao", desfecho="inviavel")
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=_corpo_comando())], _codigo())

    await consumir_fila_execucao(broker)

    assert DIARIO == ["container", "gravar", "publicar", "ack"]
    (linha,) = banco.gravados
    assert (linha["meta_venda"], linha["proposito"]) == (None, "simulacao")
    assert linha["totais"]["baseline"] == 363021.46
    assert _amostra(METRICA_REAPURACAO, resultado="ok") == reapuracoes_antes
    assert _amostra(METRICA_NA_META, proposito="simulacao", desfecho="inviavel") == na_meta_antes


def _gravado_na_meta(job_id: UUID, meta_venda: float | None, proposito: str) -> ResultadoGravado:
    return ResultadoGravado(
        id=uuid4(),
        job_id=job_id,
        status="sucesso",
        veredito=None,
        totais={"baseline": 100.0, "simulado": 90.0, "diferenca_abs": -10.0, "diferenca_pct": -0.1},
        meta_venda=meta_venda,
        proposito=proposito,
    )


@pytest.mark.parametrize(
    ("ja_gravado", "pedido"),
    [
        ((META, "busca_meta"), (12000000.0, "busca_meta")),
        ((None, "simulacao"), (META, "simulacao")),
        ((META, "simulacao"), (META, "busca_meta")),
    ],
    ids=["outra meta", "historico e meta", "outro proposito"],
)
async def test_o_mesmo_codigo_em_outra_meta_ou_proposito_executa_de_novo(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    ja_gravado: tuple[float | None, str],
    pedido: tuple[float, str],
) -> None:
    """A busca da meta maior roda o mesmo código em várias metas (T-273): cada candidata é uma
    execução, e o resultado de uma não responde pela outra."""
    job_id, codigo = uuid4(), _codigo()
    banco.existente = _gravado_na_meta(job_id, *ja_gravado)
    meta, proposito = pedido
    corpo = _corpo_comando(
        job_id=str(job_id), codigo_gerado_id=str(codigo.id), meta_venda=meta, proposito=proposito
    )
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], codigo)

    await consumir_fila_execucao(broker)

    assert len(sandbox.payloads) == 1
    (linha,) = banco.gravados
    assert (linha["meta_venda"], linha["proposito"]) == pedido


async def test_a_mesma_meta_e_o_mesmo_proposito_republicam_sem_executar(
    monkeypatch: pytest.MonkeyPatch,
    sandbox: SandboxFalso,
    banco: BancoDeResultadosFalso,
    bases_que_registram: BasesQueRegistram,
) -> None:
    job_id, codigo = uuid4(), _codigo()
    banco.existente = _gravado_na_meta(job_id, META, "busca_meta")
    antes = _amostra(METRICA_NA_META, proposito="busca_meta", desfecho="sem_orcamento")
    corpo = _corpo_na_meta(
        job_id=str(job_id), codigo_gerado_id=str(codigo.id), proposito="busca_meta"
    )
    broker, _ = _preparar(monkeypatch, [MensagemFalsa(body=corpo)], codigo)

    await consumir_fila_execucao(broker)

    assert sandbox.payloads == [] and banco.gravados == []
    assert "reapurar" not in DIARIO
    (evento,) = _publicados(broker)
    assert (evento["meta_venda"], evento["proposito"]) == (META, "busca_meta")
    assert _amostra(METRICA_NA_META, proposito="busca_meta", desfecho="sem_orcamento") == antes
