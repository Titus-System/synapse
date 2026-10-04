"""A limpeza dos checkpoints contra o Postgres real do compose (T-207).

Os checkpoints são os do `AsyncPostgresSaver` de verdade, gravados por um grafo reduzido que
reaproveita o nó real `await_execution`: o que está em jogo é o que fica nas tabelas do
LangGraph, a identidade das threads (`job_id:regra_id` e o legado `job_id`) e o registro em
`jobs_grafo_encerrados`, que precisa das migrations da `api` (changeset 017). O grafo completo,
com o modelo e as gravações de artefatos, tem os seus próprios testes.

Pedem o compose de pé e são pulados sem `RUN_POSTGRES_INTEGRATION=1`; habilitados, a ausência do
banco é falha, nunca aprovação simulada. O dono do schema semeia e apaga o que o codegen não pode
apagar: o job, para a chave estrangeira, e a linha de controle.
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph
from prometheus_client import REGISTRY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.contratos.mensagens import (
    JobEncerrado,
    OrigemJob,
    RegraSubmetida,
    SimulacaoConcluida,
    StatusSimulacao,
    StatusTerminal,
    Veredito,
)
from app.db import criar_engine, criar_sessionmaker
from app.falhas import FalhaDoJobError
from app.graph import entrypoint
from app.graph.core.state import AgentState
from app.graph.entrypoint import ResumeOutcome
from app.graph.nodes.await_execution import await_execution
from app.mensageria import limpeza as modulo_limpeza
from app.mensageria import roteamento
from app.mensageria.limpeza import LimpezaDeCheckpoints, ResultadoDaLimpeza
from app.mensageria.roteamento import GraphRouter, JobEncerradoError

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="Requer o Postgres do deploy/docker-compose.yml migrado; RUN_POSTGRES_INTEGRATION=1",
    ),
]

# Marcador no estado do grafo: o conteúdo do checkpoint não pode chegar a um log.
CONTEUDO_DO_CHECKPOINT = "CONTEUDO-DO-CHECKPOINT"


class FalhaNaDecisaoError(FalhaDoJobError):
    etapa = "decisao"


class FalhaNaGeracaoError(FalhaDoJobError):
    etapa = "geracao_codigo"


class Grafo:
    """O que os nós do grafo reduzido fizeram, e onde cada um deve falhar."""

    def __init__(self) -> None:
        self.geracoes: list[str] = []
        self.decisoes: list[str] = []
        self.falhar_na_geracao: set[str] = set()
        self.falhar_na_decisao: set[str] = set()


@pytest.fixture
def grafo(monkeypatch: pytest.MonkeyPatch) -> Grafo:
    registro = Grafo()

    async def gerar(state: AgentState) -> AgentState:
        if state["regra_id"] in registro.falhar_na_geracao:
            raise FalhaNaGeracaoError("geração falhou")
        registro.geracoes.append(state["regra_id"])
        return {"codigo_gerado_id": str(uuid4()), "orcamento": CONTEUDO_DO_CHECKPOINT}

    async def decidir(state: AgentState) -> AgentState:
        if state["regra_id"] in registro.falhar_na_decisao:
            raise FalhaNaDecisaoError("decisão falhou")
        registro.decisoes.append(state["resultado_id"])
        return {}

    def construir(checkpointer: Any) -> Any:
        grafo = StateGraph(AgentState)
        grafo.add_node("generate", gerar)
        grafo.add_node("await_execution", await_execution)
        grafo.add_node("decide", decidir)
        grafo.add_edge(START, "generate")
        grafo.add_edge("generate", "await_execution")
        grafo.add_edge("await_execution", "decide")
        grafo.add_edge("decide", END)
        return grafo.compile(checkpointer=checkpointer)

    monkeypatch.setattr(entrypoint, "build_graph", construir)
    return registro


@pytest.fixture
async def sessoes(configuracoes: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = criar_engine(configuracoes)
    try:
        yield criar_sessionmaker(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def dono(configuracoes: Settings) -> AsyncIterator[Any]:
    conexao = await asyncpg.connect(
        host=configuracoes.POSTGRES_HOST,
        port=configuracoes.POSTGRES_PORT,
        database=configuracoes.POSTGRES_DB,
        user=os.environ.get("POSTGRES_OWNER_USER", "postgres"),
        password=os.environ.get("POSTGRES_OWNER_PASSWORD", "postgres"),
    )
    try:
        yield conexao
    finally:
        await conexao.close()


@pytest.fixture
async def novo_job(dono: Any) -> AsyncIterator[Callable[[], Any]]:
    """Cria jobs reais (a chave estrangeira do registro exige) e apaga tudo deles no fim."""
    usuario_id = uuid4()
    await dono.execute(
        "INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)"
        " VALUES ($1, $2, 'x', 'Teste', 'profissional_rh', now())",
        usuario_id,
        f"teste-limpeza-{usuario_id}",
    )
    criados: list[UUID] = []

    async def criar() -> UUID:
        job_id = uuid4()
        await dono.execute(
            "INSERT INTO jobs (id, status, usuario_id, competencias, orcamento, criado_em)"
            " VALUES ($1, 'gerando_regra', $2, '{2025-11}', 1000, now())",
            job_id,
            usuario_id,
        )
        criados.append(job_id)
        return job_id

    try:
        yield criar
    finally:
        for job_id in criados:
            for tabela in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
                await dono.execute(
                    f"DELETE FROM {tabela} WHERE thread_id = $1 OR thread_id LIKE $2",
                    str(job_id),
                    f"{job_id}:%",
                )
            await dono.execute("DELETE FROM jobs_grafo_encerrados WHERE job_id = $1", job_id)
            await dono.execute("DELETE FROM jobs WHERE id = $1", job_id)
        await dono.execute("DELETE FROM usuarios WHERE id = $1", usuario_id)


async def linhas_do_job(dono: Any, job_id: UUID) -> dict[str, int]:
    contagem: dict[str, int] = {}
    for tabela in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
        contagem[tabela] = await dono.fetchval(
            f"SELECT count(*) FROM {tabela} WHERE thread_id = $1 OR thread_id LIKE $2",
            str(job_id),
            f"{job_id}:%",
        )
    return contagem


async def limpo_em(dono: Any, job_id: UUID) -> datetime | None:
    valor: datetime | None = await dono.fetchval(
        "SELECT limpo_em FROM jobs_grafo_encerrados WHERE job_id = $1", job_id
    )
    return valor


def encerramento(job_id: UUID) -> JobEncerrado:
    return JobEncerrado(
        evento_id=uuid4(),
        job_id=job_id,
        status=StatusTerminal.CANCELADO,
        encerrado_em=datetime.now(UTC),
    )


def resultado(job_id: UUID) -> SimulacaoConcluida:
    return SimulacaoConcluida(
        job_id=job_id,
        resultado_id=uuid4(),
        status=StatusSimulacao.SUCESSO,
        veredito=Veredito.VIAVEL,
    )


def submissao(job_id: UUID, regra_id: UUID) -> RegraSubmetida:
    return RegraSubmetida(
        job_id=job_id,
        regra_id=regra_id,
        origem=OrigemJob.FORMULARIO,
        competencias=["2025-11"],
        submissao_id=uuid4(),
    )


async def pausar(thread_id: str, job_id: UUID, regra_id: UUID) -> None:
    """Roda o ciclo até a pausa à espera do resultado do worker."""
    await entrypoint.run_to_completion(
        thread_id,
        {"job_id": str(job_id), "regra_id": str(regra_id)},
        sessoes=MagicMock(),
        producers=MagicMock(),
    )


async def concluir(thread_id: str) -> ResumeOutcome:
    """Entrega o resultado ao ciclo pausado e o leva até o fim."""
    return await entrypoint.resume_to_completion(
        thread_id,
        {"resultado_id": str(uuid4()), "status": "sucesso", "veredito": "viavel"},
        sessoes=MagicMock(),
        producers=MagicMock(),
    )


def roteador_para(
    sessoes: async_sessionmaker[AsyncSession],
    limpeza: LimpezaDeCheckpoints,
    monkeypatch: pytest.MonkeyPatch,
    regra_id: UUID,
) -> GraphRouter:
    """O roteador real; só a busca da versão da regra pelo resultado é trocada."""
    monkeypatch.setattr(roteamento, "buscar_regra_do_resultado", AsyncMock(return_value=regra_id))
    return GraphRouter(
        sessoes=sessoes, producers=MagicMock(etapa_alterada=AsyncMock()), limpeza=limpeza
    )


def amostra(resultado: str) -> float:
    return REGISTRY.get_sample_value("checkpoint_limpezas_total", {"resultado": resultado}) or 0.0


# ---- remoção e preservação ----


async def test_remove_os_ciclos_de_todas_as_versoes_e_do_legado_e_preserva_outro_job(
    grafo: Grafo,
    sessoes: async_sessionmaker[AsyncSession],
    dono: Any,
    novo_job: Callable[[], Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    job_id, outro_job = await novo_job(), await novo_job()
    regra_legada, regra, alternativa, regra_falha = uuid4(), uuid4(), uuid4(), uuid4()
    # O ciclo legado (de outra versão: o da mesma versão seria reaproveitado pelo versionado), o
    # versionado concluído, a alternativa que falhou antes da execução e, noutro job, um ciclo
    # pausado.
    await pausar(str(job_id), job_id, regra_legada)
    await concluir(str(job_id))
    await pausar(f"{job_id}:{regra}", job_id, regra)
    await concluir(f"{job_id}:{regra}")
    grafo.falhar_na_geracao.add(str(regra_falha))
    with pytest.raises(FalhaNaGeracaoError):
        await pausar(f"{job_id}:{regra_falha}", job_id, regra_falha)
    await pausar(f"{outro_job}:{alternativa}", outro_job, alternativa)
    preservado = await linhas_do_job(dono, outro_job)
    concluidas_antes = amostra("concluida")
    caplog.set_level(logging.INFO)

    await LimpezaDeCheckpoints(sessoes).registrar(encerramento(job_id))

    assert await linhas_do_job(dono, job_id) == {
        "checkpoints": 0,
        "checkpoint_writes": 0,
        "checkpoint_blobs": 0,
    }
    assert await linhas_do_job(dono, outro_job) == preservado
    assert await limpo_em(dono, job_id) is not None
    assert amostra("concluida") == concluidas_antes + 1
    concluida = next(
        r for r in caplog.records if r.getMessage() == "limpeza de checkpoints concluída"
    )
    assert concluida.ciclos_removidos == 3  # type: ignore[attr-defined]
    assert CONTEUDO_DO_CHECKPOINT not in caplog.text
    assert await dono.fetchval("SELECT count(*) FROM checkpoint_migrations") > 0


async def test_job_nao_encerrado_mantem_os_checkpoints_e_e_retomado_depois_de_reiniciar(
    grafo: Grafo,
    configuracoes: Settings,
    dono: Any,
    novo_job: Callable[[], Any],
) -> None:
    job_id, regra = await novo_job(), uuid4()
    await pausar(f"{job_id}:{regra}", job_id, regra)
    antes = await linhas_do_job(dono, job_id)

    # Um "reinício": engine e limpeza novos, e a retomada da subida.
    engine = criar_engine(configuracoes)
    try:
        limpeza = LimpezaDeCheckpoints(criar_sessionmaker(engine))
        await limpeza.retomar_pendentes()
        assert await limpeza.limpar(job_id) is None
    finally:
        await engine.dispose()

    assert await linhas_do_job(dono, job_id) == antes
    assert await concluir(f"{job_id}:{regra}") is ResumeOutcome.RESUMED
    assert len(grafo.decisoes) == 1


# ---- o que ainda falta acontecer ----


async def test_encerramento_antes_do_resultado_espera_o_resultado_e_so_entao_limpa(
    grafo: Grafo,
    sessoes: async_sessionmaker[AsyncSession],
    dono: Any,
    novo_job: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id, regra = await novo_job(), uuid4()
    await pausar(f"{job_id}:{regra}", job_id, regra)
    limpeza = LimpezaDeCheckpoints(sessoes)

    await limpeza.registrar(encerramento(job_id))

    assert (await linhas_do_job(dono, job_id))["checkpoints"] > 0, "o ciclo esperava o resultado"
    assert await limpo_em(dono, job_id) is None

    await roteador_para(sessoes, limpeza, monkeypatch, regra).entregar(job_id, resultado(job_id))

    assert len(grafo.decisoes) == 1, "o resultado de um job encerrado ainda é processado"
    assert (await linhas_do_job(dono, job_id))["checkpoints"] == 0
    assert await limpo_em(dono, job_id) is not None


async def test_limpeza_nao_corre_junto_com_o_processamento_do_job(
    grafo: Grafo,
    sessoes: async_sessionmaker[AsyncSession],
    dono: Any,
    novo_job: Callable[[], Any],
) -> None:
    job_id, regra = await novo_job(), uuid4()
    await pausar(f"{job_id}:{regra}", job_id, regra)
    await concluir(f"{job_id}:{regra}")
    limpeza = LimpezaDeCheckpoints(sessoes)

    async with limpeza.durante_o_processamento(job_id):
        await limpeza.registrar(encerramento(job_id))
        assert await limpeza.limpar(job_id) is ResultadoDaLimpeza.ADIADA
        assert (await linhas_do_job(dono, job_id))["checkpoints"] > 0

    await limpeza.retomar_pendentes()

    assert (await linhas_do_job(dono, job_id))["checkpoints"] == 0
    assert await limpo_em(dono, job_id) is not None


async def test_retomada_que_falhou_de_vez_libera_o_ciclo_para_a_limpeza(
    grafo: Grafo,
    sessoes: async_sessionmaker[AsyncSession],
    dono: Any,
    novo_job: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mensagem é rejeitada sem reentrega: nada mais retoma o ciclo que ficou no meio."""
    job_id, regra = await novo_job(), uuid4()
    await pausar(f"{job_id}:{regra}", job_id, regra)
    limpeza = LimpezaDeCheckpoints(sessoes)
    await limpeza.registrar(encerramento(job_id))
    grafo.falhar_na_decisao.add(str(regra))

    with pytest.raises(FalhaNaDecisaoError):
        await roteador_para(sessoes, limpeza, monkeypatch, regra).entregar(
            job_id, resultado(job_id)
        )

    assert (await linhas_do_job(dono, job_id))["checkpoints"] == 0
    assert await limpo_em(dono, job_id) is not None


