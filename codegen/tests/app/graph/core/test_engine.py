import logging
from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.codigo_gerado import CodigoInvalidoError
from app.graph.core.engine import build_graph, route_after_greeting
from app.graph.core.state import AgentState
from app.prompts.geracao_codigo import montar_prompt_geracao
from app.representacao_regra import RepresentacaoRegra
from tests.app.banco_falso import BancoFalso
from tests.app.graph.conftest import FakeChatModel

ScriptedModel = Callable[[Iterable[AIMessage]], FakeChatModel]

_REGRA = RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": []})


def test_build_graph_registers_greeting_but_leaves_it_out_of_the_run() -> None:
    graph = build_graph(InMemorySaver())

    drawable = graph.get_graph()
    assert set(drawable.nodes) == {
        "__start__",
        "greeting",
        "tools",
        "load_rule",
        "code_generation",
        "persist_response",
        "extract_code",
        "dispatch_execution",
        "await_execution",
        "__end__",
    }
    edges = {(edge.source, edge.target) for edge in drawable.edges}
    assert edges == {
        ("__start__", "load_rule"),
        ("load_rule", "code_generation"),
        ("code_generation", "persist_response"),
        ("persist_response", "extract_code"),
        ("extract_code", "dispatch_execution"),
        ("dispatch_execution", "await_execution"),
        ("await_execution", "__end__"),
    }


def test_routes_to_tools_when_the_last_message_requested_a_tool_call() -> None:
    state: AgentState = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "say_hello", "args": {"name": "x"}, "id": "call_1"}],
            )
        ]
    }

    assert route_after_greeting(state) == "continue"


def test_routes_on_when_the_last_message_has_no_tool_call() -> None:
    state: AgentState = {"messages": [AIMessage(content="Hello x")]}

    assert route_after_greeting(state) == "done"


def test_routes_on_when_there_are_no_messages_yet() -> None:
    assert route_after_greeting({}) == "done"


JOB_ID = "d9cf3b9e-c99e-4c1e-9f9e-2e6e3a5b0a11"
REGRA_ID = "d9cf3b9e-c99e-4c1e-9f9e-2e6e3a5b0a12"
FONTE = "def aplicar_regra(bases, apuracao_base, competencias):\n    return {}\n"
RESPOSTA_VALIDA = f"```python\n{FONTE}```"
CONFIG: RunnableConfig = {"configurable": {"thread_id": JOB_ID}}


