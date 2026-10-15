"""Real API, Postgres and RabbitMQ; requires a disposable T211_* environment.

The API must use the test database and isolated vhost, with outbox disabled and
Keycloak disabled. Only the model is scripted; no generated code is executed here.
"""

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest
import simplejson
from aio_pika import Message, connect_robust
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from tests.app.confirmacao_falsa import RESPOSTA
from tests.app.graph.conftest import FakeChatModel
from tests.app.graph.test_validacao_principal import amostra
from tests.app.test_mensageria import oficial

from app.config import Settings
from app.main import criar_aplicacao_padrao

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.rabbitmq,
    pytest.mark.skipif(
        not all(os.getenv(n) for n in ("T211_API_URL", "T211_POSTGRES_HOST", "T211_RABBITMQ_HOST")),
        reason="Requires disposable API, Postgres and RabbitMQ configured through T211_*",
    ),
]


async def test_regra_coerente_passa_pela_validacao_e_chega_a_simulacao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = os.environ["T211_POSTGRES_HOST"]
    dono = await asyncpg.connect(
        host=host, user="postgres", password="teste-local", database="t211_validacao"
    )
    config = Settings(
        POSTGRES_HOST=host,
        POSTGRES_DB="t211_validacao",
        SYNAPSE_CODEGEN_DB_USER="t211_codegen",
        SYNAPSE_CODEGEN_DB_PASSWORD="teste-local",
        RABBITMQ_HOST=os.environ["T211_RABBITMQ_HOST"],
        RABBITMQ_USER="t204",
        RABBITMQ_PASSWORD="teste-local",
        RABBITMQ_VHOST="t211",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: config)
    monkeypatch.setattr("app.graph.core.checkpointer.get_settings", lambda: config)
    monkeypatch.setattr("app.main.stop_logger", lambda: None)
    modelo = FakeChatModel(messages=iter([AIMessage(content=RESPOSTA)]))
    monkeypatch.setattr("app.graph.nodes.code_generation.get_model", lambda _: modelo)
    app = criar_aplicacao_padrao()
    conexao = await connect_robust(config.rabbitmq_url)
    try:
        await dono.execute(
            "INSERT INTO usuarios(id, login, senha_hash, nome, papel, criado_em)"
            " VALUES($1, $2, 'x', 'Teste', 'profissional_rh', now())",
            uuid4(),
            str(uuid4()),
        )
        nucleo = {
            "percentual": 0.025,
            "loja": [],
            "marca": [],
            "cargo": [],
            "vigencia": {"inicio": "2025-08", "fim": "2025-12"},
        }
        async with AsyncClient(base_url=os.environ["T211_API_URL"], timeout=20) as api:
            corpo = {
                "origem": "formulario",
                "competencias": ["2025-11"],
                "orcamento": 500,
                "conteudo": {"nucleo": nucleo, "texto_livre": None},
            }
            resposta = await api.post("/jobs", json=corpo)
            assert resposta.status_code == 201, resposta.text
            coerente = resposta.json()
            async with app.router.lifespan_context(app):
                canal = await conexao.channel()
                execucoes = await canal.declare_queue("executar-codigo", durable=True)
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as codegen:
                    antes = (await codegen.get("/metrics")).text
                    payload = {
                        "job_id": coerente["id"],
                        "regra_id": coerente["regra"]["id"],
                        "submissao_id": coerente["submissao_id"],
                        "origem": "formulario",
                        "competencias": ["2025-11"],
                        "orcamento": 500,
                    }
                    oficial("regra-submetida").validate(payload)
                    await canal.default_exchange.publish(
                        Message(body=simplejson.dumps(payload).encode()),
                        routing_key="regra-submetida",
                    )
                    async with asyncio.timeout(30):
                        while True:
                            consulta = await api.get(f"/jobs/{coerente['id']}")
                            assert consulta.status_code == 200
                            if consulta.json()["status"] == "simulando":
                                break
                            await asyncio.sleep(0.1)
                    comando = await execucoes.get(timeout=10)
                    assert comando is not None
                    payload_execucao = simplejson.loads(comando.body)
                    oficial("executar-codigo").validate(payload_execucao)
                    assert payload_execucao["job_id"] == coerente["id"]
                    await comando.ack()
                    assert len(modelo.seen_messages) == 1
                    depois = (await codegen.get("/metrics")).text
                    nome = "codegen_validacao_dominio_resultados_total"
                    labels = {"resultado": "liberada"}
                    assert amostra(depois, nome, labels) - amostra(antes, nome, labels) == 1
    finally:
        await conexao.close()
        await dono.close()
