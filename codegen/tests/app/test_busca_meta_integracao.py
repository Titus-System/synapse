"""Busca real no broker e no Postgres; o teste representa somente o worker externo."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import simplejson
from aio_pika import Message
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.contratos.mensagens import SimulacaoConcluida
from app.graph import entrypoint
from app.graph.core.engine import build_graph
from app.mensageria.broker import EXCHANGE_SIMULACAO, ConexaoBroker, conectar
from app.mensageria.limpeza import LimpezaDeCheckpoints
from app.mensageria.roteamento import GraphRouter
from tests.app.extracao import banco_postgres
from tests.app.graph.test_indisponibilidade_do_provedor import amostra
from tests.app.test_rabbitmq_integracao import _ler, _proxima, rabbitmqctl

postgres_extracao = banco_postgres.postgres_extracao
pytestmark = [
    pytest.mark.rabbitmq,
    pytest.mark.postgres,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("RUN_RABBITMQ_INTEGRATION") != "1"
        or os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="Requer Docker e ambas as flags RUN_RABBITMQ_INTEGRATION/RUN_POSTGRES_INTEGRATION",
    ),
]


@pytest_asyncio.fixture(loop_scope="module")
async def broker() -> AsyncIterator[ConexaoBroker]:
    vhost = f"t273-{uuid4()}"
    config = Settings(RABBITMQ_VHOST=vhost)
    await asyncio.to_thread(rabbitmqctl, "add_vhost", vhost)
    try:
        await asyncio.to_thread(
            rabbitmqctl, "set_permissions", "-p", vhost, config.RABBITMQ_USER, ".*", ".*", ".*"
        )
        conexao = await conectar(config)
        try:
            yield conexao
        finally:
            await conexao.fechar()
    finally:
        await asyncio.to_thread(rabbitmqctl, "delete_vhost", vhost)


@pytest_asyncio.fixture(loop_scope="module")
async def cliente_busca(aplicacao: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=aplicacao), base_url="http://test"
    ) as client:
        yield client


class BancoBusca:
    def __init__(self, dono: Any, sessoes: async_sessionmaker[AsyncSession]) -> None:
        self.dono = dono
        self.sessoes = sessoes
        self.job, self.regra, self.codigo = uuid4(), uuid4(), uuid4()
        self.thread = f"{self.job}:{self.regra}"
        self.resultados: dict[UUID, tuple[Decimal | None, Decimal, str]] = {}

    async def preparar(self) -> None:
        usuario, prompt = uuid4(), uuid4()
        await self.dono.execute(
            "INSERT INTO usuarios(id,login,senha_hash,nome,papel,criado_em)"
            " VALUES($1,$2,'x','Teste','profissional_rh',now())",
            usuario,
            str(usuario),
        )
        await self.dono.execute(
            "INSERT INTO jobs(id,usuario_id,status,competencias,orcamento,criado_em)"
            " VALUES($1,$2,'simulando','{2025-11}',100,now())",
            self.job,
            usuario,
        )
        await self.dono.execute(
            "INSERT INTO regras(id,job_id,versao,origem,nucleo,especificacoes,hash,criada_em)"
            " VALUES($1,$2,1,'extracao','{\"percentual\":0.05}'::jsonb,'[]'::jsonb,$3,now())",
            self.regra,
            self.job,
            uuid4().hex * 2,
        )
        await self.dono.execute(
            "INSERT INTO prompts(id,job_id,no,conteudo,modelo,criado_em)"
            " VALUES($1,$2,'geracao_codigo','artefato de teste','{}'::jsonb,now())",
            prompt,
            self.job,
        )
        await self.dono.execute(
            "INSERT INTO codigos_gerados(id,job_id,regra_id,linguagem,fonte,prompt_id,criado_em)"
            " VALUES($1,$2,$3,'python','artefato de teste',$4,now())",
            self.codigo,
            self.job,
            self.regra,
            prompt,
        )

    async def resultado(
        self, meta: Decimal | None, custo: Decimal, proposito: str, status: str = "sucesso"
    ) -> dict[str, Any]:
        resultado = uuid4()
        totais = {
            "baseline": Decimal("50"),
            "simulado": custo,
            "orcamento": Decimal("100"),
            "vendas_historicas": Decimal("1000"),
            "diferenca_abs": custo - 50,
            "diferenca_pct": (custo - 50) / 50,
        }
        veredito = "viavel" if custo <= 100 else "inviavel"
        await self.dono.execute(
            "INSERT INTO resultados_simulacao(id,job_id,codigo_gerado_id,status,totais,veredito,"
            " assercoes,meta_venda,proposito,criado_em)"
            " VALUES($1,$2,$3,$4,$5::jsonb,$6,'[]'::jsonb,$7,$8,now())",
            resultado,
            self.job,
            self.codigo,
            status,
            simplejson.dumps(totais, use_decimal=True) if status == "sucesso" else None,
            veredito if status == "sucesso" else None,
            meta,
            proposito,
        )
        self.resultados[resultado] = (meta, custo, status)
        evento: dict[str, Any] = {
            "job_id": str(self.job),
            "resultado_id": str(resultado),
            "status": status,
            "proposito": proposito,
        }
        if meta is not None:
            evento["meta_venda"] = meta
        if status == "sucesso":
            evento["veredito"] = veredito
        return evento


@pytest_asyncio.fixture(loop_scope="module")
async def banco(
    postgres_extracao: tuple[int, Any], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[BancoBusca]:
    porta, dono = postgres_extracao
    url = f"postgresql://teste_codegen:teste-local@127.0.0.1:{porta}/postgres"
    engine = create_async_engine(
        url.replace("postgresql://", "postgresql+asyncpg://"), hide_parameters=True
    )
    sessoes = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def checkpoint() -> AsyncIterator[AsyncPostgresSaver]:
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            yield saver

    async with checkpoint() as saver:
        await saver.setup()
    monkeypatch.setattr(entrypoint, "get_checkpointer", checkpoint)
    monkeypatch.setattr(get_settings(), "BUSCA_META_ENABLED", True)
    banco = BancoBusca(dono, sessoes)
    await banco.preparar()
    try:
        yield banco
    finally:
        await engine.dispose()


async def iniciar(banco: BancoBusca, broker: ConexaoBroker) -> dict[str, Any]:
    original = await banco.resultado(None, Decimal("50"), "simulacao")
    config = {
        "configurable": {
            "thread_id": banco.thread,
            "sessoes": banco.sessoes,
            "producers": broker.producers,
        }
    }
    async with entrypoint.get_checkpointer() as saver:
        await build_graph(saver).aupdate_state(
            config,
            {
                "job_id": str(banco.job),
                "regra_id": str(banco.regra),
                "codigo_gerado_id": str(banco.codigo),
                "competencias": ["2025-11"],
                "orcamento": "100",
                "resultado_id": original["resultado_id"],
                "status_simulacao": "sucesso",
                "veredito": "viavel",
                "representacao_regra": {"nucleo": {"percentual": "0.05"}, "especificacoes": []},
            },
            as_node="await_execution",
        )
    return original


async def publicar_resultado(broker: ConexaoBroker, evento: dict[str, Any]) -> None:
    from tests.app.test_mensageria import oficial

    oficial("simulacao-concluida").validate(evento)
    fanout = await broker.canal.get_exchange(EXCHANGE_SIMULACAO)
    await fanout.publish(
        Message(body=simplejson.dumps(evento, use_decimal=True).encode()), routing_key=""
    )


@pytest.mark.parametrize(
    "modo", ["sucesso", "nao_monotonica", "intervalo_esgotado", "falha_execucao"]
)
async def test_busca_com_broker_banco_checkpoint_e_scrape_reais(
    banco: BancoBusca,
    broker: ConexaoBroker,
    modo: str,
    cliente_busca: AsyncClient,
) -> None:
    original = await iniciar(banco, broker)
    roteador = GraphRouter(banco.sessoes, broker.producers, LimpezaDeCheckpoints(banco.sessoes))
    await broker.iniciar_consumers(roteador)
    antes = (await cliente_busca.get("/metrics")).text
    await publicar_resultado(broker, original)
    historico = [original]
    candidatas = []
    # Cada retomada reabre a conexão do checkpointer: nenhuma depende de memória local.
    for indice in range(12):
        comando = await _ler(await _proxima(broker.filas["executar-codigo"]), "executar-codigo")
        candidatas.append(comando)
        assert comando["codigo_gerado_id"] == str(banco.codigo)
        assert comando["proposito"] == "busca_meta"
        assert comando["orcamento"] == 100 and comando["competencias"] == ["2025-11"]
        custo = {
            "sucesso": comando["meta_venda"] / 20,
            "nao_monotonica": Decimal("40"),
            "intervalo_esgotado": Decimal("50"),
            "falha_execucao": Decimal("0"),
        }[modo]
        evento = await banco.resultado(
            comando["meta_venda"],
            custo,
            "busca_meta",
            "erro_codigo" if modo == "falha_execucao" else "sucesso",
        )
        for antigo in historico:
            await publicar_resultado(broker, antigo)
        await publicar_resultado(broker, evento)
        historico.append(evento)
        # A função linear encontra 2000, dobra para delimitar e faz dez bisseções.
        if modo in ("nao_monotonica", "falha_execucao") or indice == 11:
            break
    sugerida = await _ler(
        await _proxima(broker.filas["meta-venda-sugerida"]), "meta-venda-sugerida"
    )
    if modo == "sucesso":
        meta, custo, status = banco.resultados[UUID(sugerida["resultado_id"])]
        assert sugerida["meta_venda"] == meta == 2000 and custo <= 100 and status == "sucesso"
    else:
        assert sugerida["sem_solucao"] == {"motivo": modo}
    # A conclusão de auditoria vem após a sugestão: esperá-la confirma que a publicação terminou.
    trilhas = [
        await _ler(await _proxima(broker.filas["no-concluido"]), "no-concluido") for _ in range(2)
    ]
    assert all(t["no"] == "decisao" for t in trilhas)
    assert trilhas[0]["evento_id"] != trilhas[1]["evento_id"]
    depois = (await cliente_busca.get("/metrics")).text
    rotulos = {
        "desfecho": "sugerida" if modo == "sucesso" else "sem_solucao",
        "motivo": "encontrada" if modo == "sucesso" else modo,
    }
    assert (
        amostra(depois, "codegen_busca_meta_total", rotulos)
        - amostra(antes, "codegen_busca_meta_total", rotulos)
        == 1
    )
    assert amostra(depois, "codegen_busca_meta_espera_seconds_count", {}) - amostra(
        antes, "codegen_busca_meta_espera_seconds_count", {}
    ) == len(candidatas)
    # A reentrega depois do fim também não publica outra candidata nem sugestão.
    await roteador.entregar(
        banco.job,
        SimulacaoConcluida.model_validate_json(simplejson.dumps(historico[-1], use_decimal=True)),
    )
    assert await broker.filas["executar-codigo"].get(fail=False) is None
    assert await broker.filas["meta-venda-sugerida"].get(fail=False) is None


async def test_duas_retomadas_concorrentes_publicam_uma_candidata(
    banco: BancoBusca, broker: ConexaoBroker
) -> None:
    original = await iniciar(banco, broker)
    kwargs = {"sessoes": banco.sessoes, "producers": broker.producers}
    await entrypoint.resume_to_completion(banco.thread, original, **kwargs)
    comando = await _ler(await _proxima(broker.filas["executar-codigo"]), "executar-codigo")
    resultado = await banco.resultado(comando["meta_venda"], Decimal("100"), "busca_meta")
    desfechos = await asyncio.gather(
        *[entrypoint.resume_to_completion(banco.thread, resultado, **kwargs) for _ in range(2)]
    )
    assert set(desfechos) == {entrypoint.ResumeOutcome.RESUMED, entrypoint.ResumeOutcome.IGNORED}
    await _ler(await _proxima(broker.filas["executar-codigo"]), "executar-codigo")
    assert await broker.filas["executar-codigo"].get(fail=False) is None
