import json
import logging
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from queue import Queue
from typing import Any

import pytest

from app.config import Settings
from app.core.logger import ContextQueueHandler, JsonFormatter, job_id_ctx, user_id_ctx

# Other services parse this envelope. Changing the set means changing them too.
CONTRACT_FIELDS = frozenset(
    {
        "timestamp",
        "level",
        "message",
        "service",
        "environment",
        "version",
        "host",
        "logger",
        "module",
        "function",
        "line",
    }
)

EmitLine = Callable[..., str]
Envelope = Callable[..., dict[str, Any]]


@pytest.fixture(autouse=True)
def _isolated_context() -> Iterator[None]:
    job_token = job_id_ctx.set(None)
    user_token = user_id_ctx.set(None)
    yield
    job_id_ctx.reset(job_token)
    user_id_ctx.reset(user_token)


@pytest.fixture
def emit_line() -> EmitLine:
    """Handler then formatter, the same order the QueueListener applies them in."""
    handler = ContextQueueHandler(Queue(-1))
    formatter = JsonFormatter()

    def _emit(
        message: str = "code execution finished",
        *,
        level: int = logging.INFO,
        exc_info: Any = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        record = logging.getLogger("app.worker.consumer").makeRecord(
            "app.worker.consumer",
            level,
            "app/worker/consumer.py",
            42,
            message,
            (),
            exc_info,
            "handle_message",
            extra,
        )
        return formatter.format(handler.prepare(record))

    return _emit


@pytest.fixture
def envelope(emit_line: EmitLine) -> Envelope:
    def _envelope(*args: Any, **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(emit_line(*args, **kwargs))
        return payload

    return _envelope


def test_top_level_fields_are_exactly_the_contract(envelope: Envelope) -> None:
    assert set(envelope()) == set(CONTRACT_FIELDS)


def test_identity_fields_come_from_settings(envelope: Envelope, settings: Settings) -> None:
    payload = envelope()

    assert payload["service"] == settings.SERVICE_NAME
    assert payload["environment"] == settings.ENVIRONMENT
    assert payload["version"] == settings.VERSION
    assert payload["host"] == settings.hostname


def test_timestamp_is_utc_iso8601(envelope: Envelope) -> None:
    assert datetime.fromisoformat(envelope()["timestamp"]).utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (logging.DEBUG, "DEBUG"),
        (logging.INFO, "INFO"),
        (logging.WARNING, "WARN"),
        (logging.ERROR, "ERROR"),
        (logging.CRITICAL, "FATAL"),
    ],
)
def test_level_uses_opentelemetry_short_names(
    envelope: Envelope, level: int, expected: str
) -> None:
    """`level` is a Loki label, so the vocabulary has to be one across services."""
    assert envelope(level=level)["level"] == expected


def test_source_location_identifies_the_call_site(envelope: Envelope) -> None:
    payload = envelope()

    assert payload["logger"] == "app.worker.consumer"
    assert payload["module"] == "consumer"
    assert payload["function"] == "handle_message"
    assert payload["line"] == 42


def test_extra_is_namespaced_under_extra(envelope: Envelope) -> None:
    payload = envelope(extra={"exit_code": 0, "duration_ms": 1432})

    assert payload["extra"] == {"exit_code": 0, "duration_ms": 1432}
    assert "exit_code" not in payload


def test_correlation_fields_are_omitted_when_unset(envelope: Envelope) -> None:
    assert not {"trace_id", "span_id", "job_id", "user_id"} & set(envelope())


def test_correlation_fields_are_top_level(envelope: Envelope) -> None:
    job_id_ctx.set("job-42")
    user_id_ctx.set("user-7")

    payload = envelope()

    assert payload["job_id"] == "job-42"
    assert payload["user_id"] == "user-7"
    assert "extra" not in payload


def test_traceback_is_a_field_and_leaves_the_message_constant(envelope: Envelope) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        payload = envelope("sandbox timed out", level=logging.ERROR, exc_info=sys.exc_info())

    assert payload["message"] == "sandbox timed out"
    assert "ValueError: boom" in payload["exception"]


def test_a_record_serializes_to_one_line(emit_line: EmitLine) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        line = emit_line("sandbox timed out", level=logging.ERROR, exc_info=sys.exc_info())

    assert "\n" not in line


def test_non_ascii_is_not_escaped(emit_line: EmitLine) -> None:
    assert "execução finalizada" in emit_line("execução finalizada")
