"""
The graph's public interface - the only thing meant to be imported from outside `app/graph/`.
Everything under `app/graph/core/` is internal.
"""

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logger import get_logger
from app.graph.core.checkpointer import get_checkpointer
from app.graph.core.engine import AWAIT_EXECUTION, build_graph
from app.graph.core.state import AgentState
from app.mensageria.producers import Producers

logger = get_logger("app.graph.entrypoint")

type Grafo = CompiledStateGraph[AgentState, None, AgentState, AgentState]
type Entrada = AgentState | Command[Any] | None


class ResumeOutcome(StrEnum):
    """O que a retomada encontrou no checkpoint do job.

    Quem chama decide o que fazer com a mensagem: `NO_CHECKPOINT` é definitivo (o resultado é
    de um job que este serviço não conhece), `NOT_PAUSED_YET` é a corrida entre a publicação
    do worker e a gravação do checkpoint, e vale reentregar.
    """

    RESUMED = "resumed"
    NO_CHECKPOINT = "no_checkpoint"
    NOT_PAUSED_YET = "not_paused_yet"
    ALREADY_FINISHED = "already_finished"


def _config(
    thread_id: str, *, sessoes: async_sessionmaker[AsyncSession], producers: Producers
) -> RunnableConfig:
    return {
        "configurable": {
            "thread_id": thread_id,
            "sessoes": sessoes,
            "producers": producers,
        }
    }


async def _checkpoint_do_ciclo(
    graph: Grafo, config: RunnableConfig
) -> tuple[RunnableConfig, StateSnapshot]:
    estado = await graph.aget_state(config)
    job_id, separador, regra_id = config["configurable"]["thread_id"].partition(":")
    if estado.values or not separador:
        return config, estado

    anterior: RunnableConfig = {
        **config,
        "configurable": {**config["configurable"], "thread_id": job_id},
    }
    legado = await graph.aget_state(anterior)
    # Só o mesmo ciclo pode reutilizar um checkpoint gravado antes do versionamento.
    if legado.values.get("job_id") == job_id and legado.values.get("regra_id") == regra_id:
        return anterior, legado
    return config, estado


async def _consumir(
    graph: Grafo, entrada: Entrada, config: RunnableConfig
) -> AsyncIterator[tuple[str, Any]]:
    async for stream_mode, chunk in graph.astream(
        entrada, config, stream_mode=["updates", "custom"]
    ):
        if stream_mode == "updates" and isinstance(chunk, dict):
            for node_name, update in chunk.items():
                logger.info("graph node finished", extra={"node": node_name})
                yield node_name, update


async def run(
    thread_id: str,
    initial_state: AgentState,
    *,
    sessoes: async_sessionmaker[AsyncSession],
    producers: Producers,
) -> AsyncIterator[tuple[str, Any]]:
    """Run the graph on `thread_id`, yielding `(node_name, update)` as each node finishes.

    `thread_id` identifies the cycle, not the job: a job that adapts its rule runs the
    pipeline once per rule version, and each run needs a checkpoint of its own (see
    `app/mensageria/roteamento.py::thread_do_ciclo`). If a checkpoint already exists under
    it, the graph resumes from that point and `initial_state` is ignored; otherwise the
    graph starts fresh from it. When the run pauses, the last item is
    `("__interrupt__", ...)` carrying the `interrupt()` value, and the iteration ends.

    `sessoes` and `producers` reach every node through `config["configurable"]`, as agreed
    across T-094/T-096/T-097 - see `.agents/skills/graph/SKILL.md`.
    """
    config = _config(thread_id, sessoes=sessoes, producers=producers)

    async with get_checkpointer() as checkpointer:
        graph = build_graph(checkpointer)
        # LangGraph starts a new run from START for any non-None input, even on a thread that
        # already has checkpoints. `None` continues from the last one instead: after a
        # redelivery, the nodes that already finished (model call, inserts) do not run again.
        config, existing = await _checkpoint_do_ciclo(graph, config)
        graph_input = None if existing.values else initial_state
        async for item in _consumir(graph, graph_input, config):
            yield item


async def resume_to_completion(
    thread_id: str,
    valor: dict[str, Any],
    *,
    sessoes: async_sessionmaker[AsyncSession],
    producers: Producers,
) -> ResumeOutcome:
    """Hand `valor` to the pending `interrupt()` of `thread_id` and drive the rest of the run.

    `valor` carries references and control fields only; the simulation's numbers stay in the
    database (ADR-001). The checkpoint is inspected before resuming because the worker can
    publish its result before the paused checkpoint is written - see
    `docs/retomada-apos-execucao.md`.
    """
    config = _config(thread_id, sessoes=sessoes, producers=producers)

    async with get_checkpointer() as checkpointer:
        graph = build_graph(checkpointer)
        config, estado = await _checkpoint_do_ciclo(graph, config)
        if not estado.values:
            return ResumeOutcome.NO_CHECKPOINT
        if not estado.next:
            return ResumeOutcome.ALREADY_FINISHED
        if estado.values.get("resultado_id") == valor.get("resultado_id"):
            entrada: Entrada = None
        elif estado.next == (AWAIT_EXECUTION,):
            entrada = Command(resume=valor)
        else:
            return ResumeOutcome.NOT_PAUSED_YET

        async for _ in _consumir(graph, entrada, config):
            pass
        return ResumeOutcome.RESUMED


async def run_to_completion(
    thread_id: str,
    initial_state: AgentState,
    *,
    sessoes: async_sessionmaker[AsyncSession],
    producers: Producers,
) -> None:
    """Drive `run` until the graph finishes or pauses, discarding the per-node updates.

    Meant to be called from the message-router boundary, never directly from a message
    handler.
    """
    async for _ in run(thread_id, initial_state, sessoes=sessoes, producers=producers):
        pass
