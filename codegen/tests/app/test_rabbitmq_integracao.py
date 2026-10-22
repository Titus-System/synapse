import asyncio
import os
import subprocess
from collections.abc import AsyncGenerator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import simplejson
from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractIncomingMessage, AbstractQueue
from aiormq.exceptions import ChannelNotFoundEntity

from app.config import Settings
from app.contratos.mensagens import (
    JobEncerrado,
    ModeloContrato,
    RegraSubmetida,
    SimulacaoConcluida,
)
from app.contratos.serializacao import serializar
from app.graph.nodes.dispatch_execution import dispatch_execution
from app.mensageria.broker import (
    EXCHANGE_SIMULACAO,
    FILA_SIMULACAO,
    ConexaoBroker,
    conectar,
)
from app.mensageria.consumers import Consumer
from app.mensageria.roteamento import Entrada, GraphRouter
from app.representacao_regra import RepresentacaoRegra
from tests.app.confirmacao_falsa import ConfirmacaoFalsa
from tests.app.graph.test_reextracao import AmbienteReextracao
from tests.app.iteracao_falsa import NUCLEO, HistoricoFalso
from tests.app.test_mensageria import SAIDAS, exemplo, oficial, sugestao_do_exemplo

pytestmark = [
    pytest.mark.rabbitmq,
    pytest.mark.skipif(
        os.getenv("RUN_RABBITMQ_INTEGRATION") != "1",
        reason="Requer RabbitMQ real do deploy/docker-compose.yml; RUN_RABBITMQ_INTEGRATION=1",
    ),
]
COMPOSE = Path(__file__).resolve().parents[3] / "deploy" / "docker-compose.yml"


def rabbitmqctl(*argumentos: str) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "exec",
            "-T",
            "rabbitmq",
            "rabbitmqctl",
            *argumentos,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture
async def broker_real() -> AsyncGenerator[ConexaoBroker, None]:
    # Vhost próprio evita consumir ou apagar mensagens do ambiente de desenvolvimento.
    vhost = f"t049-{uuid4()}"
    config = Settings(RABBITMQ_VHOST=vhost)
    await asyncio.to_thread(rabbitmqctl, "add_vhost", vhost)
    try:
        await asyncio.to_thread(
            rabbitmqctl, "set_permissions", "-p", vhost, config.RABBITMQ_USER, ".*", ".*", ".*"
        )
        broker = await conectar(config)
        try:
            yield broker
        finally:
            await broker.fechar()
    finally:
        await asyncio.to_thread(rabbitmqctl, "delete_vhost", vhost)


class RoteadorTeste:
    def __init__(self) -> None:
        self.entregas: asyncio.Queue[tuple[UUID, Entrada]] = asyncio.Queue()

    async def entregar(self, job_id: UUID, mensagem: Entrada) -> None:
        await self.entregas.put((job_id, mensagem))


async def test_broker_real_entrega_ao_codegen_sem_api(broker_real: ConexaoBroker) -> None:
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    canal_verificacao = await broker_real.conexao.channel()
    try:
        with pytest.raises(ChannelNotFoundEntity):
            await canal_verificacao.declare_queue("simulacao-concluida.api", passive=True)
    finally:
        if not canal_verificacao.is_closed:
            await canal_verificacao.close()
    payload = exemplo("regra-submetida")
    corpo = simplejson.dumps(payload, use_decimal=True).encode()

    await broker_real.canal.default_exchange.publish(
        Message(body=corpo, content_type="application/json"), routing_key="regra-submetida"
    )
    job_id, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)

    assert isinstance(dto, RegraSubmetida)
    assert str(job_id) == payload["job_id"]
    assert simplejson.loads(serializar(dto), use_decimal=True) == payload


async def test_encerramento_da_api_chega_ao_codegen_pela_fila_propria(
    broker_real: ConexaoBroker,
) -> None:
    """A `api` publica `job-encerrado` na fila de mesmo nome (DEC-089), e só o codegen a lê."""
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    payload = exemplo("job-encerrado")
    corpo = simplejson.dumps(payload).encode()

    await broker_real.canal.default_exchange.publish(
        Message(body=corpo, content_type="application/json"), routing_key="job-encerrado"
    )
    job_id, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)

    assert isinstance(dto, JobEncerrado)
    assert str(job_id) == payload["job_id"]
    assert str(dto.evento_id) == payload["evento_id"]


