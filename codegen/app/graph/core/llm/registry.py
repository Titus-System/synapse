"""Named registry of chat models.

A node asks for the model it needs by name - `get_model("calculator")` -
rather than instantiating a provider client itself. This is the one place
provider/config details for every model in the graph live, so swapping a
provider, or using a different model for a different node, never touches
node code.
"""

from collections.abc import Callable
from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings


# --- BUILDERS - One builder per provider.
def _google(model_id: str) -> BaseChatModel:
    """Return a Google Gemini model with the given `model_id`."""
    api_key = get_settings().GOOGLE_API_KEY
    return ChatGoogleGenerativeAI(model=model_id, google_api_key=api_key)


# --- MODELS registry. Add a new entry here to register a new model.
_MODELS: dict[str, Callable[[], BaseChatModel]] = {
    "calculator": lambda: _google("gemini-3.1-flash-lite"),
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
