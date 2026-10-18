"""Real Postgres, RabbitMQ, checkpointer and app; only the LLM is scripted (T-221).

T204_POSTGRES_HOST and T204_RABBITMQ_HOST must point at disposable test servers, as in
`test_extracao.py`. The database is created for this test, and the rows the api writes before
publishing `correcao-submetida` are inserted by hand.
"""

import asyncio
import os
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
import simplejson
from aio_pika import Message, connect_robust
from aio_pika.abc import AbstractQueue
from httpx import ASGITransport, AsyncClient
from tests.app.extracao.test_motor import modelo_falso
from tests.app.graph.test_extracao import amostra
from tests.app.graph.test_reextracao import PERCENTUAL, TEXTO
from tests.app.test_mensageria import oficial

from app.config import Settings
from app.main import criar_aplicacao_padrao

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.rabbitmq,
    pytest.mark.skipif(
        not (os.getenv("T204_POSTGRES_HOST") and os.getenv("T204_RABBITMQ_HOST")),
        reason="Requer Postgres e RabbitMQ descartáveis, configurados por T204_*_HOST",
    ),
]
SAIDA = {"operacoes": [PERCENTUAL]}


async def _do_job(fila: AbstractQueue, evento: str, job_id: UUID) -> dict[str, Any]:
    """A próxima mensagem do job na fila; as de outros jobs do servidor descartável saem."""
    async with asyncio.timeout(30):
        while True:
            recebida = await fila.get(fail=False)
            if recebida is None:
                await asyncio.sleep(0.1)
                continue
            await recebida.ack()
            payload: dict[str, Any] = simplejson.loads(recebida.body, use_decimal=True)
            if payload.get("job_id") == str(job_id):
                oficial(evento).validate(payload)
                return payload


