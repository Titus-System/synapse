import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
import simplejson
from aio_pika import DeliveryMode
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from app.codigo_gerado import CodigoInvalidoError
from app.config import Settings
from app.contratos.mensagens import (
    EtapaAlterada,
    ExecutarCodigo,
    ModeloContrato,
    NoConcluido,
    ParametrosConfirmados,
    RegraSubmetida,
    SimulacaoConcluida,
)
from app.contratos.serializacao import serializar
from app.core.logger import job_id_ctx
from app.falhas import FalhaDoJobError
from app.graph.nodes.code_generation import RespostaModeloInvalidaError
from app.graph.nodes.dispatch_execution import OrcamentoAusenteError
from app.mensageria import broker as modulo_broker
from app.mensageria.broker import FILA_SIMULACAO, FILAS_SIMPLES, conectar, declarar_topologia
from app.mensageria.consumers import Consumer
from app.mensageria.producers import Producers, ProdutorError
from app.mensageria.roteamento import Entrada, JobDesconhecidoError
from app.repositorio.regras import RegraInvalidaError

CONTRATOS = Path(__file__).resolve().parents[3] / "contracts"


async def test_consumer_entrega_dto_canonico_com_decimal_exato_e_campo_futuro() -> None:
    valor = Decimal("12345678901234567890.1234567890123456789")
    payload = exemplo("simulacao-concluida") | {
        "total_simulado": valor,
        "extensao_futura": {"ok": True},
    }
    roteador = MagicMock(entregar=AsyncMock())
    mensagem = AsyncMock(body=simplejson.dumps(payload, use_decimal=True).encode())

    await Consumer(SimulacaoConcluida, "simulacao-concluida", roteador).receber(mensagem)

    dto = roteador.entregar.call_args.args[1]
    assert isinstance(dto, SimulacaoConcluida)
    assert dto.total_simulado == valor
    assert "extensao_futura" not in dto.model_dump()
    mensagem.ack.assert_awaited_once_with()


ENTRADAS = (
    (RegraSubmetida, "regra-submetida"),
    (ParametrosConfirmados, "parametros-confirmados"),
    (SimulacaoConcluida, "simulacao-concluida"),
)
SAIDAS = (
    (ExecutarCodigo, "executar-codigo", "executar_codigo"),
    (EtapaAlterada, "etapa-alterada", "etapa_alterada"),
    (NoConcluido, "no-concluido", "no_concluido"),
)


def exemplo(nome: str) -> dict[str, Any]:
    return simplejson.loads(
        (CONTRATOS / "examples" / "events" / f"{nome}.json").read_bytes(), use_decimal=True
    )


def oficial(nome: str) -> Draft202012Validator:
    schemas = [
        simplejson.loads(p.read_bytes(), use_decimal=True) for p in CONTRATOS.rglob("*.schema.json")
    ]
    registro = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    schema = next(s for s in schemas if s["$id"].endswith(f"/events/{nome}.schema.json"))
    return Draft202012Validator(schema, registry=registro, format_checker=FormatChecker())


@pytest.mark.parametrize(
    "modelo,nome,alteracao",
    [
        (RegraSubmetida, "regra-submetida", {"competencias": []}),
        (RegraSubmetida, "regra-submetida", {"competencias": ["2025-13"]}),
        (RegraSubmetida, "regra-submetida", {"origem": "outra"}),
        (RegraSubmetida, "regra-submetida", {"submissao_id": None}),
        (RegraSubmetida, "regra-submetida", {"regra_id": None}),
        (ParametrosConfirmados, "parametros-confirmados", {"job_id": "invalido"}),
        (SimulacaoConcluida, "simulacao-concluida", {"total_simulado": None}),
        (SimulacaoConcluida, "simulacao-concluida", {"total_simulado": "1.2"}),
        (SimulacaoConcluida, "simulacao-concluida", {"total_simulado": True}),
    ],
)
async def test_consumer_recusa_schema_invalido_antes_de_entregar(
    modelo: type[Entrada], nome: str, alteracao: dict[str, Any]
) -> None:
    roteador = MagicMock(entregar=AsyncMock())
    mensagem = AsyncMock(body=simplejson.dumps(exemplo(nome) | alteracao).encode())

    await Consumer(modelo, nome, roteador).receber(mensagem)

    mensagem.reject.assert_awaited_once_with(requeue=False)
    mensagem.ack.assert_not_awaited()
    roteador.entregar.assert_not_awaited()


