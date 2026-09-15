"""Fecha o loop com um RabbitMQ e um Postgres reais — o que os testes com fila e
sessão falsas (`test_consumidor.py`) não alcançam: que `consumir_fila_execucao` de fato lê da
fila declarada por `conectar` e que o `prefetch` 1 do canal real serializa o
processamento de dois comandos publicados de uma vez.
"""

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from aio_pika import Message

from app.mensageria import consumidor
from app.mensageria.broker import conectar, desconectar
from app.repositorio.codigos_gerados import buscar_codigo as buscar_codigo_real

if TYPE_CHECKING:
    from app.config import Settings

pytestmark = [pytest.mark.postgres, pytest.mark.rabbitmq]


async def test_dois_comandos_reais_sao_processados_um_de_cada_vez(
    monkeypatch: pytest.MonkeyPatch,
    settings: "Settings",
    codigo_gerado_seed: dict[str, object],
) -> None:
    broker = await conectar()
    await broker.fila.purge()

    ordem: list[str] = []

    async def buscar_codigo_instrumentado(sessao: object, codigo_gerado_id: object) -> object:
        ordem.append("entrou")
        await asyncio.sleep(0.05)
        resultado = await buscar_codigo_real(sessao, codigo_gerado_id)  # type: ignore[arg-type]
        ordem.append("saiu")
        return resultado

    monkeypatch.setattr(consumidor, "buscar_codigo", buscar_codigo_instrumentado)

    for _ in range(2):
        corpo = {
            "job_id": str(uuid4()),
            "codigo_gerado_id": str(codigo_gerado_seed["id"]),
            "competencias": ["2025-08"],
            "orcamento": 1000.0,
        }
        await broker.canal.default_exchange.publish(
            Message(body=json.dumps(corpo).encode("utf-8")),
            routing_key=settings.RABBITMQ_FILA_EXECUCAO,
        )

    tarefa = asyncio.create_task(consumidor.consumir_fila_execucao(broker))
    try:
        for _ in range(100):
            if len(ordem) >= 4:
                break
            await asyncio.sleep(0.05)
    finally:
        tarefa.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarefa
        await desconectar(broker)

    assert ordem == ["entrou", "saiu", "entrou", "saiu"]
