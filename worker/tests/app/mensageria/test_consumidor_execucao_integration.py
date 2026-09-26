"""O fluxo de execução inteiro com peças reais: comando no RabbitMQ, código no Postgres,
container Docker efêmero a partir da imagem do sandbox, e o resultado gravado e publicado.

`test_consumidor.py` prova a fiação com fakes; aqui nada é falso. O que estes testes alcançam e
aqueles não: que o código que sai do banco é o que roda dentro do container, que o resultado é o
do motor de verdade, que a linha gravada é a que o evento referencia (e já existe quando o
consumidor o recebe), que perder o evento não perde a linha nem a duplica ao reentregar, e que a
falha de infraestrutura percorre o retry do broker real até a DLQ, deixando o desfecho gravado.

Marcados `postgres` e `rabbitmq`, e não `docker`: o `verify.sh` roda `-m docker` sempre que há
daemon (é o caso da CI, que não tem Postgres nem RabbitMQ), e estes testes não poderiam subir.
Onde o compose está de pé o Docker também está, então a imagem do sandbox não é obstáculo.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import docker
import pytest
from aio_pika import Message
from aio_pika.abc import AbstractIncomingMessage, AbstractQueue

from app.config import get_settings
from app.execucao.container import ROTULO_JOB, SaidaBruta, executar_no_sandbox
from app.execucao.preparo import PayloadContainer
from app.mensageria import consumidor
from app.mensageria.broker import ConexaoBroker
from app.mensageria.retry import HEADER_RETRY
from tests.app.esquemas import erros_do_evento
from tests.app.mensageria.test_publicador_integration import (
    FILA_API,
    FILA_CODEGEN,
    declarar_fila,
    retirar,
)
from tests.app.sandbox.test_harness import EXEMPLO

pytestmark = [pytest.mark.postgres, pytest.mark.rabbitmq]

BASELINE_2025_11 = 508382.32
TENTATIVAS_TOTAIS = 3  # DEC-091: a inicial e duas republicações
PRAZO_S = 180.0


@pytest.fixture
def fonte_do_codigo_seed() -> str:
    """O banco guarda a regra de exemplo do contrato, que o motor sabe executar."""
    return EXEMPLO


@pytest.fixture(autouse=True)
def banco() -> None:
    """Sobrescreve o `banco` autouse do conftest: aqui a gravação é a de verdade, com o usuário
    do worker, e quem limpa é o dono do schema (o `codigo_gerado_seed`)."""


@pytest.fixture
async def filas(broker_real: ConexaoBroker) -> tuple[AbstractQueue, AbstractQueue]:
    """As filas da api e do codegen, declaradas e ligadas como cada um faz ao subir."""
    return (
        await declarar_fila(broker_real, FILA_API),
        await declarar_fila(broker_real, FILA_CODEGEN),
    )


async def _linhas_do_job(conexao_dono: Any, job_id: UUID) -> list[Any]:
    return list(
        await conexao_dono.fetch(
            "SELECT * FROM resultados_simulacao WHERE job_id = $1 ORDER BY criado_em, id", job_id
        )
    )


def _comando(codigo_gerado_seed: dict[str, Any], orcamento: float = 485000.0) -> Message:
    corpo = {
        "job_id": str(codigo_gerado_seed["job_id"]),
        "codigo_gerado_id": str(codigo_gerado_seed["id"]),
        "competencias": ["2025-11"],
        "orcamento": orcamento,
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


# O exemplo do contrato apura 494.037,78 sobre o baseline de 508.382,32 de novembro.
SIMULADO_DO_EXEMPLO = 494037.78


def _espia_do_container(
    monkeypatch: pytest.MonkeyPatch, imagem: str
) -> list[tuple[PayloadContainer, SaidaBruta]]:
    execucoes: list[tuple[PayloadContainer, SaidaBruta]] = []

    def executar_na_imagem_de_teste(payload: PayloadContainer, **kwargs: Any) -> SaidaBruta:
        saida = executar_no_sandbox(payload, imagem=imagem, **kwargs)
        execucoes.append((payload, saida))
        return saida

    monkeypatch.setattr(consumidor, "executar_no_sandbox", executar_na_imagem_de_teste)
    return execucoes


@pytest.mark.parametrize(
    ("orcamento", "veredito"),
    [
        (485000.0, "inviavel"),
        (SIMULADO_DO_EXEMPLO - 0.01, "inviavel"),
        (SIMULADO_DO_EXEMPLO, "viavel"),
        (600000.0, "viavel"),
    ],
    ids=["abaixo", "um centavo abaixo", "igual", "acima"],
)
async def test_comando_no_rabbitmq_vira_linha_no_banco_e_evento_nas_duas_filas(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    broker_real: ConexaoBroker,
    filas: tuple[AbstractQueue, AbstractQueue],
    conexao_dono: Any,
    codigo_gerado_seed: dict[str, Any],
    imagem: str,
    orcamento: float,
    veredito: str,
) -> None:
    fila_api, fila_codegen = filas
    caplog.set_level(logging.INFO)
    execucoes = _espia_do_container(monkeypatch, imagem)

    # O consumidor do codegen confere, no instante em que recebe o evento, que a linha que ele
    # referencia já é consultável: é a ordem "gravar antes de publicar", vista de fora.
    recebidos: list[tuple[dict[str, Any], bool]] = []

    async def ao_receber(mensagem: AbstractIncomingMessage) -> None:
        async with mensagem.process():
            corpo = json.loads(mensagem.body)
            linha = await conexao_dono.fetchrow(
                "SELECT id FROM resultados_simulacao WHERE id = $1", UUID(corpo["resultado_id"])
            )
            recebidos.append((corpo, linha is not None))

    await fila_codegen.consume(ao_receber)
    concluido = _observar_processamento(monkeypatch, total=1)
    await broker_real.canal.default_exchange.publish(
        _comando(codigo_gerado_seed, orcamento), routing_key=broker_real.fila.name
    )

    await _consumir_ate(broker_real, concluido)
    for _ in range(100):
        if recebidos:
            break
        await asyncio.sleep(0.05)

    julgados = [r for r in caplog.records if r.getMessage() == "execução julgada"]
    assert len(julgados) == 1
    assert (julgados[0].classe, julgados[0].motivo, julgados[0].veredito) == (  # type: ignore[attr-defined]
        "sucesso",
        "ok",
        veredito,
    )
    assert len(execucoes) == 1
    payload, saida = execucoes[0]
    assert payload.job_id == codigo_gerado_seed["job_id"]
    assert payload.fonte == EXEMPLO, "o container recebeu outra fonte que não a do banco"
    assert (saida.codigo_saida, saida.oom_killed, saida.estourou_timeout) == (0, False, False)
    assert "orcamento" not in json.loads(saida.stdout)["resultado"]["totais"]
    assert _containers_do_job(payload.job_id) == []

    # A linha: uma só, com o resultado inteiro e o orçamento do comando.
    (linha,) = await _linhas_do_job(conexao_dono, codigo_gerado_seed["job_id"])
    assert (linha["status"], linha["veredito"]) == ("sucesso", veredito)
    assert linha["codigo_gerado_id"] == codigo_gerado_seed["id"]
    totais = json.loads(linha["totais"])
    assert (totais["baseline"], totais["simulado"]) == (BASELINE_2025_11, SIMULADO_DO_EXEMPLO)
    assert totais["orcamento"] == orcamento
    assert json.loads(linha["decomposicao"]) is not None
    assert [a["resultado"] for a in json.loads(linha["assercoes"])] == ["ok"]

    # O evento: o mesmo nas duas filas, referenciando a linha, e a linha já existia ao recebê-lo.
    assert len(recebidos) == 1
    corpo, linha_visivel_ao_receber = recebidos[0]
    assert linha_visivel_ao_receber is True
    assert corpo["resultado_id"] == str(linha["id"])
    assert corpo["job_id"] == str(codigo_gerado_seed["job_id"])
    assert (corpo["status"], corpo["veredito"]) == ("sucesso", veredito)
    assert corpo["total_simulado"] == SIMULADO_DO_EXEMPLO
    assert erros_do_evento("simulacao-concluida", corpo) == []
    da_api = await retirar(fila_api)
    assert da_api is not None and json.loads(da_api.body) == corpo

    assert await _retirar(broker_real, broker_real.fila.name) is None
    assert await _retirar(broker_real, f"{broker_real.fila.name}.dlq") is None


async def test_evento_perdido_nao_perde_a_linha_e_a_reentrega_nao_a_duplica(
    monkeypatch: pytest.MonkeyPatch,
    broker_real: ConexaoBroker,
    conexao_dono: Any,
    codigo_gerado_seed: dict[str, Any],
    imagem: str,
) -> None:
    """Sem nenhuma fila ligada o broker devolve o evento e a publicação falha, três vezes. A
    linha, gravada antes, continua consultável, e é uma só: as reentregas a encontraram em vez de
    executar de novo. Religada a fila, o operador reenvia o comando da DLQ e o evento sai, ainda
    sem executar o container nem gravar outra linha."""
    execucoes = _espia_do_container(monkeypatch, imagem)
    job_id = codigo_gerado_seed["job_id"]
    concluido = _observar_processamento(monkeypatch, total=TENTATIVAS_TOTAIS)
    await broker_real.canal.default_exchange.publish(
        _comando(codigo_gerado_seed), routing_key=broker_real.fila.name
    )

    await _consumir_ate(broker_real, concluido)

    (linha,) = await _linhas_do_job(conexao_dono, job_id)
    assert linha["status"] == "sucesso"
    assert len(execucoes) == 1, "a reentrega executou o container de novo"
    na_dlq = await _retirar(broker_real, f"{broker_real.fila.name}.dlq")
    assert na_dlq is not None, "o comando não chegou à DLQ"

    # A fila do codegen volta, e o operador reenvia o comando: só o evento faltava.
    fila_codegen = await declarar_fila(broker_real, FILA_CODEGEN)
    await broker_real.canal.default_exchange.publish(
        Message(body=na_dlq.body), routing_key=broker_real.fila.name
    )
    concluido = _observar_processamento(monkeypatch, total=1)

    await _consumir_ate(broker_real, concluido)

    recebido = await retirar(fila_codegen)
    assert recebido is not None
    assert json.loads(recebido.body)["resultado_id"] == str(linha["id"])
    assert len(execucoes) == 1
    assert len(await _linhas_do_job(conexao_dono, job_id)) == 1
    assert await _retirar(broker_real, broker_real.fila.name) is None


async def test_falha_de_infraestrutura_no_container_esgota_o_retry_grava_o_erro_e_chega_a_dlq(
    monkeypatch: pytest.MonkeyPatch,
    broker_real: ConexaoBroker,
    filas: tuple[AbstractQueue, AbstractQueue],
    conexao_dono: Any,
    codigo_gerado_seed: dict[str, Any],
    imagem: str,
) -> None:
    """Uma imagem que não existe é falha nossa, não da regra: o comando é tentado três vezes
    (DEC-091) e só então vai para a DLQ. Antes disso o desfecho é gravado e publicado (DEC-094),
    senão o job ficaria em `simulando` para sempre."""
    fila_api, fila_codegen = filas
    tentativas: list[UUID] = []
    executar: Callable[..., SaidaBruta] = executar_no_sandbox

    def executar_com_imagem_inexistente(payload: PayloadContainer, **kwargs: Any) -> SaidaBruta:
        tentativas.append(payload.job_id)
        return executar(payload, imagem="synapse-sandbox:inexistente", **kwargs)

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

    # Uma linha só, gravada no esgotamento, e não a cada tentativa.
    (linha,) = await _linhas_do_job(conexao_dono, codigo_gerado_seed["job_id"])
    assert linha["status"] == "erro_infra"
    assert (linha["veredito"], linha["totais"], linha["decomposicao"]) == (None, None, None)
    assert json.loads(linha["assercoes"]) == []
    for fila in (fila_api, fila_codegen):
        evento = await retirar(fila)
        assert evento is not None, "o erro_infra não foi publicado"
        corpo = json.loads(evento.body)
        assert corpo["status"] == "erro_infra" and corpo["resultado_id"] == str(linha["id"])
        assert "veredito" not in corpo
        assert erros_do_evento("simulacao-concluida", corpo) == []
        assert await retirar(fila) is None, "o erro_infra foi publicado mais de uma vez"