@pytest.mark.parametrize("origem", ["formulario", "reprocessamento"])
async def test_consumer_exige_referencias_conforme_origem(origem: str) -> None:
    payload = exemplo("regra-submetida") | {"origem": origem}
    del payload["regra_id"]
    roteador = MagicMock(entregar=AsyncMock())
    mensagem = AsyncMock(body=simplejson.dumps(payload).encode())

    await Consumer(RegraSubmetida, "regra-submetida", roteador).receber(mensagem)

    mensagem.reject.assert_awaited_once_with(requeue=False)
    roteador.entregar.assert_not_awaited()


async def test_consumer_aceita_voz_sem_regra_id() -> None:
    roteador = MagicMock(entregar=AsyncMock())
    payload = exemplo("regra-submetida-voz")
    mensagem = AsyncMock(body=simplejson.dumps(payload).encode())

    await Consumer(RegraSubmetida, "regra-submetida", roteador).receber(mensagem)

    dto = roteador.entregar.call_args.args[1]
    assert simplejson.loads(serializar(dto)) == payload
    mensagem.ack.assert_awaited_once_with()


async def test_producer_preserva_decimal_exato_no_corpo_json() -> None:
    valor = Decimal("12345678901234567890.1234567890123456789")
    dto = ExecutarCodigo.model_validate_json(simplejson.dumps(exemplo("executar-codigo")))
    dto.orcamento = valor
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock()

    await Producers(canal).executar_codigo(dto)

    corpo = canal.default_exchange.publish.call_args.args[0].body
    assert simplejson.loads(corpo, use_decimal=True)["orcamento"] == valor
    assert str(valor).encode() in corpo


@pytest.mark.parametrize(
    "alteracao",
    [
        {"concluido_em": "2025-11-28T14:32:10"},
        {"conclusao": {"resumo": "ok", "fontes": None}},
        {"explicacao_id": None},
    ],
)
async def test_producer_recusa_data_sem_fuso_e_null_explicito(
    alteracao: dict[str, Any],
) -> None:
    dto = NoConcluido.model_validate_json(simplejson.dumps(exemplo("no-concluido") | alteracao))
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock()

    with pytest.raises(ProdutorError):
        await Producers(canal).no_concluido(dto)

    canal.default_exchange.publish.assert_not_awaited()


@pytest.mark.parametrize("modelo,nome,metodo", SAIDAS)
async def test_producer_publica_payload_validado_na_rota_correta(
    modelo: type[ModeloContrato],
    nome: str,
    metodo: str,
) -> None:
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock()
    dto = modelo.model_validate_json(simplejson.dumps(exemplo(nome)))

    await getattr(Producers(canal), metodo)(dto)

    args = canal.default_exchange.publish.call_args
    assert args.kwargs == {"routing_key": nome, "mandatory": True}
    mensagem = args.args[0]
    oficial(nome).validate(simplejson.loads(mensagem.body, use_decimal=True))
    assert mensagem.delivery_mode == DeliveryMode.PERSISTENT
    assert mensagem.correlation_id == str(dto.job_id)
    assert mensagem.content_type == "application/json"
    assert mensagem.content_encoding == "utf-8"
    assert mensagem.type == nome
    assert mensagem.message_id == (str(dto.evento_id) if isinstance(dto, NoConcluido) else None)
    assert simplejson.loads(mensagem.body, use_decimal=True) == exemplo(nome)


@pytest.mark.parametrize("modelo,nome,metodo", SAIDAS)
async def test_producer_nao_publica_dto_adulterado(
    modelo: type[ModeloContrato], nome: str, metodo: str
) -> None:
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock()
    dto = modelo.model_validate_json(simplejson.dumps(exemplo(nome)))
    dto.job_id = "invalido"

    with pytest.raises(ProdutorError):
        await getattr(Producers(canal), metodo)(dto)

    canal.default_exchange.publish.assert_not_awaited()


