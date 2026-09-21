"""O fluxo de execução inteiro com peças reais: comando no RabbitMQ, código no Postgres e
container Docker efêmero a partir da imagem do sandbox.

`test_consumidor.py` prova a fiação com um executor falso; aqui nada é falso. O que estes testes
alcançam e aqueles não: que o código que sai do banco é o que roda dentro do container, que o
resultado é o do motor de verdade, e que a falha de infraestrutura percorre o retry do broker
real até a DLQ.

Marcados `postgres` e `rabbitmq`, e não `docker`: o `verify.sh` roda `-m docker` sempre que há
daemon (é o caso da CI, que não tem Postgres nem RabbitMQ), e estes testes não poderiam subir.
Onde o compose está de pé o Docker também está, então a imagem do sandbox não é obstáculo.
"""

import asyncio
import contextlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import docker
import pytest
from aio_pika import Message
from aio_pika.abc import AbstractIncomingMessage

from app.config import get_settings
from app.execucao.container import ROTULO_JOB, SaidaBruta, executar_no_sandbox
from app.execucao.preparo import PayloadContainer
from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker
from app.mensageria.retry import HEADER_RETRY
from tests.app.sandbox.test_harness import EXEMPLO

pytestmark = [pytest.mark.postgres, pytest.mark.rabbitmq]

BASELINE_2025_11 = 508382.32
TENTATIVAS_TOTAIS = 3  # DEC-091: a inicial e duas republicações
PRAZO_S = 180.0


@pytest.fixture
def fonte_do_codigo_seed() -> str:
    """O banco guarda a regra de exemplo do contrato, que o motor sabe executar."""
    return EXEMPLO


def _comando(codigo_gerado_seed: dict[str, Any]) -> Message:
    corpo = {
        "job_id": str(codigo_gerado_seed["job_id"]),
        "codigo_gerado_id": str(codigo_gerado_seed["id"]),
        "competencias": ["2025-11"],
        "orcamento": 485000.0,
    }
    return Message(body=json.dumps(corpo).encode("utf-8"))


def _observar_processamento(monkeypatch: pytest.MonkeyPatch, total: int) -> asyncio.Event:
    """Sinaliza quando `total` mensagens terminaram o ciclo, ack ou republicação incluídos.

    Parar por tempo cancelaria o consumidor antes do ack e devolveria a mensagem à fila."""
    concluido = asyncio.Event()
    terminadas = 0
    processar = consumidor._processar

    async def processar_e_contar(mensagem: Any, broker: ConexaoBroker) -> None:
        nonlocal terminadas
        await processar(mensagem, broker)
        terminadas += 1
        if terminadas >= total:
            concluido.set()

    monkeypatch.setattr(consumidor, "_processar", processar_e_contar)
    return concluido


async def _consumir_ate(broker: ConexaoBroker, concluido: asyncio.Event) -> None:
    tarefa = asyncio.create_task(consumidor.consumir_fila_execucao(broker))
    try:
        await asyncio.wait_for(concluido.wait(), timeout=PRAZO_S)
    finally:
        tarefa.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarefa


async def _retirar(broker: ConexaoBroker, fila: str) -> AbstractIncomingMessage | None:
    """Lê de verdade o que está pronto na fila, num canal novo. Contar pela declaração passiva
    poderia devolver um valor guardado pelo canal robusto e passar por engano."""
    canal = await broker.conexao.channel()
    try:
        declarada = await canal.declare_queue(fila, passive=True)
        mensagem = await declarada.get(fail=False, timeout=5)
        if mensagem is not None:
            await mensagem.ack()
        return mensagem
    finally:
        await canal.close()


def _containers_do_job(job_id: UUID) -> list[str]:
    cliente = docker.DockerClient(base_url=get_settings().DOCKER_HOST)
    try:
        achados = cliente.containers.list(all=True, filters={"label": f"{ROTULO_JOB}={job_id}"})
        return [str(c.name) for c in achados]
    finally:
        cliente.close()


async def test_comando_no_rabbitmq_roda_o_codigo_do_banco_num_container_real(
    monkeypatch: pytest.MonkeyPatch,
    broker_real: ConexaoBroker,
    codigo_gerado_seed: dict[str, Any],
    imagem: str,
) -> None:
    execucoes: list[tuple[PayloadContainer, SaidaBruta]] = []

    def executar_na_imagem_de_teste(payload: PayloadContainer) -> SaidaBruta:
        saida = executar_no_sandbox(payload, imagem=imagem)
        execucoes.append((payload, saida))
        return saida

    monkeypatch.setattr(consumidor, "executar_no_sandbox", executar_na_imagem_de_teste)
    concluido = _observar_processamento(monkeypatch, total=1)
    await broker_real.canal.default_exchange.publish(
        _comando(codigo_gerado_seed), routing_key=broker_real.fila.name
    )

    await _consumir_ate(broker_real, concluido)

    assert len(execucoes) == 1
    payload, saida = execucoes[0]
    assert payload.job_id == codigo_gerado_seed["job_id"]
    assert payload.fonte == EXEMPLO, "o container recebeu outra fonte que não a do banco"
    assert (saida.codigo_saida, saida.oom_killed, saida.estourou_timeout) == (0, False, False)
    envelope = json.loads(saida.stdout)
    assert envelope["status"] == "sucesso"
    assert envelope["resultado"]["totais"]["baseline"] == BASELINE_2025_11
    assert "orcamento" not in envelope["resultado"]["totais"]
    assert _containers_do_job(payload.job_id) == []
    assert await _retirar(broker_real, broker_real.fila.name) is None
    assert await _retirar(broker_real, f"{broker_real.fila.name}.dlq") is None


async def test_falha_de_infraestrutura_no_container_esgota_o_retry_e_chega_a_dlq(
    monkeypatch: pytest.MonkeyPatch,
    broker_real: ConexaoBroker,
    codigo_gerado_seed: dict[str, Any],
    imagem: str,
) -> None:
    """Uma imagem que não existe é falha nossa, não da regra: o comando é tentado três vezes
    (DEC-091) e só então vai para a DLQ, para diagnóstico."""
    tentativas: list[UUID] = []
    executar: Callable[..., SaidaBruta] = executar_no_sandbox

    def executar_com_imagem_inexistente(payload: PayloadContainer) -> SaidaBruta:
        tentativas.append(payload.job_id)
        return executar(payload, imagem="synapse-sandbox:inexistente")

    monkeypatch.setattr(consumidor, "executar_no_sandbox", executar_com_imagem_inexistente)
    concluido = _observar_processamento(monkeypatch, total=TENTATIVAS_TOTAIS)
    await broker_real.canal.default_exchange.publish(
        _comando(codigo_gerado_seed), routing_key=broker_real.fila.name
    )

    await _consumir_ate(broker_real, concluido)

    assert len(tentativas) == TENTATIVAS_TOTAIS
    assert await _retirar(broker_real, broker_real.fila.name) is None
    na_dlq = await _retirar(broker_real, f"{broker_real.fila.name}.dlq")
    assert na_dlq is not None, "o comando não chegou à DLQ"
    assert json.loads(na_dlq.body)["job_id"] == str(codigo_gerado_seed["job_id"])
    assert na_dlq.headers[HEADER_RETRY] == TENTATIVAS_TOTAIS - 1
    assert _containers_do_job(codigo_gerado_seed["job_id"]) == []  # type: ignore[arg-type]