async def test_resultado_do_worker_chega_ao_codegen_pelo_fanout(
    broker_real: ConexaoBroker,
) -> None:
    """O resultado publicado pelo worker é entregue ao roteador, que retoma o grafo."""
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    payload = exemplo("simulacao-concluida")
    corpo = simplejson.dumps(payload, use_decimal=True).encode()
    exchange = await broker_real.canal.get_exchange(EXCHANGE_SIMULACAO)
    assert broker_real.filas[FILA_SIMULACAO].name == "simulacao-concluida.codegen"

    await exchange.publish(Message(body=corpo, content_type="application/json"), routing_key="")

    job_id, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)
    assert isinstance(dto, SimulacaoConcluida)
    assert str(job_id) == payload["job_id"]
    assert simplejson.loads(serializar(dto), use_decimal=True) == payload


async def test_parametros_confirmados_drena_validas_duplicadas_e_invalidas(
    broker_real: ConexaoBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Broker e consumer reais; só banco, modelo e produtores do grafo são falsos."""
    ambiente = ConfirmacaoFalsa(monkeypatch)
    assentadas: asyncio.Queue[None] = asyncio.Queue()
    receber = Consumer.receber

    async def acompanhar(self: Consumer, mensagem: AbstractIncomingMessage) -> None:
        await receber(self, mensagem)
        assentadas.put_nowait(None)

    monkeypatch.setattr(Consumer, "receber", acompanhar)
    await broker_real.iniciar_consumers(ambiente.roteador)
    nome = "parametros-confirmados"
    valida = exemplo(nome) | {"meta_venda": Decimal("12000000")}
    antiga = {"job_id": valida["job_id"], "regra_id": str(uuid4())}
    invalida = valida | {"competencias": []}
    corpos = [
        simplejson.dumps(p, use_decimal=True).encode() for p in (valida, antiga, invalida, valida)
    ]
    corpos.append(b"{")
    for corpo in corpos:
        await broker_real.canal.default_exchange.publish(
            Message(body=corpo, content_type="application/json"), routing_key=nome
        )
    for _ in corpos:
        await asyncio.wait_for(assentadas.get(), timeout=10)

    # `broker_real.canal` já declarou essa fila antes do consumer existir; um `declare_queue`
    # passivo nele devolve o `AbstractQueue` cacheado, com o `declaration_result` daquele
    # instante. Um canal novo não tem esse cache e força a reconsulta ao broker.
    canal_verificacao = await broker_real.conexao.channel()
    try:
        fila = await canal_verificacao.declare_queue(nome, passive=True)
        assert fila.declaration_result.consumer_count == 1
        assert fila.declaration_result.message_count == 0
    finally:
        if not canal_verificacao.is_closed:
            await canal_verificacao.close()
    assert len(ambiente.modelo.seen_messages) == 1
    ambiente.producers.executar_codigo.assert_awaited_once()
    assert (await ambiente.estado(antiga)).values == {}
    assert all(p.get("status") != "erro" for _, p in ambiente.publicacoes)


async def test_fanout_mantem_copia_na_fila_api(broker_real: ConexaoBroker) -> None:
    """Uma publicação rende duas cópias: uma para o codegen e uma para a `api`.

    A do codegen é consumida e entregue ao roteador; a da `api` espera o consumer dela, que
    não existe neste teste. O que se confere é que uma cópia não come a outra.
    """
    exchange = await broker_real.canal.get_exchange(EXCHANGE_SIMULACAO)
    fila_api = await broker_real.canal.declare_queue("simulacao-concluida.api", durable=True)
    await fila_api.bind(exchange, routing_key="")
    roteador = RoteadorTeste()
    await broker_real.iniciar_consumers(roteador)
    corpo = simplejson.dumps(exemplo("simulacao-concluida")).encode()

    await exchange.publish(Message(body=corpo), routing_key="")

    _, dto = await asyncio.wait_for(roteador.entregas.get(), timeout=10)
    assert isinstance(dto, SimulacaoConcluida)
    copia_api = await fila_api.get(timeout=10)
    assert copia_api.body == corpo
    await copia_api.ack()


@pytest.mark.parametrize("modelo,nome,metodo", SAIDAS)
async def test_producer_real_entrega_payload_oficial_na_fila(
    broker_real: ConexaoBroker,
    modelo: type[ModeloContrato],
    nome: str,
    metodo: str,
) -> None:
    dto = modelo.model_validate_json(simplejson.dumps(exemplo(nome)))

    await getattr(broker_real.producers, metodo)(dto)
    recebido = await broker_real.filas[nome].get(timeout=10)

    payload = simplejson.loads(recebido.body, use_decimal=True)
    oficial(nome).validate(payload)
    assert payload == exemplo(nome)
    assert recebido.exchange == ""
    assert recebido.routing_key == nome
    await recebido.ack()


async def test_producer_real_entrega_a_sugestao_na_fila(broker_real: ConexaoBroker) -> None:
    """Fora da parametrização porque este DTO não tem volta por texto JSON (ver o unitário)."""
    nome = "sugestao-adaptacao-proposta"

    await broker_real.producers.sugestao_adaptacao_proposta(sugestao_do_exemplo())
    recebido = await broker_real.filas[nome].get(timeout=10)

    payload = simplejson.loads(recebido.body, use_decimal=True)
    oficial(nome).validate(payload)
    assert payload == exemplo(nome)
    assert recebido.routing_key == nome
    await recebido.ack()


@pytest.mark.parametrize(
    ("parametros", "esperados"),
    [
        (
            {"orcamento": "485000.10", "meta_venda": "26000000.123456789012345"},
            {
                "orcamento": Decimal("485000.10"),
                "meta_venda": Decimal("26000000.123456789012345"),
            },
        ),
        # O job sem orçamento nem meta: o worker simula sobre o histórico, sem veredito (T-281).
        ({}, {}),
    ],
    ids=["com-orcamento-e-meta", "sem-orcamento-e-meta"],
)
async def test_dispatch_execution_entrega_comando_persistente_e_valido(
    broker_real: ConexaoBroker, parametros: dict[str, str], esperados: dict[str, Decimal]
) -> None:
    job_id, codigo_gerado_id, regra_id = uuid4(), uuid4(), uuid4()
    estado = {
        "job_id": str(job_id),
        "regra_id": str(regra_id),
        "codigo_gerado_id": str(codigo_gerado_id),
        "competencias": ["2025-11"],
        "representacao_regra": {"nucleo": {"percentual": Decimal("0.025")}, "especificacoes": []},
        "codigo_fonte": "def aplicar_regra(bases, apuracao_base, competencias): ...",
        **parametros,
    }

    await dispatch_execution(estado, {"configurable": {"producers": broker_real.producers}})
    recebido = await broker_real.filas["executar-codigo"].get(timeout=10)

    payload = simplejson.loads(recebido.body, use_decimal=True)
    oficial("executar-codigo").validate(payload)
    assert payload == {
        "job_id": str(job_id),
        "codigo_gerado_id": str(codigo_gerado_id),
        "competencias": ["2025-11"],
        "proposito": "simulacao",
        "elementos_exigidos": ["nucleo.percentual"],
        **esperados,
    }
    assert recebido.delivery_mode == DeliveryMode.PERSISTENT
    await recebido.ack()

    # Os outros dois eventos do nó chegam nas filas deles, válidos no contrato: o progresso
    # que move o job e a linha de trilha desta etapa.
    etapa = await broker_real.filas["etapa-alterada"].get(timeout=10)
    oficial("etapa-alterada").validate(simplejson.loads(etapa.body, use_decimal=True))
    await etapa.ack()

    trilha = await broker_real.filas["no-concluido"].get(timeout=10)
    conclusao = simplejson.loads(trilha.body, use_decimal=True)
    oficial("no-concluido").validate(conclusao)
    assert conclusao["no"] == "delegacao_worker"
    assert conclusao["regra_id"] == str(regra_id)
    assert "codigo_gerado_id" not in conclusao
    await trilha.ack()


async def _proxima(fila: AbstractQueue, prazo: float = 30) -> AbstractIncomingMessage:
    """A próxima mensagem da fila. `get` não espera por ela, então a consulta se repete."""
    async with asyncio.timeout(prazo):
        while True:
            recebida = await fila.get(fail=False)
            if recebida is not None:
                return recebida
            await asyncio.sleep(0.05)


async def _ler(recebida: AbstractIncomingMessage, evento: str) -> dict[str, Any]:
    payload: dict[str, Any] = simplejson.loads(recebida.body, use_decimal=True)
    oficial(evento).validate(payload)
    await recebida.ack()
    return payload


async def test_iteracao_da_taxa_nova_propoe_tres_taxas_e_encerra_sem_alternativa(
    broker_real: ConexaoBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Consumers e producers reais no broker; o teste faz a api e o worker (T-271).

    A cada ciclo, a api publica `regra-submetida` com o orçamento do job, e o worker lê o
    comando e publica o resultado no fanout. Nenhuma das três taxas cabe em 1700, e depois da
    terceira o codegen anuncia o fim da iteração em vez de uma quarta proposta.
    """
    ambiente = ConfirmacaoFalsa(monkeypatch)
    historico = HistoricoFalso(uuid4(), Decimal("1700"), Decimal("1000"))
    historico.instalar(monkeypatch)
    roteador = GraphRouter(ambiente.banco, broker_real.producers, ambiente.limpeza)
    await broker_real.iniciar_consumers(roteador)
    fanout = await broker_real.canal.get_exchange(EXCHANGE_SIMULACAO)
    job_id = str(historico.job_id)
    regra_id = historico.gravar_versao({"nucleo": dict(NUCLEO), "especificacoes": []}, "extracao")
    propostas: list[dict[str, Any]] = []

    for comissao in ("2200", "1800", "1764", "1710"):
        submetida = exemplo("regra-submetida-parametros") | {
            "job_id": job_id,
            "regra_id": str(regra_id),
            "orcamento": Decimal("1700"),
        }
        await broker_real.canal.default_exchange.publish(
            Message(body=simplejson.dumps(submetida, use_decimal=True).encode()),
            routing_key="regra-submetida",
        )
        comando = await _ler(
            await _proxima(broker_real.filas["executar-codigo"]), "executar-codigo"
        )
        assert comando["orcamento"] == Decimal("1700")
        resultado_id = historico.gravar_resultado(regra_id, Decimal(comissao))
        resultado = exemplo("simulacao-concluida") | {
            "job_id": job_id,
            "resultado_id": str(resultado_id),
            "veredito": "inviavel",
        }
        await fanout.publish(
            Message(body=simplejson.dumps(resultado, use_decimal=True).encode()), routing_key=""
        )
        if len(propostas) < 3:
            proposta = await _ler(
                await _proxima(broker_real.filas["sugestao-adaptacao-proposta"]),
                "sugestao-adaptacao-proposta",
            )
            assert proposta["regra_origem_id"] == str(regra_id)
            propostas.append(proposta)
            regra_id = historico.gravar_proposta(proposta)

    etapas: list[dict[str, Any]] = []
    # Prazo do conjunto: um ciclo em laço de reentrega publica etapas sem nunca chegar ao fim.
    async with asyncio.timeout(60):
        while not etapas or etapas[-1]["status"] != "sem_alternativa":
            recebida = await _proxima(broker_real.filas["etapa-alterada"])
            etapas.append(await _ler(recebida, "etapa-alterada"))
    assert etapas[-1] == {
        "job_id": job_id,
        "etapa": "sugestao_adaptacao",
        "status": "sem_alternativa",
    }
    assert [p["tentativa"] for p in propostas] == [1, 2, 3]
    assert all(e["status"] != "erro" for e in etapas)
    assert await broker_real.filas["sugestao-adaptacao-proposta"].get(fail=False) is None
    for nome in ("regra-submetida", FILA_SIMULACAO):
        canal_verificacao = await broker_real.conexao.channel()
        try:
            fila = await canal_verificacao.declare_queue(nome, passive=True)
            assert fila.declaration_result.message_count == 0
        finally:
            if not canal_verificacao.is_closed:
                await canal_verificacao.close()


async def test_regra_barrada_publica_a_pausa_no_broker_sem_chegar_ao_modelo(
    broker_real: ConexaoBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Consumer, roteador e producers reais no broker; o teste faz a api (T-219).

    A regra não tem percentual, um conflito conhecido. O ciclo termina publicando a pausa, e
    nada segue para a geração de código.
    """
    ambiente = ConfirmacaoFalsa(monkeypatch)
    ambiente.buscar_regra.return_value = RepresentacaoRegra.model_validate(
        {"nucleo": {"loja": [], "marca": [], "cargo": []}, "especificacoes": []}
    )
    assentadas: asyncio.Queue[None] = asyncio.Queue()
    receber = Consumer.receber

    async def acompanhar(self: Consumer, mensagem: AbstractIncomingMessage) -> None:
        await receber(self, mensagem)
        assentadas.put_nowait(None)

    monkeypatch.setattr(Consumer, "receber", acompanhar)
    roteador = GraphRouter(ambiente.banco, broker_real.producers, ambiente.limpeza)
    await broker_real.iniciar_consumers(roteador)
    nome = "parametros-confirmados"
    payload = exemplo(nome) | {
        "job_id": str(uuid4()),
        "regra_id": str(uuid4()),
        "meta_venda": Decimal("12000000"),
    }

    await broker_real.canal.default_exchange.publish(
        Message(body=simplejson.dumps(payload, use_decimal=True).encode()), routing_key=nome
    )
    await asyncio.wait_for(assentadas.get(), timeout=30)

    etapas = [
        await _ler(await _proxima(broker_real.filas["etapa-alterada"]), "etapa-alterada")
        for _ in range(2)
    ]
    assert etapas == [
        {"job_id": payload["job_id"], "etapa": "validacao_dominio", "status": "iniciada"},
        {
            "job_id": payload["job_id"],
            "etapa": "confirmacao",
            "status": "aguardando_correcao",
            "regra_id": payload["regra_id"],
            "conflitos": [{"elementos": ["nucleo.percentual"], "motivo": "percentual ausente"}],
        },
    ]
    trilha = await _ler(await _proxima(broker_real.filas["no-concluido"]), "no-concluido")
    assert trilha["no"] == "validacao_dominio"
    for fila_de_saida in ("etapa-alterada", "no-concluido", "executar-codigo"):
        assert await broker_real.filas[fila_de_saida].get(fail=False) is None
    assert ambiente.modelo.seen_messages == []
    canal_verificacao = await broker_real.conexao.channel()
    try:
        fila = await canal_verificacao.declare_queue(nome, passive=True)
        assert fila.declaration_result.message_count == 0
    finally:
        if not canal_verificacao.is_closed:
            await canal_verificacao.close()


async def test_correcao_submetida_drena_validas_duplicadas_e_invalidas_e_publica_a_proposta(
    broker_real: ConexaoBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Consumer, roteador e producers reais no broker; o teste faz a api (T-221).

    A fila de entrada fica vazia depois de uma correção válida, da reentrega dela, de uma sem
    texto, de uma fora do contrato e de um corpo malformado. Só a válida chega à proposta.
    """
    ambiente = AmbienteReextracao(monkeypatch)
    assentadas: asyncio.Queue[None] = asyncio.Queue()
    receber = Consumer.receber

    async def acompanhar(self: Consumer, mensagem: AbstractIncomingMessage) -> None:
        await receber(self, mensagem)
        assentadas.put_nowait(None)

    monkeypatch.setattr(Consumer, "receber", acompanhar)
    roteador = GraphRouter(ambiente.banco, broker_real.producers, ambiente.limpeza)
    await broker_real.iniciar_consumers(roteador)
    nome = "correcao-submetida"
    valida = ambiente.entrada()
    sem_texto = ambiente.entrada(None)
    invalida = valida | {"competencias": []}
    corpos = [
        simplejson.dumps(p, use_decimal=True).encode()
        for p in (valida, valida, sem_texto, invalida)
    ]
    corpos.append(b"{")
    for corpo in corpos:
        await broker_real.canal.default_exchange.publish(
            Message(body=corpo, content_type="application/json"), routing_key=nome
        )
    for _ in corpos:
        await asyncio.wait_for(assentadas.get(), timeout=30)

    proposta = await _ler(
        await _proxima(broker_real.filas["correcao-proposta"]), "correcao-proposta"
    )
    assert proposta["submissao_id"] == valida["submissao_id"]
    assert proposta["regra_origem_id"] == valida["regra_origem_id"]
    assert await broker_real.filas["correcao-proposta"].get(fail=False) is None
    etapas = []
    while (recebida := await broker_real.filas["etapa-alterada"].get(fail=False)) is not None:
        etapas.append(await _ler(recebida, "etapa-alterada"))
    assert [(e["job_id"], e["status"]) for e in etapas] == [
        (valida["job_id"], "iniciada"),
        (sem_texto["job_id"], "iniciada"),
        (sem_texto["job_id"], "erro"),
    ]
    assert etapas[-1]["regra_id"] == sem_texto["regra_origem_id"]
    assert etapas[-1]["submissao_id"] == sem_texto["submissao_id"]
    assert len(ambiente.modelo_reextracao.seen_messages) == 1
    canal_verificacao = await broker_real.conexao.channel()
    try:
        fila = await canal_verificacao.declare_queue(nome, passive=True)
        assert fila.declaration_result.consumer_count == 1
        assert fila.declaration_result.message_count == 0
    finally:
        if not canal_verificacao.is_closed:
            await canal_verificacao.close()
