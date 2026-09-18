"""Named registry of chat models.

A node asks for the model it needs by name — `get_model("calculator")` —
rather than instantiating a provider client itself. This is the one place
provider/config details for every model in the graph live, so swapping a
provider, or using a different model for a different node, never touches
node code.
"""

from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings

_MODEL_IDS = {
    "calculator": "gemini-3.1-flash-lite",
}


@lru_cache
def get_model(name: str) -> ChatGoogleGenerativeAI:
    """Return the configured chat model registered under `name`."""
    try:
        model_id = _MODEL_IDS[name]
    except KeyError:
        raise ValueError(f"No model registered under {name!r}") from None

    settings = get_settings()
    return ChatGoogleGenerativeAI(model=model_id, google_api_key=settings.GOOGLE_API_KEY)