# ---- recuperação ----


async def test_falha_no_meio_da_remocao_e_terminada_pela_retomada_da_subida(
    grafo: Grafo,
    sessoes: async_sessionmaker[AsyncSession],
    dono: Any,
    novo_job: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    job_id, regra, alternativa = await novo_job(), uuid4(), uuid4()
    for regra_do_ciclo in (regra, alternativa):
        await pausar(f"{job_id}:{regra_do_ciclo}", job_id, regra_do_ciclo)
        await concluir(f"{job_id}:{regra_do_ciclo}")
    apagar_de_verdade = modulo_limpeza.apagar_ciclos

    async def apagar_um_e_cair(thread_ids: Any) -> None:
        await apagar_de_verdade(list(thread_ids)[:1])
        raise ConnectionError("a conexão caiu no meio")

    monkeypatch.setattr(modulo_limpeza, "apagar_ciclos", apagar_um_e_cair)
    falhas_antes = amostra("falhou")
    caplog.set_level(logging.INFO)

    await LimpezaDeCheckpoints(sessoes).registrar(encerramento(job_id))

    assert await limpo_em(dono, job_id) is None, "limpo_em só aparece quando a limpeza termina"
    assert (await linhas_do_job(dono, job_id))["checkpoints"] > 0
    assert amostra("falhou") == falhas_antes + 1
    falha = next(r for r in caplog.records if r.getMessage() == "limpeza de checkpoints falhou")
    assert falha.causa == "ConnectionError"  # type: ignore[attr-defined]
    assert "a conexão caiu" not in caplog.text

    monkeypatch.setattr(modulo_limpeza, "apagar_ciclos", apagar_de_verdade)
    await LimpezaDeCheckpoints(sessoes).retomar_pendentes()

    assert (await linhas_do_job(dono, job_id))["checkpoints"] == 0
    assert await limpo_em(dono, job_id) is not None


# ---- reentregas depois da limpeza ----


async def test_reentregas_depois_da_limpeza_nao_recomecam_nada(
    grafo: Grafo,
    sessoes: async_sessionmaker[AsyncSession],
    dono: Any,
    novo_job: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id, regra = await novo_job(), uuid4()
    await pausar(f"{job_id}:{regra}", job_id, regra)
    await concluir(f"{job_id}:{regra}")
    limpeza = LimpezaDeCheckpoints(sessoes)
    evento = encerramento(job_id)
    await limpeza.registrar(evento)
    marcado = await limpo_em(dono, job_id)
    roteador = roteador_para(sessoes, limpeza, monkeypatch, regra)
    geracoes, decisoes = list(grafo.geracoes), list(grafo.decisoes)

    with pytest.raises(JobEncerradoError):
        await roteador.entregar(job_id, submissao(job_id, regra))
    with pytest.raises(JobEncerradoError):
        await roteador.entregar(job_id, resultado(job_id))
    await roteador.entregar(job_id, evento)

    assert (grafo.geracoes, grafo.decisoes) == (geracoes, decisoes)
    assert await linhas_do_job(dono, job_id) == {
        "checkpoints": 0,
        "checkpoint_writes": 0,
        "checkpoint_blobs": 0,
    }
    assert await limpo_em(dono, job_id) == marcado
    roteador.producers.etapa_alterada.assert_not_awaited()  # type: ignore[union-attr]


async def test_um_job_novo_nao_e_bloqueado_pelo_encerramento_de_outro(
    grafo: Grafo,
    sessoes: async_sessionmaker[AsyncSession],
    novo_job: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reprocessar cria outro job: o registro do anterior não fala por ele."""
    anterior, novo, regra = await novo_job(), await novo_job(), uuid4()
    limpeza = LimpezaDeCheckpoints(sessoes)
    await limpeza.registrar(encerramento(anterior))

    await roteador_para(sessoes, limpeza, monkeypatch, regra).entregar(novo, submissao(novo, regra))

    assert grafo.geracoes == [str(regra)]


async def test_as_metricas_da_limpeza_aparecem_no_metrics(
    grafo: Grafo,
    sessoes: async_sessionmaker[AsyncSession],
    novo_job: Callable[[], Any],
) -> None:
    from app.main import criar_aplicacao

    job_id, regra = await novo_job(), uuid4()
    await pausar(f"{job_id}:{regra}", job_id, regra)
    await concluir(f"{job_id}:{regra}")
    await LimpezaDeCheckpoints(sessoes).registrar(encerramento(job_id))

    aplicacao = criar_aplicacao()
    async with AsyncClient(transport=ASGITransport(app=aplicacao), base_url="http://t") as cliente:
        resposta = await cliente.get("/metrics")

    assert 'checkpoint_limpezas_total{resultado="concluida"}' in resposta.text
    assert 'checkpoint_limpeza_duracao_seconds_count{resultado="concluida"}' in resposta.text


async def test_encerramentos_concorrentes_do_mesmo_job_limpam_uma_vez(
    grafo: Grafo,
    sessoes: async_sessionmaker[AsyncSession],
    dono: Any,
    novo_job: Callable[[], Any],
) -> None:
    """Duas entregas do mesmo evento ao mesmo tempo: uma linha, uma limpeza concluída."""
    job_id, regra = await novo_job(), uuid4()
    await pausar(f"{job_id}:{regra}", job_id, regra)
    await concluir(f"{job_id}:{regra}")
    evento = encerramento(job_id)

    await asyncio.gather(
        LimpezaDeCheckpoints(sessoes).registrar(evento),
        LimpezaDeCheckpoints(sessoes).registrar(evento),
    )

    assert (
        await dono.fetchval("SELECT count(*) FROM jobs_grafo_encerrados WHERE job_id = $1", job_id)
        == 1
    )
    assert (await linhas_do_job(dono, job_id))["checkpoints"] == 0
    assert await limpo_em(dono, job_id) is not None
