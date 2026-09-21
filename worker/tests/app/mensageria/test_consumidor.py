import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from aio_pika import Message
from aio_pika.exceptions import DeliveryError
from pamqp.commands import Basic
from sqlalchemy.exc import IntegrityError, OperationalError

from app.execucao.container import SaidaBruta, SandboxCanceladoError, SandboxInfraError
from app.execucao.preparo import PayloadContainer
from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker
from app.mensageria.consumidor import consumir_fila_execucao
from app.mensageria.retry import HEADER_RETRY
from app.repositorio.codigos_gerados import CodigoGerado, CodigoNaoEncontradoError
from app.repositorio.resultados import ResultadoGravado
from tests.app.esquemas import erros_do_evento
from tests.app.execucao.envelopes import resultado_para
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


@pytest.mark.parametrize("status", ["sucesso", "assercao_violada"])
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
    assert banco.consultas == [(job_id, codigo.id)]
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
