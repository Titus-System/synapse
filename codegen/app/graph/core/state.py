"""The one shared state schema every node in the graph reads and writes."""

from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """Shared graph state - see `.agents/skills/graph/SKILL.md`.

    Every field is optional: a node declares only the ones it actually reads or writes.
    Field names and types are the interface agreed across T-094/T-096/T-097 - do not rename
    or retype one without coordinating those tasks.
    """

    # `add_messages` is the reducer: a node's return value is merged into `messages`
    # (appended) rather than replacing it outright. No current node reads or writes it -
    # kept for a future node that needs an accumulating chat history (e.g. a tool loop, or
    # replaying context across an `interrupt()` pause).
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # T-094 (initial state, from `regra-submetida`)
    job_id: str
    regra_id: str
    origem: str
    competencias: list[str]
    orcamento: str  # decimal text, never float - see `app/tipos_estado.py::Orcamento`

    # T-096 (this task)
    representacao_regra: dict[str, Any]
    prompt_enviado: str
    resposta_bruta: str
    modelo: dict[str, Any]
    consumo_tokens: dict[str, Any]

    # T-097
    prompt_id: str
    resposta_id: str
    codigo_fonte: str
    codigo_gerado_id: str