class _Execucao:
    """One graph wired with in-memory checkpoints, database and producers."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, banco: BancoFalso | None = None) -> None:
        monkeypatch.setattr(
            "app.graph.nodes.load_rule.buscar_regra", AsyncMock(return_value=_REGRA)
        )
        self.banco = banco or BancoFalso()
        self.producers = MagicMock(executar_codigo=AsyncMock())
        self.graph: CompiledStateGraph[AgentState, None, AgentState, AgentState] = build_graph(
            InMemorySaver()
        )
        self.config: RunnableConfig = {
            "configurable": {
                "thread_id": JOB_ID,
                "sessoes": self.banco,
                "producers": self.producers,
            }
        }

    async def iniciar(self) -> Any:
        initial_state: AgentState = {
            "job_id": JOB_ID,
            "regra_id": REGRA_ID,
            "competencias": ["2025-08", "2025-11"],
            "orcamento": "485000.00",
        }
        return await self.graph.ainvoke(initial_state, self.config)

    async def continuar(self) -> Any:
        """What `entrypoint.run` does on a redelivery: continue from the last checkpoint."""
        return await self.graph.ainvoke(None, self.config)

    async def retomar(self) -> Any:
        return await self.graph.ainvoke(Command(resume={"status": "concluida"}), self.config)


async def test_graph_records_the_artifacts_publishes_and_pauses(
    scripted_model: ScriptedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_model([AIMessage(content=RESPOSTA_VALIDA)])
    execucao = _Execucao(monkeypatch)

    await execucao.iniciar()

    [prompt] = execucao.banco.tabela("prompts")
    [resposta] = execucao.banco.tabela("respostas_modelo")
    [codigo] = execucao.banco.tabela("codigos_gerados")
    assert resposta["prompt_id"] == prompt["id"]
    assert codigo["prompt_id"] == prompt["id"]
    assert codigo["regra_id"] == UUID(REGRA_ID)
    assert codigo["fonte"] == FONTE
    [comando] = execucao.producers.executar_codigo.await_args.args
    assert comando.codigo_gerado_id == codigo["id"]
    assert comando.competencias == ["2025-08", "2025-11"]
    assert comando.orcamento == Decimal("485000.00")
    assert FONTE not in comando.model_dump_json()
    estado = await execucao.graph.aget_state(execucao.config)
    assert estado.next == ("await_execution",)
    assert estado.tasks[0].interrupts[0].value == {
        "job_id": JOB_ID,
        "codigo_gerado_id": str(codigo["id"]),
    }


async def test_resuming_the_paused_graph_does_not_publish_again(
    scripted_model: ScriptedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_model([AIMessage(content=RESPOSTA_VALIDA)])
    execucao = _Execucao(monkeypatch)
    await execucao.iniciar()

    await execucao.retomar()

    execucao.producers.executar_codigo.assert_awaited_once()
    assert (await execucao.graph.aget_state(execucao.config)).next == ()


async def test_an_invalid_reply_stays_recorded_and_nothing_is_published(
    scripted_model: ScriptedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_model([AIMessage(content="```python\nnão é python(\n```")])
    execucao = _Execucao(monkeypatch)

    with pytest.raises(CodigoInvalidoError):
        await execucao.iniciar()

    assert len(execucao.banco.tabela("respostas_modelo")) == 1
    assert execucao.banco.tabela("codigos_gerados") == []
    execucao.producers.executar_codigo.assert_not_awaited()


async def test_a_failure_recording_the_code_publishes_nothing(
    scripted_model: ScriptedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_model([AIMessage(content=RESPOSTA_VALIDA)])
    execucao = _Execucao(monkeypatch, BancoFalso(falhar_em=("codigos_gerados",)))

    with pytest.raises(RuntimeError):
        await execucao.iniciar()

    execucao.producers.executar_codigo.assert_not_awaited()


async def test_a_failure_publishing_keeps_the_recorded_code(
    scripted_model: ScriptedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_model([AIMessage(content=RESPOSTA_VALIDA)])
    execucao = _Execucao(monkeypatch)
    execucao.producers.executar_codigo.side_effect = RuntimeError("broker down")

    with pytest.raises(RuntimeError):
        await execucao.iniciar()

    assert len(execucao.banco.tabela("codigos_gerados")) == 1


async def test_a_redelivery_after_a_failed_publish_reuses_the_recorded_rows(
    scripted_model: ScriptedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted_model([AIMessage(content=RESPOSTA_VALIDA)])
    execucao = _Execucao(monkeypatch)
    execucao.producers.executar_codigo.side_effect = [RuntimeError("broker down"), None]
    with pytest.raises(RuntimeError):
        await execucao.iniciar()

    await execucao.continuar()

    assert len(execucao.banco.tabela("prompts")) == 1
    assert len(execucao.banco.tabela("codigos_gerados")) == 1
    primeiro, segundo = execucao.producers.executar_codigo.await_args_list
    assert primeiro.args[0].codigo_gerado_id == segundo.args[0].codigo_gerado_id


async def test_no_node_logs_the_prompt_the_reply_or_the_code(
    scripted_model: ScriptedModel,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    scripted_model([AIMessage(content=RESPOSTA_VALIDA)])
    execucao = _Execucao(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger="app"):
        await execucao.iniciar()

    assert caplog.records
    registros = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "aplicar_regra" not in registros
    assert montar_prompt_geracao(_REGRA)[:200] not in registros


async def test_a_rejected_reply_is_not_logged(
    scripted_model: ScriptedModel,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    scripted_model([AIMessage(content="```python\nsegredo_da_resposta(\n```")])
    execucao = _Execucao(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger="app"), pytest.raises(CodigoInvalidoError):
        await execucao.iniciar()

    assert any(r.getMessage() == "generated code rejected" for r in caplog.records)
    registros = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "segredo_da_resposta" not in registros
