import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
import simplejson
from aio_pika import DeliveryMode
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from referencing import Registry, Resource

from app.config import Settings
from app.core.logger import job_id_ctx
from app.mensageria import broker as modulo_broker
from app.mensageria.broker import FILA_SIMULACAO, FILAS_SIMPLES, conectar, declarar_topologia
from app.mensageria.consumers import Consumer
from app.mensageria.contratos import (
    Entrada,
    EtapaAlterada,
    ExecutarCodigo,
    Mensagem,
    NoConcluido,
    ParametrosConfirmados,
    RegraSubmetida,
    SimulacaoConcluida,
)
from app.mensageria.producers import Producers, ProdutorError
from app.mensageria.roteamento import JobDesconhecidoError

CONTRATOS = Path(__file__).resolve().parents[3] / "contracts"
MODELOS = (
    RegraSubmetida,
    ParametrosConfirmados,
    SimulacaoConcluida,
    ExecutarCodigo,
    EtapaAlterada,
    NoConcluido,
)
ENTRADAS = (RegraSubmetida, ParametrosConfirmados, SimulacaoConcluida)
SAIDAS = (
    (ExecutarCodigo, "executar_codigo"),
    (EtapaAlterada, "etapa_alterada"),
    (NoConcluido, "no_concluido"),
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


@pytest.mark.parametrize("modelo", MODELOS)
def test_seis_dtos_validam_exemplo_e_serializacao_no_schema_oficial(modelo: type[Mensagem]) -> None:
    payload = exemplo(modelo.nome)
    schema = oficial(modelo.nome)
    schema.validate(payload)

    dto = modelo.model_validate(payload)
    produzido = simplejson.loads(dto.serializar(), use_decimal=True)

    schema.validate(produzido)
    assert produzido == payload
    assert isinstance(dto.job_id, UUID)


@pytest.mark.parametrize("modelo", MODELOS)
def test_dto_recusa_uuid_invalido(modelo: type[Mensagem]) -> None:
    payload = exemplo(modelo.nome) | {"job_id": "invalido"}
    with pytest.raises(ValidationError):
        modelo.model_validate(payload)


@pytest.mark.parametrize("modelo", MODELOS)
def test_dto_ignora_campos_aditivos(modelo: type[Mensagem]) -> None:
    payload = exemplo(modelo.nome)
    dto = modelo.model_validate(payload | {"extensao_futura": {"ok": True}})
    assert simplejson.loads(dto.serializar(), use_decimal=True) == payload


@pytest.mark.parametrize(
    "modelo,campo",
    [
        (RegraSubmetida, "regra_id"),
        (SimulacaoConcluida, "total_simulado"),
        (NoConcluido, "explicacao_id"),
    ],
)
def test_opcional_ausente_nao_autoriza_null(modelo: type[Mensagem], campo: str) -> None:
    with pytest.raises(ValidationError):
        modelo.model_validate(exemplo(modelo.nome) | {campo: None})


@pytest.mark.parametrize(
    "alteracao",
    [
        {"competencias": []},
        {"competencias": ["2025-13"]},
        {"origem": "outra"},
        {"submissao_id": None},
        {"regra_id": None},
    ],
)
def test_regra_recusa_campos_incompativeis(alteracao: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RegraSubmetida.model_validate(exemplo("regra-submetida") | alteracao)


def test_regra_exige_referencias_conforme_origem() -> None:
    payload = exemplo("regra-submetida")
    del payload["regra_id"]
    with pytest.raises(ValidationError):
        RegraSubmetida.model_validate(payload)
    voz = RegraSubmetida.model_validate(exemplo("regra-submetida-voz"))
    assert "regra_id" not in simplejson.loads(voz.serializar())
    payload["origem"] = "reprocessamento"
    with pytest.raises(ValidationError):
        RegraSubmetida.model_validate(payload)


@pytest.mark.parametrize("valor", [1.2, True, "1.2", Decimal("NaN"), Decimal("Infinity"), -1])
def test_orcamento_recusa_numero_inadequado(valor: object) -> None:
    with pytest.raises(ValidationError):
        ExecutarCodigo.model_validate(exemplo("executar-codigo") | {"orcamento": valor})


def test_decimal_preserva_todos_os_digitos_no_corpo_json() -> None:
    valor = Decimal("12345678901234567890.1234567890123456789")
    dto = ExecutarCodigo.model_validate(exemplo("executar-codigo") | {"orcamento": valor})
    assert dto.orcamento == valor
    assert simplejson.loads(dto.serializar(), use_decimal=True)["orcamento"] == valor
    assert str(valor).encode() in dto.serializar()


@pytest.mark.parametrize(
    "alteracao",
    [
        {"concluido_em": "2025-11-28T14:32:10"},
        {"no": "inventado"},
        {"conclusao": {"resumo": ""}},
        {"conclusao": {"resumo": "ok", "elementos_implementados": ["invalido"]}},
        {"conclusao": {"resumo": "ok", "fontes": None}},
    ],
)
def test_conclusao_recusa_data_no_ou_conteudo_invalido(alteracao: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        NoConcluido.model_validate(exemplo("no-concluido") | alteracao)


@pytest.mark.parametrize("modelo,metodo", SAIDAS)
async def test_producer_publica_payload_validado_na_rota_correta(
    modelo: type[Mensagem],
    metodo: str,
) -> None:
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock()
    dto = modelo.model_validate(exemplo(modelo.nome))

    await getattr(Producers(canal), metodo)(dto)

    args = canal.default_exchange.publish.call_args
    assert args.kwargs == {"routing_key": modelo.nome, "mandatory": True}
    mensagem = args.args[0]
    oficial(modelo.nome).validate(simplejson.loads(mensagem.body, use_decimal=True))
    assert mensagem.delivery_mode == DeliveryMode.PERSISTENT
    assert mensagem.correlation_id == str(dto.job_id)
    assert mensagem.content_type == "application/json"


@pytest.mark.parametrize("modelo,metodo", SAIDAS)
async def test_producer_nao_publica_dto_adulterado(modelo: type[Mensagem], metodo: str) -> None:
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock()
    dto = modelo.model_validate(exemplo(modelo.nome))
    dto.job_id = "invalido"

    with pytest.raises(ProdutorError):
        await getattr(Producers(canal), metodo)(dto)

    canal.default_exchange.publish.assert_not_awaited()


@pytest.mark.parametrize("modelo", ENTRADAS)
async def test_consumer_entrega_dto_e_job_id_antes_do_ack(modelo: type[Entrada]) -> None:
    ordem = []
    roteador = MagicMock()

    async def entregar(job_id: UUID, dto: Entrada) -> None:
        assert isinstance(dto, modelo)
        assert job_id == UUID(exemplo(modelo.nome)["job_id"])
        assert job_id_ctx.get() == str(job_id)
        mensagem.ack.assert_not_awaited()
        ordem.append("persistido")

    roteador.entregar = AsyncMock(side_effect=entregar)
    mensagem = AsyncMock(body=simplejson.dumps(exemplo(modelo.nome)).encode())
    mensagem.ack.side_effect = lambda: ordem.append("ack")
    await Consumer(modelo, roteador).receber(mensagem)

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
    consumer = Consumer(ParametrosConfirmados, roteador)
    primeira = AsyncMock(body=simplejson.dumps(exemplo("parametros-confirmados")).encode())
    segunda = AsyncMock(body=primeira.body)

    await consumer.receber(primeira)
    await consumer.receber(segunda)

    primeira.reject.assert_awaited_once_with(requeue=False)
    primeira.ack.assert_not_awaited()
    segunda.ack.assert_awaited_once_with()
    assert log.warning.call_args.kwargs["extra"]["causa"] == "job_desconhecido"
    assert "segredo" not in str(log.mock_calls)


async def test_falha_de_processamento_reentrega_sem_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    log = MagicMock()
    monkeypatch.setattr("app.mensageria.consumers.logger", log)
    roteador = MagicMock(entregar=AsyncMock(side_effect=RuntimeError("segredo")))
    mensagem = AsyncMock(body=simplejson.dumps(exemplo("parametros-confirmados")).encode())

    await Consumer(ParametrosConfirmados, roteador).receber(mensagem)

    mensagem.nack.assert_awaited_once_with(requeue=True)
    mensagem.ack.assert_not_awaited()
    assert "segredo" not in str(log.mock_calls)


@pytest.mark.parametrize("corpo", [b"{", b"\xff", b"null", b"[]", b"{}", b'{"job_id": NaN}'])
async def test_mensagem_malformada_rejeitada_sem_processamento(corpo: bytes) -> None:
    roteador = MagicMock(entregar=AsyncMock())
    mensagem = AsyncMock(body=corpo)

    await Consumer(ParametrosConfirmados, roteador).receber(mensagem)

    mensagem.reject.assert_awaited_once_with(requeue=False)
    mensagem.ack.assert_not_awaited()
    roteador.entregar.assert_not_awaited()


async def test_cancelamento_nao_confirma_trabalho_incompleto() -> None:
    roteador = MagicMock(entregar=AsyncMock(side_effect=asyncio.CancelledError))
    mensagem = AsyncMock(body=simplejson.dumps(exemplo("parametros-confirmados")).encode())
    with pytest.raises(asyncio.CancelledError):
        await Consumer(ParametrosConfirmados, roteador).receber(mensagem)
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

    broker = MagicMock(iniciar_consumers=AsyncMock(), fechar=AsyncMock())
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
    broker.fechar.assert_awaited_once_with()


async def test_producer_revalida_restricao_schema_depois_de_mutacao() -> None:
    canal = MagicMock()
    canal.default_exchange.publish = AsyncMock()
    dto = ExecutarCodigo.model_validate(exemplo("executar-codigo"))
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
    assert len(broker.consumidores) == 3
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

    consumer = Consumer(ParametrosConfirmados, MagicMock(entregar=entregar))
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
    await Consumer(ParametrosConfirmados, MagicMock()).receber(mensagem)

    schema = simplejson.loads((CONTRATOS / "observability" / "log.schema.json").read_bytes())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(envelopes[0])
    assert envelopes[0]["job_id"] == payload["job_id"]
    assert envelopes[0]["service.name"] == "synapse-codegen"
    assert envelopes[0]["extra"]["decisao"] == "reject_sem_requeue"
    assert "segredo" not in str(envelopes)
