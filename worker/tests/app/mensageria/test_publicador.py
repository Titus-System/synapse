"""A publicação de `simulacao-concluida` (T-067), sem broker: o que é enviado e como.

O comportamento contra um RabbitMQ de verdade (fanout, duas filas, consumidor desligado, mensagem
sem rota) está em `test_publicador_integration.py`.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aio_pika import DeliveryMode
from aio_pika.exceptions import DeliveryError
from pamqp.commands import Basic

from app.mensageria.broker import ConexaoBroker
from app.mensageria.contracts import SimulacaoConcluida
from app.mensageria.publicador import (
    PublicacaoError,
    mensagem_do_evento,
    publicar_simulacao_concluida,
)
from tests.app.esquemas import erros_do_evento
from tests.app.mensageria.resultado_falso import ExchangeFalsa

SUCESSO = SimulacaoConcluida(
    job_id=uuid4(),
    resultado_id=uuid4(),
    status="sucesso",
    veredito="inviavel",
    total_baseline=480312.0,
    total_simulado=492100.0,
    diferenca_abs=11788.0,
    diferenca_pct=0.0245,
)
ERRO = SimulacaoConcluida(job_id=uuid4(), resultado_id=uuid4(), status="erro_codigo")


def broker_com(exchange: ExchangeFalsa) -> ConexaoBroker:
    return ConexaoBroker(  # type: ignore[arg-type]
        conexao=AsyncMock(), canal=MagicMock(), fila=MagicMock(), exchange=exchange
    )


async def test_publica_na_exchange_sem_chave_de_roteamento_e_com_mandatory() -> None:
    """Fanout ignora a chave; `mandatory` é o que impede o broker de descartar em silêncio uma
    mensagem para quem ainda não ligou a sua fila."""
    exchange = ExchangeFalsa()

    await publicar_simulacao_concluida(broker_com(exchange), SUCESSO)

    assert exchange.chamadas == [{"routing_key": "", "mandatory": True}]
    assert len(exchange.publicadas) == 1


@pytest.mark.parametrize("evento", [SUCESSO, ERRO], ids=["sucesso", "erro"])
async def test_o_corpo_valida_contra_o_schema_do_evento(evento: SimulacaoConcluida) -> None:
    exchange = ExchangeFalsa()

    await publicar_simulacao_concluida(broker_com(exchange), evento)

    corpo = json.loads(exchange.publicadas[0].body)
    assert erros_do_evento("simulacao-concluida", corpo) == []
    assert corpo["resultado_id"] == str(evento.resultado_id)


async def test_evento_de_erro_nao_leva_campos_vazios() -> None:
    """`veredito` e os agregados ausentes, e não `null`: o schema os declara ausentes fora de
    `sucesso`, e a api lê `veredito == null` como ausente só por acaso."""
    exchange = ExchangeFalsa()

    await publicar_simulacao_concluida(broker_com(exchange), ERRO)

    assert set(json.loads(exchange.publicadas[0].body)) == {"job_id", "resultado_id", "status"}


def test_a_mensagem_e_json_utf8_persistente_e_identificavel() -> None:
    mensagem = mensagem_do_evento(SUCESSO)

    assert mensagem.content_type == "application/json"
    assert mensagem.content_encoding == "utf-8"
    assert mensagem.delivery_mode == DeliveryMode.PERSISTENT
    assert mensagem.type == "simulacao-concluida"
    assert mensagem.message_id == str(SUCESSO.resultado_id)
    assert mensagem.correlation_id == str(SUCESSO.job_id)
    assert mensagem.app_id == "synapse-worker"


def test_o_message_id_e_estavel_entre_republicacoes() -> None:
    assert mensagem_do_evento(SUCESSO).message_id == mensagem_do_evento(SUCESSO).message_id


@pytest.mark.parametrize(
    "erro", [DeliveryError(None, None), ConnectionError("caiu"), RuntimeError("canal fechado")]
)
async def test_falha_do_broker_vira_publicacao_error(erro: Exception) -> None:
    exchange = ExchangeFalsa()
    exchange.erro = erro

    with pytest.raises(PublicacaoError) as excinfo:
        await publicar_simulacao_concluida(broker_com(exchange), SUCESSO)

    assert excinfo.value.__cause__ is erro


async def test_confirmacao_negativa_vira_publicacao_error() -> None:
    exchange = ExchangeFalsa()
    exchange.confirmacao = Basic.Nack()

    with pytest.raises(PublicacaoError, match="confirmação"):
        await publicar_simulacao_concluida(broker_com(exchange), SUCESSO)


async def test_sem_confirmacao_nenhuma_tambem_e_falha() -> None:
    exchange = ExchangeFalsa()
    exchange.confirmacao = None

    with pytest.raises(PublicacaoError):
        await publicar_simulacao_concluida(broker_com(exchange), SUCESSO)


async def test_o_cancelamento_nao_e_engolido() -> None:
    """Encerrar o worker no meio de uma publicação não pode ser tratado como falha do broker: o
    comando seria republicado por uma tarefa que está sendo cancelada."""
    exchange = ExchangeFalsa()
    exchange.erro = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await publicar_simulacao_concluida(broker_com(exchange), SUCESSO)
