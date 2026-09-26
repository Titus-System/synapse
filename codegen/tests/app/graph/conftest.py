from collections.abc import Callable, Iterable, Iterator
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from pydantic import Field


class FakeChatModel(GenericFakeChatModel):
    """Scripted stand-in for a provider client; records what the node sent and bound."""

    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeChatModel":
        self.bound_tools = list(tools)
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.seen_messages.append(list(messages))
        resultado = super()._generate(messages, *args, **kwargs)
        # O provedor real sempre reporta o motivo da parada, e num sucesso ele é `STOP`. Sem
        # isso toda resposta roteirizada pareceria interrompida para quem valida o campo.
        # Uma resposta que já traz o seu próprio `finish_reason` não é tocada.
        for geracao in resultado.generations:
            geracao.message.response_metadata.setdefault("finish_reason", "STOP")
        return resultado


@pytest.fixture
def scripted_model(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Iterable[AIMessage]], FakeChatModel]:
    """Make every model-calling node use one model that replies with `responses`, in order.

    A graph run consumes the replies in the order the nodes call the model.

    Pass fresh message objects: `add_messages` stamps an id on each one, and a repeated
    object would replace itself in the history instead of being appended.
    """

    def install(responses: Iterable[AIMessage]) -> FakeChatModel:
        replies: Iterator[AIMessage] = iter(responses)
        model = FakeChatModel(messages=replies)
        monkeypatch.setattr("app.graph.nodes.code_generation.get_model", lambda name: model)
        return model

    return install