@pytest.mark.parametrize("modelo,nome", ENTRADAS)
async def test_consumer_entrega_dto_e_job_id_antes_do_ack(modelo: type[Entrada], nome: str) -> None:
    ordem = []
    roteador = MagicMock()

    async def entregar(job_id: UUID, dto: Entrada) -> None:
        assert isinstance(dto, modelo)
        assert "extensao_futura" not in dto.model_dump()
        assert job_id == UUID(exemplo(nome)["job_id"])
        assert job_id_ctx.get() == str(job_id)
        mensagem.ack.assert_not_awaited()
        ordem.append("persistido")

    roteador.entregar = AsyncMock(side_effect=entregar)
    mensagem = AsyncMock(
        body=simplejson.dumps(exemplo(nome) | {"extensao_futura": {"ok": True}}).encode()
    )
    mensagem.ack.side_effect = lambda: ordem.append("ack")
    await Consumer(modelo, nome, roteador).receber(mensagem)

    assert ordem == ["persistido", "ack"]
    assert job_id_ctx.get() is None
    mensagem.nack.assert_not_awaited()
    mensagem.reject.assert_not_awaited()


async def test_job_desconhecido_rejeitado_e_consumer_continua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = MagicMock()
    monkeypatch.setattr("app.mensageria.consumers.logger", log)
    roteador = MagicMock(entregar=AsyncMock(side_effect=[JobDesconhecidoError("segredo"), None]))
    consumer = Consumer(ParametrosConfirmados, "parametros-confirmados", roteador)
    primeira = AsyncMock(body=simplejson.dumps(exemplo("parametros-confirmados")).encode())
    segunda = AsyncMock(body=primeira.body)

    await consumer.receber(primeira)
    await consumer.receber(segunda)

    primeira.reject.assert_awaited_once_with(requeue=False)
    primeira.ack.assert_not_awaited()
    segunda.ack.assert_awaited_once_with()
    assert log.warning.call_args.kwargs["extra"]["causa"] == "job_desconhecido"
    assert "segredo" not in str(log.mock_calls)


@pytest.mark.parametrize(
    ("falha", "etapa"),
    [
        (RegraInvalidaError, "geracao_codigo"),
        (RespostaModeloInvalidaError, "geracao_codigo"),
        (CodigoInvalidoError, "geracao_codigo"),
        (OrcamentoAusenteError, "delegacao_worker"),
    ],
)
async def test_falha_permanente_rejeitada_sem_requeue(
    monkeypatch: pytest.MonkeyPatch, falha: type[FalhaDoJobError], etapa: str
) -> None:
    """Toda falha permanente tem a mesma decisão, qualquer que seja o nó que a levantou.

    Reentregar não corrige nenhuma delas, e o grafo retomaria do checkpoint sobre o mesmo
    artefato inválido - com a chamada paga ao modelo repetida junto, no caso do provedor.
    """
    log = MagicMock()
    monkeypatch.setattr("app.mensageria.consumers.logger", log)
    roteador = MagicMock(entregar=AsyncMock(side_effect=falha("segredo")))
    mensagem = AsyncMock(body=simplejson.dumps(exemplo("regra-submetida")).encode())

    await Consumer(RegraSubmetida, "regra-submetida", roteador).receber(mensagem)

    mensagem.reject.assert_awaited_once_with(requeue=False)
    mensagem.nack.assert_not_awaited()
    mensagem.ack.assert_not_awaited()
    extra = log.warning.call_args.kwargs["extra"]
    assert extra["causa"] == "falha_do_job"
    assert extra["etapa"] == etapa
    assert "segredo" not in str(log.mock_calls)


async def test_falha_de_processamento_reentrega_sem_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    log = MagicMock()
    monkeypatch.setattr("app.mensageria.consumers.logger", log)
    roteador = MagicMock(entregar=AsyncMock(side_effect=RuntimeError("segredo")))
    mensagem = AsyncMock(body=simplejson.dumps(exemplo("parametros-confirmados")).encode())

    await Consumer(ParametrosConfirmados, "parametros-confirmados", roteador).receber(mensagem)

    mensagem.nack.assert_awaited_once_with(requeue=True)
    mensagem.ack.assert_not_awaited()
    assert "segredo" not in str(log.mock_calls)


@pytest.mark.parametrize("corpo", [b"{", b"\xff", b"null", b"[]", b"{}", b'{"job_id": NaN}'])
async def test_mensagem_malformada_rejeitada_sem_processamento(corpo: bytes) -> None:
    roteador = MagicMock(entregar=AsyncMock())
    mensagem = AsyncMock(body=corpo)

    await Consumer(ParametrosConfirmados, "parametros-confirmados", roteador).receber(mensagem)

    mensagem.reject.assert_awaited_once_with(requeue=False)
    mensagem.ack.assert_not_awaited()
    roteador.entregar.assert_not_awaited()


