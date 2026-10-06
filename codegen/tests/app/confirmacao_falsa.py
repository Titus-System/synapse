"""Fronteiras externas falsas; consumer, roteador, entrypoint e nós são os reais."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
import simplejson
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import StateSnapshot

from app.contratos.mensagens import ModeloContrato, ParametrosConfirmados
from app.contratos.serializacao import serializar
from app.graph.core.engine import build_graph
from app.mensageria.consumers import Consumer
from app.mensageria.roteamento import GraphRouter, thread_do_ciclo
from app.representacao_regra import RepresentacaoRegra
from tests.app.banco_falso import BancoFalso
from tests.app.graph.conftest import FakeChatModel
from tests.app.limpeza_falsa import LimpezaFalsa
from tests.app.test_mensageria import exemplo, oficial

FONTE = "def aplicar_regra(bases, apuracao_base, competencias):\n    return {}\n"
RESPOSTA = f"```python\n{FONTE}```"


class ConfirmacaoFalsa:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, resposta: str = RESPOSTA) -> None:
        self.saver = InMemorySaver()
        self.banco = BancoFalso()
        self.limpeza = LimpezaFalsa()
        self.publicacoes: list[tuple[str, dict[str, Any]]] = []
        self.modelo = FakeChatModel(messages=iter([AIMessage(content=resposta) for _ in range(4)]))
        self.buscar_regra = AsyncMock(
            return_value=RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": []})
        )

        @asynccontextmanager
        async def checkpointer() -> AsyncIterator[InMemorySaver]:
            yield self.saver

        monkeypatch.setattr("app.graph.entrypoint.get_checkpointer", checkpointer)
        monkeypatch.setattr("app.graph.nodes.load_rule.buscar_regra", self.buscar_regra)
        monkeypatch.setattr("app.graph.nodes.code_generation.get_model", lambda _: self.modelo)
        self.producers = MagicMock()
        for metodo, evento in (
            ("etapa_alterada", "etapa-alterada"),
            ("no_concluido", "no-concluido"),
            ("executar_codigo", "executar-codigo"),
            ("sugestao_adaptacao_proposta", "sugestao-adaptacao-proposta"),
        ):
            setattr(self.producers, metodo, AsyncMock(side_effect=self._publicador(evento)))
        self.roteador = GraphRouter(self.banco, self.producers, self.limpeza)
        self.consumer = Consumer(ParametrosConfirmados, "parametros-confirmados", self.roteador)

    def _publicador(self, evento: str) -> Any:
        async def publicar(dto: ModeloContrato) -> None:
            payload = simplejson.loads(serializar(dto), use_decimal=True)
            oficial(evento).validate(payload)
            self.publicacoes.append((evento, payload))

        return publicar

    async def estado(self, payload: dict[str, Any]) -> StateSnapshot:
        thread = thread_do_ciclo(UUID(payload["job_id"]), UUID(payload["regra_id"]))
        return await build_graph(self.saver).aget_state({"configurable": {"thread_id": thread}})


def mensagem(payload: dict[str, Any] | None = None) -> AsyncMock:
    corpo = exemplo("parametros-confirmados") if payload is None else payload
    return AsyncMock(body=simplejson.dumps(corpo, use_decimal=True).encode())
