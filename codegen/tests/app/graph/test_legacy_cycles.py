from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.contratos.mensagens import (
    OrigemJob,
    RegraSubmetida,
    SimulacaoConcluida,
    StatusSimulacao,
    Veredito,
)
from app.graph import entrypoint
from app.graph.core.state import AgentState
from app.graph.nodes.await_execution import await_execution
from app.mensageria import roteamento
from app.mensageria.roteamento import GraphRouter, JobDesconhecidoError

JOB_ID = uuid4()
REGRA_ID = uuid4()
RESULTADO_ID = uuid4()


@pytest.fixture
def ciclos(monkeypatch: pytest.MonkeyPatch) -> tuple[InMemorySaver, list[str], list[str]]:
    saver = InMemorySaver()
    geracoes: list[str] = []
    resultados: list[str] = []

    @asynccontextmanager
    async def checkpointer() -> AsyncIterator[InMemorySaver]:
        yield saver

    async def gerar(state: AgentState) -> AgentState:
        geracoes.append(state["regra_id"])
        return {"codigo_gerado_id": str(uuid4())}

    async def decidir(state: AgentState) -> AgentState:
        resultados.append(state["resultado_id"])
        return {}

    def build(checkpointer: Any) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("generate", gerar)
        graph.add_node("await_execution", await_execution)
        graph.add_node("decide", decidir)
        graph.add_edge(START, "generate")
        graph.add_edge("generate", "await_execution")
        graph.add_edge("await_execution", "decide")
        graph.add_edge("decide", END)
        return graph.compile(checkpointer=checkpointer)

    monkeypatch.setattr(entrypoint, "get_checkpointer", checkpointer)
    monkeypatch.setattr(entrypoint, "build_graph", build)
    monkeypatch.setattr(roteamento, "buscar_regra_do_resultado", AsyncMock(return_value=REGRA_ID))
    return saver, geracoes, resultados


async def iniciar_antigo(regra_id: str = str(REGRA_ID)) -> None:
    await entrypoint.run_to_completion(
        str(JOB_ID),
        {"job_id": str(JOB_ID), "regra_id": regra_id},
        sessoes=MagicMock(),
        producers=MagicMock(),
    )


def submissao(regra_id: UUID = REGRA_ID) -> RegraSubmetida:
    return RegraSubmetida(
        job_id=JOB_ID,
        regra_id=regra_id,
        origem=OrigemJob.FORMULARIO,
        competencias=["2025-11"],
        submissao_id=uuid4(),
    )


def resultado() -> SimulacaoConcluida:
    return SimulacaoConcluida(
        job_id=JOB_ID,
        resultado_id=RESULTADO_ID,
        status=StatusSimulacao.SUCESSO,
        veredito=Veredito.VIAVEL,
    )


async def test_resultado_retoma_checkpoint_anterior_sem_repetir_geracao(ciclos: Any) -> None:
    saver, geracoes, resultados = ciclos
    await iniciar_antigo()
    router = GraphRouter(sessoes=MagicMock(), producers=MagicMock())

    await router.entregar(JOB_ID, resultado())
    await router.entregar(JOB_ID, resultado())

    assert geracoes == [str(REGRA_ID)]
    assert resultados == [str(RESULTADO_ID)]
    assert saver.get_tuple({"configurable": {"thread_id": f"{JOB_ID}:{REGRA_ID}"}}) is None


@pytest.mark.parametrize("concluido", [False, True])
async def test_reentrega_da_submissao_reutiliza_checkpoint_anterior(
    ciclos: Any, concluido: bool
) -> None:
    saver, geracoes, _ = ciclos
    await iniciar_antigo()
    if concluido:
        await entrypoint.resume_to_completion(
            str(JOB_ID),
            {"resultado_id": str(RESULTADO_ID), "status": "sucesso"},
            sessoes=MagicMock(),
            producers=MagicMock(),
        )
    router = GraphRouter(sessoes=MagicMock(), producers=MagicMock())

    await router.entregar(JOB_ID, submissao())

    assert geracoes == [str(REGRA_ID)]
    assert saver.get_tuple({"configurable": {"thread_id": f"{JOB_ID}:{REGRA_ID}"}}) is None


async def test_sugestao_tem_checkpoint_proprio_sem_sobrescrever_o_original(ciclos: Any) -> None:
    saver, geracoes, _ = ciclos
    await iniciar_antigo()
    alternativa = uuid4()
    router = GraphRouter(sessoes=MagicMock(), producers=MagicMock())

    await router.entregar(JOB_ID, submissao(alternativa))
    await router.entregar(JOB_ID, submissao(alternativa))

    assert geracoes == [str(REGRA_ID), str(alternativa)]
    original = saver.get_tuple({"configurable": {"thread_id": str(JOB_ID)}})
    assert original is not None
    assert original.checkpoint["channel_values"]["regra_id"] == str(REGRA_ID)
    assert saver.get_tuple({"configurable": {"thread_id": f"{JOB_ID}:{alternativa}"}}) is not None


async def test_resultado_nao_retoma_checkpoint_de_outra_regra(ciclos: Any) -> None:
    _, _, resultados = ciclos
    await iniciar_antigo(str(uuid4()))
    router = GraphRouter(sessoes=MagicMock(), producers=MagicMock())

    with pytest.raises(JobDesconhecidoError):
        await router.entregar(JOB_ID, resultado())

    assert resultados == []


async def test_checkpoint_versionado_existente_tem_prioridade_sobre_o_legado(ciclos: Any) -> None:
    _, geracoes, resultados = ciclos
    await iniciar_antigo()
    thread_id = f"{JOB_ID}:{REGRA_ID}"
    # Um ciclo já gravado no formato novo deve ser retomado no mesmo lugar.
    graph = entrypoint.build_graph(ciclos[0])
    await graph.ainvoke(
        {"job_id": str(JOB_ID), "regra_id": str(REGRA_ID)},
        {"configurable": {"thread_id": thread_id}},
    )
    router = GraphRouter(sessoes=MagicMock(), producers=MagicMock())

    await router.entregar(JOB_ID, resultado())

    assert resultados == [str(RESULTADO_ID)]
    assert len(geracoes) == 2
    assert (await graph.aget_state({"configurable": {"thread_id": thread_id}})).next == ()
    assert (await graph.aget_state({"configurable": {"thread_id": str(JOB_ID)}})).next == (
        "await_execution",
    )


async def test_checkpoint_legado_exige_job_e_regra_corretos(ciclos: Any) -> None:
    _, _, resultados = ciclos
    await entrypoint.run_to_completion(
        str(JOB_ID),
        {"job_id": str(uuid4()), "regra_id": str(REGRA_ID)},
        sessoes=MagicMock(),
        producers=MagicMock(),
    )
    router = GraphRouter(sessoes=MagicMock(), producers=MagicMock())

    with pytest.raises(JobDesconhecidoError):
        await router.entregar(JOB_ID, resultado())

    assert resultados == []