async def test_correcao_publicada_na_fila_produz_a_proposta_artefatos_e_metricas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = os.environ["T204_POSTGRES_HOST"]
    administrador = await asyncpg.connect(
        host=host, user="postgres", password="teste-local", database="postgres"
    )
    banco = f"t221_{uuid4().hex}"
    await administrador.execute(f'CREATE DATABASE "{banco}"')
    dono = await asyncpg.connect(host=host, user="postgres", password="teste-local", database=banco)
    try:
        migrations = (
            Path(__file__).resolve().parents[4] / "api/src/main/resources/db/changelog/changesets"
        )
        for arquivo in sorted(migrations.glob("*.sql")):
            sql = arquivo.read_text()
            for papel in ("api", "codegen", "worker"):
                sql = sql.replace("${usuario_" + papel + "}", "t221_" + papel)
            await dono.execute(sql)
        await dono.execute("ALTER ROLE t221_codegen WITH PASSWORD 'teste-local'")
        usuario, job, outro_job = uuid4(), uuid4(), uuid4()
        entrada, correcao, regra, regra_de_outro_job = uuid4(), uuid4(), uuid4(), uuid4()
        await dono.execute(
            "INSERT INTO usuarios(id, login, senha_hash, nome, papel, criado_em)"
            " VALUES($1, $2, 'x', 'Teste', 'profissional_rh', now())",
            usuario,
            str(usuario),
        )
        for submissao, texto in ((entrada, "Pague na loja 13."), (correcao, TEXTO)):
            await dono.execute(
                "INSERT INTO submissoes(id, usuario_id, tipo, transcricao, criado_em)"
                " VALUES($1, $2, 'texto', $3, now())",
                submissao,
                usuario,
                texto,
            )
        for id_job, id_regra in ((job, regra), (outro_job, regra_de_outro_job)):
            await dono.execute(
                "INSERT INTO jobs"
                " (id, usuario_id, submissao_id, status, competencias, orcamento, criado_em)"
                " VALUES($1, $2, $3, 'aguardando_confirmacao_parametros', '{2025-10,2025-11}',"
                " 500000, now())",
                id_job,
                usuario,
                entrada,
            )
            await dono.execute(
                "INSERT INTO regras"
                " (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em)"
                " VALUES($1, $2, 1, 'extracao', '{\"loja\": [\"13\"]}', '[]', $3, now())",
                id_regra,
                id_job,
                uuid4().hex * 2,
            )
        # A extração do job descartou a meta por falta de lastro: a validação da versão aponta o
        # conflito, e a reextração o recalcula pela consulta real (T-280).
        prompt_da_extracao, resposta_da_extracao = uuid4(), uuid4()
        await dono.execute(
            "INSERT INTO prompts(id, job_id, no, conteudo, modelo, criado_em)"
            " VALUES($1, $2, 'extracao_parametros', 'extração', '{}', now())",
            prompt_da_extracao,
            job,
        )
        await dono.execute(
            "INSERT INTO respostas_modelo(id, job_id, prompt_id, conteudo, criado_em)"
            " VALUES($1, $2, $3, '{}', now())",
            resposta_da_extracao,
            job,
            prompt_da_extracao,
        )
        await dono.execute(
            "INSERT INTO extracoes_regras"
            " (id, job_id, submissao_id, resposta_id, representacao, rebaixamentos, criado_em)"
            " VALUES($1, $2, $3, $4, '{}', $5::jsonb, now())",
            uuid4(),
            job,
            entrada,
            resposta_da_extracao,
            simplejson.dumps([{"ref": "parametros.meta_venda", "motivo": "valor_sem_lastro"}]),
        )
        config = Settings(
            POSTGRES_HOST=host,
            POSTGRES_DB=banco,
            SYNAPSE_CODEGEN_DB_USER="t221_codegen",
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
                propostas = await canal.declare_queue("correcao-proposta", durable=True)
                etapas = await canal.declare_queue("etapa-alterada", durable=True)
                trilhas = await canal.declare_queue("no-concluido", durable=True)
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as cliente:
                    antes = (await cliente.get("/metrics")).text
                    payload = {
                        "job_id": str(job),
                        "regra_origem_id": str(regra),
                        "submissao_id": str(correcao),
                        "competencias": ["2025-10", "2025-11"],
                        "orcamento": 500000,
                    }
                    oficial("correcao-submetida").validate(payload)
                    # A versão de outro job é recusada pela consulta real a `regras`.
                    alheia = payload | {
                        "job_id": str(outro_job),
                        "regra_origem_id": str(regra),
                        "submissao_id": str(uuid4()),
                    }
                    for mensagem in (payload, alheia):
                        await canal.default_exchange.publish(
                            Message(body=simplejson.dumps(mensagem).encode()),
                            routing_key="correcao-submetida",
                        )

                    proposta = await _do_job(propostas, "correcao-proposta", job)
                    assert proposta == {
                        "job_id": str(job),
                        "regra_origem_id": str(regra),
                        "submissao_id": str(correcao),
                        "representacao": {
                            "nucleo": {"loja": ["13"], "percentual": Decimal("0.03")},
                            "especificacoes": [],
                        },
                        "parametros": {"competencias": ["2025-10", "2025-11"], "orcamento": 500000},
                    }
                    trilha = await _do_job(trilhas, "no-concluido", job)
                    falha = await _do_job(etapas, "etapa-alterada", outro_job)
                    while falha["status"] != "erro":
                        falha = await _do_job(etapas, "etapa-alterada", outro_job)
                    assert falha == {
                        "job_id": str(outro_job),
                        "etapa": "extracao_parametros",
                        "status": "erro",
                        "regra_id": str(regra),
                        "submissao_id": alheia["submissao_id"],
                    }
                    [linha] = await dono.fetch(
                        "SELECT p.id, p.no, p.conteudo AS prompt, r.conteudo AS resposta"
                        " FROM prompts p JOIN respostas_modelo r ON r.prompt_id = p.id"
                        " WHERE p.job_id = $1 AND p.id <> $2",
                        job,
                        prompt_da_extracao,
                    )
                    assert linha["no"] == "extracao_parametros"
                    enviado = simplejson.loads(linha["prompt"], use_decimal=True)
                    assert enviado["dados_nao_confiaveis_da_correcao"] == {"texto": TEXTO}
                    assert enviado["dados_do_sistema"]["conflitos"] == [
                        {"elementos": ["nucleo.percentual"], "motivo": "percentual ausente"},
                        {
                            "elementos": ["parametros.meta_venda"],
                            "motivo": "meta de venda citada sem valor reconhecido",
                        },
                    ]
                    assert simplejson.loads(linha["resposta"], use_decimal=True) == SAIDA
                    assert trilha["prompt_id"] == str(linha["id"])
                    assert trilha["regra_id"] == str(regra)
                    sem_prompt = "SELECT count(*) FROM prompts WHERE job_id=$1"
                    assert await dono.fetchval(sem_prompt, outro_job) == 0
                    async with asyncio.timeout(15):
                        while True:
                            fila = await canal.declare_queue("correcao-submetida", passive=True)
                            if fila.declaration_result.message_count == 0:
                                break
                            await asyncio.sleep(0.1)
                    depois = (await cliente.get("/metrics")).text
                    rotulos = {"job_name": "reextract_rule"}
                    for nome, delta in (
                        ("job_runs_total", 2),
                        ("job_failures_total", 1),
                        ("job_duration_seconds_count", 2),
                    ):
                        variacao = amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos)
                        assert variacao == delta
                    classe = {"classe": "regra_indisponivel"}
                    assert (
                        amostra(depois, "codegen_extracao_falhas_total", classe)
                        - amostra(antes, "codegen_extracao_falhas_total", classe)
                        == 1
                    )
                    assert len(modelo.seen_messages) == 1
        finally:
            await conexao.close()
    finally:
        await dono.close()
        await administrador.execute(f'DROP DATABASE "{banco}" WITH (FORCE)')
        await administrador.close()