async def test_cancelamento_nao_confirma_trabalho_incompleto() -> None:
    roteador = MagicMock(entregar=AsyncMock(side_effect=asyncio.CancelledError))
    mensagem = AsyncMock(body=simplejson.dumps(exemplo("parametros-confirmados")).encode())
    with pytest.raises(asyncio.CancelledError):
        await Consumer(ParametrosConfirmados, "parametros-confirmados", roteador).receber(mensagem)
    mensagem.ack.assert_not_awaited()
    mensagem.reject.assert_not_awaited()


async def test_topologia_preserva_nomes_durabilidade_e_fanout_independente() -> None:
    canal = AsyncMock()
    filas = await declarar_topologia(canal)
    assert set(filas) == {*FILAS_SIMPLES, FILA_SIMULACAO}
    assert [c.args[0] for c in canal.declare_queue.call_args_list] == [
        *FILAS_SIMPLES,
        "simulacao-concluida.codegen",
    ]
    assert all(c.kwargs == {"durable": True} for c in canal.declare_queue.call_args_list)
    canal.declare_exchange.assert_awaited_once_with("simulacao-concluida", "fanout", durable=True)
    filas[FILA_SIMULACAO].bind.assert_awaited_once_with(
        canal.declare_exchange.return_value,
        routing_key="",
    )


async def test_conexao_fecha_se_declaracao_falhar(
    monkeypatch: pytest.MonkeyPatch,
    configuracoes: Settings,
) -> None:
    conexao = MagicMock(channel=AsyncMock(side_effect=RuntimeError), close=AsyncMock())
    monkeypatch.setattr(modulo_broker, "connect_robust", AsyncMock(return_value=conexao))
    with pytest.raises(RuntimeError):
        await conectar(configuracoes)
    conexao.close.assert_awaited_once_with()


