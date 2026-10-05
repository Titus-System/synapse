from langchain_core.messages import BaseMessage


def extrair_resposta(response: BaseMessage) -> tuple[str, str | None]:
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
