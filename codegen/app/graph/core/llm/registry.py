"""Named registry of chat models.

A node asks for the model it needs by name - `get_model("code_generation")` -
rather than instantiating a provider client itself. This is the one place
provider/config details for every model in the graph live, so swapping a
provider, or using a different model for a different node, never touches
node code.
"""

from collections.abc import Callable
from copy import deepcopy
from functools import lru_cache
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings


# --- BUILDERS - One builder per provider.
def _google(model_id: str, **kwargs: Any) -> BaseChatModel:
    """Return a Google Gemini model with the given `model_id`."""
    api_key = get_settings().GOOGLE_API_KEY
    if api_key is None:
        raise ValueError("GOOGLE_API_KEY is not configured")
    return ChatGoogleGenerativeAI(model=model_id, google_api_key=api_key, **kwargs)


# --- MODELS registry. Add a new entry here to register a new model.
# `code_generation`'s prompt embeds the base tables, schemas and the RegraFn contract, so it
# is large (~80k chars / ~23k tokens for the fixtures used in local verification); the timeout
# below must stay below the RabbitMQ consumer_timeout for regra-submetida (the message carries
# no ack while this call runs - see `.agents/skills/graph/SKILL.md`).
#
# `gemini-3.1-flash-lite`, not a "pro" model: verified against the real API -
# `gemini-3.1-pro` does not exist, and the "pro" tier models that do
# (`gemini-3.1-pro-preview`, `gemini-2.5-pro`) return `RESOURCE_EXHAUSTED` (quota 0) on this
# project's free-tier key. `flash-lite` has real quota and the same 1,048,576-token input
# window, comfortably above this prompt's size.
_MODELS: dict[str, Callable[[], BaseChatModel]] = {
    "code_generation": lambda: _google(
        "gemini-3.1-flash-lite",
        temperature=0,
        max_output_tokens=8192,
        timeout=60,
        max_retries=2,
    ),
}

# Metadata recorded alongside each call, matching `modelo-llm.schema.json`. Kept here, next to
# the builder that produces it, instead of read back from the provider response: Gemini's
# response carries no reliable per-call snapshot/version field to read it from.
_METADATA: dict[str, dict[str, Any]] = {
    "code_generation": {
        "provedor": "google",
        "modelo": "gemini-3.1-flash-lite",
        "versao": "stable",
        "parametros": {"temperature": 0, "max_output_tokens": 8192},
    },
}


# --- PUBLIC INTERFACE to get a model by name.
@lru_cache
def get_model(name: str) -> BaseChatModel:
    """Return the configured chat model registered under `name`."""
    try:
        build = _MODELS[name]
    except KeyError:
        raise ValueError(f"No model registered under {name!r}") from None
    return build()


def get_model_metadata(name: str) -> dict[str, Any]:
    """Return the `modelo-llm.schema.json` metadata registered under `name`."""
    try:
        metadata = _METADATA[name]
    except KeyError:
        raise ValueError(f"No metadata registered under {name!r}") from None
    return deepcopy(metadata)
