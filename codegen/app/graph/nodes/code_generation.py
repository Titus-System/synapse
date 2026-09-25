"""`code_generation` node: sends the generation prompt to the model and records the raw reply.

No tools are bound here - the model only replies with text, never picks a next step.
"""

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import NoGrafo
from app.core.logger import get_logger, no_ctx
from app.falhas import FalhaDoJobError
from app.graph.core.llm.registry import get_model, get_model_metadata
from app.graph.core.state import AgentState
from app.prompts.geracao_codigo import montar_prompt_geracao
from app.representacao_regra import RepresentacaoRegra

logger = get_logger("app.graph.nodes.code_generation")

# Identifies this node's model call in the log `no` field and in `prompts.no`.
NO_GERACAO_CODIGO: NoGrafo = "geracao_codigo"

# The only finish reason that means a clean stop. An allowlist, not a blocklist: the provider
# reports the enum's name (`langchain_google_genai/chat_models.py`), and the set of failure
# names is open - `BLOCKLIST`, `PROHIBITED_CONTENT`, `SPII`, `MALFORMED_FUNCTION_CALL` and
# `UNKNOWN_<n>` for an unmapped enum. A blocklist would let those through with partial text.
# An absent field is enum 0, `FINISH_REASON_UNSPECIFIED`, which is not a clean stop either.
_FINISH_REASON_ACEITO = "STOP"


class RespostaModeloInvalidaError(FalhaDoJobError):
    """The model call returned no usable content: empty, blocked, or truncated by a limit.

    Permanent by design: `temperature=0` makes the call deterministic, so a redelivery would
    resume at this same node and pay for the same unusable reply again.
    """

    etapa = "geracao_codigo"


async def code_generation(state: AgentState, config: RunnableConfig) -> AgentState:
    """Build the generation prompt from `representacao_regra` and call `code_generation`.

    Raises `RespostaModeloInvalidaError` when the reply is empty, blocked or truncated - a
    provider error propagates as-is. Neither case leaves partial state (AGENTS.md).
    """
    rule = RepresentacaoRegra.model_validate(state["representacao_regra"])
    prompt = montar_prompt_geracao(rule)

    token = no_ctx.set(NO_GERACAO_CODIGO)
    try:
        model = get_model("code_generation")
        response = await model.ainvoke([HumanMessage(content=prompt)])
        content, finish_reason = _extract_response(response)

        if not content or finish_reason != _FINISH_REASON_ACEITO:
            logger.error(
                "code_generation model call returned no usable content",
                extra={"finish_reason": finish_reason},
            )
            raise RespostaModeloInvalidaError("Empty, blocked or truncated model response")

        update: AgentState = {
            "prompt_enviado": prompt,
            "resposta_bruta": content,
            "modelo": get_model_metadata("code_generation"),
        }
        usage = _token_usage(response)
        if usage is not None:
            update["consumo_tokens"] = usage

        logger.info("code_generation model call finished", extra={"finish_reason": finish_reason})
        return update
    finally:
        no_ctx.reset(token)


def _extract_response(response: BaseMessage) -> tuple[str, str | None]:
    content = _text_content(response.content)
    metadata = response.response_metadata or {}
    finish_reason = metadata.get("finish_reason")
    return content, finish_reason


def _text_content(content: object) -> str:
    # `AIMessage.content` is `str | list[str | dict]`. Some providers (observed: Gemini,
    # via langchain_google_genai) return a list of content-part dicts even for a plain text
    # reply, e.g. `[{"type": "text", "text": "...", "extras": {...}}]` - a bare `isinstance`
    # check against `str` silently treats every one of those replies as empty.
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes = []
        for item in content:
            if isinstance(item, str):
                partes.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                partes.append(str(item.get("text", "")))
        return "".join(partes)
    return ""


def _token_usage(response: BaseMessage) -> dict[str, Any] | None:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return None
    tokens_in = usage.get("input_tokens")
    tokens_out = usage.get("output_tokens")
    if tokens_in is None or tokens_out is None:
        return None
    return {"tokens_in": tokens_in, "tokens_out": tokens_out}
