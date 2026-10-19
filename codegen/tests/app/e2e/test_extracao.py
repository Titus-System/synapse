"""Real Postgres, RabbitMQ, checkpointer and app; only the LLM is scripted.

T204_POSTGRES_HOST and T204_RABBITMQ_HOST must point at disposable test servers.
The database is created for this test and the RabbitMQ server must be isolated.
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import simplejson
from aio_pika import Message, connect_robust
from httpx import ASGITransport, AsyncClient
from tests.app.extracao.test_motor import modelo_falso
from tests.app.graph.test_extracao import NUCLEO, SAIDA, TEXTO, amostra
from tests.app.test_mensageria import oficial

from app.config import Settings
from app.graph.core.checkpointer import get_checkpointer
from app.graph.core.engine import build_graph
from app.main import criar_aplicacao_padrao

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.rabbitmq,
    pytest.mark.skipif(
        not (os.getenv("T204_POSTGRES_HOST") and os.getenv("T204_RABBITMQ_HOST")),
        reason="Requer Postgres e RabbitMQ descartáveis, configurados por T204_*_HOST",
    ),
]


async def test_texto_publicado_na_fila_persiste_e_expoe_metricas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = os.environ["T204_POSTGRES_HOST"]
    administrador = await asyncpg.connect(
        host=host, user="postgres", password="teste-local", database="postgres"
    )
    banco = f"t204_{uuid4().hex}"
    await administrador.execute(f'CREATE DATABASE "{banco}"')
    dono = await asyncpg.connect(host=host, user="postgres", password="teste-local", database=banco)
    try:
        migrations = (
            Path(__file__).resolve().parents[4] / "api/src/main/resources/db/changelog/changesets"
        )
        for arquivo in sorted(migrations.glob("*.sql")):
            sql = arquivo.read_text()
            for papel in ("api", "codegen", "worker"):
                sql = sql.replace("${usuario_" + papel + "}", "t204_" + papel)
            await dono.execute(sql)
        await dono.execute("ALTER ROLE t204_codegen WITH PASSWORD 'teste-local'")
        usuario, job, submissao = uuid4(), uuid4(), uuid4()
        await dono.execute(
            "INSERT INTO usuarios(id, login, senha_hash, nome, papel, criado_em)"
            " VALUES($1, $2, 'x', 'Teste', 'profissional_rh', now())",
            usuario,
            str(usuario),
        )
        await dono.execute(
            "INSERT INTO submissoes(id, usuario_id, tipo, transcricao, criado_em)"
            " VALUES($1, $2, 'texto', $3, now())",
            submissao,
            usuario,
            TEXTO,
        )
        await dono.execute(
            "INSERT INTO jobs"
            " (id, usuario_id, submissao_id, status, competencias, orcamento, criado_em)"
            " VALUES($1, $2, $3, 'gerando_regra', '{2025-11}', 500, now())",
            job,
            usuario,
            submissao,
        )
        config = Settings(
            POSTGRES_HOST=host,
            POSTGRES_DB=banco,
            SYNAPSE_CODEGEN_DB_USER="t204_codegen",
            SYNAPSE_CODEGEN_DB_PASSWORD="teste-local",
            RABBITMQ_HOST=os.environ["T204_RABBITMQ_HOST"],
            RABBITMQ_USER="t204",
            RABBITMQ_PASSWORD="teste-local",
            RABBITMQ_VHOST="/",
        )
        monkeypatch.setattr("app.main.get_settings", lambda: config)
        monkeypatch.setattr("app.graph.core.checkpointer.get_settings", lambda: config)
        monkeypatch.setattr("app.main.stop_logger", lambda: None)
        modelo = modelo_falso(SAIDA)
        monkeypatch.setattr("app.graph.core.llm.registry.get_model", lambda _: modelo)
        app = criar_aplicacao_padrao()
        conexao = await connect_robust(config.rabbitmq_url)
        try:
            async with app.router.lifespan_context(app):
                canal = await conexao.channel()
                extraidas = await canal.declare_queue("regra-extraida", durable=True)
                trilhas = await canal.declare_queue("no-concluido", durable=True)
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as cliente:
                    antes = (await cliente.get("/metrics")).text
                    payload = {
                        "job_id": str(job),
                        "submissao_id": str(submissao),
                        "origem": "texto",
                        "competencias": ["2025-11"],
                        "orcamento": 500,
                    }
                    await canal.default_exchange.publish(
                        Message(body=simplejson.dumps(payload).encode()),
                        routing_key="regra-submetida",
                    )
                    evento = await extraidas.get(timeout=15, fail=False)
                    async with asyncio.timeout(15):
                        while evento is None:
                            await asyncio.sleep(0.1)
                            evento = await extraidas.get(fail=False)
                    assert evento is not None
                    extraida = simplejson.loads(evento.body)
                    oficial("regra-extraida").validate(extraida)
                    assert set(extraida) == {"job_id", "submissao_id", "extracao_id"}
                    assert extraida["job_id"] == str(job)
                    assert extraida["submissao_id"] == str(submissao)
                    await evento.ack()
                    async with asyncio.timeout(15):
                        trilha = None
                        while trilha is None:
                            trilha = await trilhas.get(fail=False)
                            if trilha is None:
                                await asyncio.sleep(0.1)
                    await trilha.ack()
                    async with asyncio.timeout(15):
                        while True:
                            async with get_checkpointer() as saver:
                                estado = await build_graph(saver).aget_state(
                                    {"configurable": {"thread_id": str(job)}}
                                )
                            if estado.values and not estado.next:
                                break
                            await asyncio.sleep(0.1)
                    [linha] = await dono.fetch(
                        "SELECT e.id AS extracao_id, e.representacao::text,"
                        " e.parametros::text AS parametros, p.no,"
                        " p.conteudo AS prompt, r.conteudo AS resposta"
                        " FROM extracoes_regras e JOIN respostas_modelo r ON r.id=e.resposta_id"
                        " JOIN prompts p ON p.id=r.prompt_id WHERE e.job_id=$1",
                        job,
                    )
                    assert simplejson.loads(linha["representacao"], use_decimal=True) == {
                        "nucleo": NUCLEO,
                        "especificacoes": [],
                    }
                    assert simplejson.loads(linha["parametros"], use_decimal=True) == {}
                    assert linha["no"] == "extracao_parametros"
                    assert str(linha["extracao_id"]) == extraida["extracao_id"]
                    assert TEXTO in linha["prompt"]
                    assert simplejson.loads(linha["resposta"], use_decimal=True) == SAIDA
                    depois = (await cliente.get("/metrics")).text
                    for nome in ("job_runs_total", "job_duration_seconds_count"):
                        labels = {"job_name": "extract_rule"}
                        assert amostra(depois, nome, labels) - amostra(antes, nome, labels) == 1
                    assert len(modelo.seen_messages) == 1
        finally:
            await conexao.close()
    finally:
        await dono.close()
        await administrador.execute(f'DROP DATABASE "{banco}" WITH (FORCE)')
        await administrador.close()