@pytest.mark.parametrize("com_roteador", [True, False])
async def test_lifespan_inicia_recursos_e_fecha_sem_grafo_falso(
    monkeypatch: pytest.MonkeyPatch,
    com_roteador: bool,
) -> None:
    from app.main import criar_aplicacao

    engine = MagicMock(dispose=AsyncMock())
    checkpointer = AsyncMock()
    broker = MagicMock(iniciar_consumers=AsyncMock(), fechar=AsyncMock())
    monkeypatch.setattr("app.main.criar_engine", MagicMock(return_value=engine))
    monkeypatch.setattr("app.main.criar_sessionmaker", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr("app.main.get_checkpointer", _checkpointer_fixo(checkpointer))
    monkeypatch.setattr("app.main.conectar", AsyncMock(return_value=broker))
    monkeypatch.setattr("app.main.stop_logger", MagicMock())
    roteador = MagicMock() if com_roteador else None
    aplicacao = criar_aplicacao(roteador)

    async with aplicacao.router.lifespan_context(aplicacao):
        assert aplicacao.state.producers is broker.producers
        broker.fechar.assert_not_awaited()
        if com_roteador:
            broker.iniciar_consumers.assert_awaited_once_with(roteador)
        else:
            broker.iniciar_consumers.assert_not_awaited()
    checkpointer.setup.assert_awaited_once_with()
    broker.fechar.assert_awaited_once_with()
    engine.dispose.assert_awaited_once_with()


def _checkpointer_fixo(checkpointer: AsyncMock) -> Any:
    @asynccontextmanager
    async def get_checkpointer() -> AsyncIterator[AsyncMock]:
        yield checkpointer

    return get_checkpointer


async def test_lifespan_liga_sessoes_e_producers_num_graph_router_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import criar_aplicacao
    from app.mensageria.roteamento import GraphRouter

    engine = MagicMock(dispose=AsyncMock())
    sessoes = MagicMock()
    checkpointer = AsyncMock()
    broker = MagicMock(iniciar_consumers=AsyncMock(), fechar=AsyncMock())
    monkeypatch.setattr("app.main.criar_engine", MagicMock(return_value=engine))
    monkeypatch.setattr("app.main.criar_sessionmaker", MagicMock(return_value=sessoes))
    monkeypatch.setattr("app.main.get_checkpointer", _checkpointer_fixo(checkpointer))
    monkeypatch.setattr("app.main.conectar", AsyncMock(return_value=broker))
    monkeypatch.setattr("app.main.stop_logger", MagicMock())
    roteador = GraphRouter()
    aplicacao = criar_aplicacao(roteador)

    async with aplicacao.router.lifespan_context(aplicacao):
        assert roteador.sessoes is sessoes
        assert roteador.producers is broker.producers


async def test_producer_revalida_restricao_schema_depois_de_mutacao() -> None:
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock()
    dto = ExecutarCodigo.model_validate_json(simplejson.dumps(exemplo("executar-codigo")))
    dto.competencias.clear()

    with pytest.raises(ProdutorError):
        await Producers(canal).executar_codigo(dto)

    canal.default_exchange.publish.assert_not_awaited()


async def test_broker_usa_confirms_prefetch_e_consumers_com_ack_manual(
    monkeypatch: pytest.MonkeyPatch,
    configuracoes: Settings,
) -> None:
    canal = AsyncMock()
    canal.declare_queue.side_effect = lambda *args, **kwargs: AsyncMock()
    conexao = MagicMock(channel=AsyncMock(return_value=canal), close=AsyncMock())
    monkeypatch.setattr(modulo_broker, "connect_robust", AsyncMock(return_value=conexao))
    broker = await conectar(configuracoes)
    await broker.iniciar_consumers(MagicMock())

    conexao.channel.assert_awaited_once_with(publisher_confirms=True, on_return_raises=True)
    canal.set_qos.assert_awaited_once_with(prefetch_count=1)
    assert len(broker.consumidores) == 1
    for fila, _, _ in broker.consumidores:
        assert fila.consume.call_args.kwargs == {"no_ack": False}
    await broker.fechar()
    for fila, tag, _ in broker.consumidores:
        fila.cancel.assert_awaited_once_with(tag)
    conexao.close.assert_awaited_once_with()


async def test_encerramento_aguarda_processamento_antes_de_fechar_conexao() -> None:
    from app.mensageria.broker import ConexaoBroker

    inicio = asyncio.Event()
    liberar = asyncio.Event()

    async def entregar(job_id: UUID, mensagem: Entrada) -> None:
        inicio.set()
        await liberar.wait()

    consumer = Consumer(
        ParametrosConfirmados, "parametros-confirmados", MagicMock(entregar=entregar)
    )
    mensagem = AsyncMock(body=simplejson.dumps(exemplo("parametros-confirmados")).encode())
    tarefa = asyncio.create_task(consumer.receber(mensagem))
    await inicio.wait()
    conexao = MagicMock(close=AsyncMock())
    cancelado = asyncio.Event()
    fila = MagicMock(cancel=AsyncMock(side_effect=lambda _: cancelado.set()))
    broker = ConexaoBroker(conexao, MagicMock(), {}, MagicMock(), [(fila, "tag", consumer)])
    fechamento = asyncio.create_task(broker.fechar())
    await cancelado.wait()
    conexao.close.assert_not_awaited()
    mensagem.ack.assert_not_awaited()

    liberar.set()
    await tarefa
    await fechamento

    mensagem.ack.assert_awaited_once_with()
    conexao.close.assert_awaited_once_with()


async def test_log_de_rejeicao_preserva_envelope_e_job_sem_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import logging

    from app.core.logger import FormatadorJson, ManipuladorFilaContexto

    envelopes = []

    class Captura(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            preparado = ManipuladorFilaContexto(None).prepare(record)
            envelopes.append(simplejson.loads(FormatadorJson().format(preparado)))

    logger = logging.Logger("app.mensageria.consumers")
    logger.addHandler(Captura())
    monkeypatch.setattr("app.mensageria.consumers.logger", logger)
    payload = exemplo("parametros-confirmados") | {"regra_id": "segredo"}
    mensagem = AsyncMock(body=simplejson.dumps(payload).encode())
    await Consumer(ParametrosConfirmados, "parametros-confirmados", MagicMock()).receber(mensagem)

    schema = simplejson.loads((CONTRATOS / "observability" / "log.schema.json").read_bytes())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(envelopes[0])
    assert envelopes[0]["job_id"] == payload["job_id"]
    assert envelopes[0]["service.name"] == "synapse-codegen"
    assert envelopes[0]["extra"]["decisao"] == "reject_sem_requeue"
    assert "segredo" not in str(envelopes)
