from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from app.graph.core.llm import registry


@pytest.fixture(autouse=True)
def clear_model_cache() -> Iterator[None]:
    registry.get_model.cache_clear()
    yield
    registry.get_model.cache_clear()


def test_get_model_rejects_a_name_that_is_not_registered() -> None:
    with pytest.raises(ValueError, match="'missing'") as error:
        registry.get_model("missing")

    assert error.value.__suppress_context__ is True


def test_get_model_builds_each_registered_model_once(monkeypatch: pytest.MonkeyPatch) -> None:
    builds: list[str] = []

    def build() -> Any:
        builds.append("built")
        return object()

    monkeypatch.setattr(registry, "_MODELS", {"fake": build})

    first = registry.get_model("fake")
    second = registry.get_model("fake")

    assert first is second
    assert builds == ["built"]


def test_get_model_returns_what_the_registered_builder_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = object()
    monkeypatch.setattr(registry, "_MODELS", {"fake": lambda: model})

    assert registry.get_model("fake") is model


def test_google_builder_takes_its_key_from_settings_and_the_id_from_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}

    def fake_client(**kwargs: Any) -> object:
        received.update(kwargs)
        return object()

    monkeypatch.setattr(registry, "ChatGoogleGenerativeAI", fake_client)
    monkeypatch.setattr(registry, "get_settings", lambda: SimpleNamespace(GOOGLE_API_KEY="key-1"))

    registry._google("some-model")

    assert received == {"model": "some-model", "google_api_key": "key-1"}


def test_google_builder_forwards_extra_parameters_to_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}
    monkeypatch.setattr(
        registry, "ChatGoogleGenerativeAI", lambda **kw: received.update(kw) or object()
    )
    monkeypatch.setattr(registry, "get_settings", lambda: SimpleNamespace(GOOGLE_API_KEY="key-1"))

    registry._google("some-model", temperature=0, timeout=45)

    assert received == {
        "model": "some-model",
        "google_api_key": "key-1",
        "temperature": 0,
        "timeout": 45,
    }


def test_google_builder_raises_a_clear_error_when_the_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "get_settings", lambda: SimpleNamespace(GOOGLE_API_KEY=None))

    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        registry._google("some-model")


def test_code_generation_is_registered_with_its_metadata() -> None:
    assert "code_generation" in registry._MODELS

    metadata = registry.get_model_metadata("code_generation")

    assert metadata["provedor"] == "google"
    assert metadata["modelo"] == "gemini-3.1-flash-lite"


def test_greeting_is_registered() -> None:
    assert "greeting" in registry._MODELS


def test_get_model_metadata_returns_a_copy_not_the_stored_dict() -> None:
    metadata = registry.get_model_metadata("code_generation")
    metadata["provedor"] = "adulterado"

    assert registry.get_model_metadata("code_generation")["provedor"] == "google"


def test_get_model_metadata_rejects_a_name_that_is_not_registered() -> None:
    with pytest.raises(ValueError, match="'missing'"):
        registry.get_model_metadata("missing")
