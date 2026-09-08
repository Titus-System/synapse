import copy
import json
import logging
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import lru_cache
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from queue import Queue
from typing import Any, ClassVar

from opentelemetry import trace as otel_trace

from app.config import get_settings

# Business-level context. trace_id/span_id are NOT here: they come from the
# active OpenTelemetry span, so the ids in the log are always the ones the
# tracing backend knows.
job_id_ctx: ContextVar[str | None] = ContextVar("job_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

# conforms to opentelemetry convention
_OTEL_SEVERITY_TEXT = {"WARNING": "WARN", "CRITICAL": "FATAL"}


def severity_text(levelname: str) -> str:
    """Nome do nível como ele vai para o log, no vocabulário do OpenTelemetry."""
    return _OTEL_SEVERITY_TEXT.get(levelname, levelname)


def current_trace_ids() -> tuple[str, str] | None:
    """W3C-formatted (trace_id, span_id) of the active span, if there is one."""
    span_context = otel_trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None

    return format(span_context.trace_id, "032x"), format(span_context.span_id, "016x")


class ContextQueueHandler(QueueHandler):
    """Snapshots context vars onto the record before enqueuing.

    The QueueListener processes records in a separate thread where
    ContextVar values from the originating async task are not visible.
    The OTel span context is a ContextVar too, so it is captured here as well.
    """

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        # Not super().prepare(): it bakes the traceback into the message and drops exc_info.
        record = copy.copy(record)
        trace_ids = current_trace_ids()
        if trace_ids:
            record.trace_id, record.span_id = trace_ids

        ctx_job_id = job_id_ctx.get()
        if ctx_job_id:
            record.job_id = ctx_job_id

        ctx_user_id = user_id_ctx.get()
        if ctx_user_id:
            record.user_id = ctx_user_id

        return record


class JsonFormatter(logging.Formatter):
    """Structured JSON formatter shared by every microservice.

    Emits a stable envelope: origin identity (service/environment/version/host),
    correlation fields, source location, and any ``extra={...}`` payload.
    """

    _DEFAULT_KEYS = frozenset(
        logging.LogRecord("", 0, "", 0, None, None, None).__dict__.keys()
        | {"message", "taskName", "trace_id", "span_id", "job_id", "user_id"}
    )

    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self._service = settings.SERVICE_NAME
        self._environment = settings.ENVIRONMENT
        self._version = settings.VERSION
        self._host = settings.hostname

    def format(self, record: logging.LogRecord) -> str:
        log_record: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": severity_text(record.levelname),
            "message": record.getMessage(),
            "service": self._service,
            "environment": self._environment,
            "version": self._version,
            "host": self._host,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        for field in ("trace_id", "span_id", "job_id", "user_id"):
            value = getattr(record, field, None)
            if value:
                log_record[field] = value

        # Capture extra fields passed via logger.info("msg", extra={...})
        extra = {k: v for k, v in record.__dict__.items() if k not in self._DEFAULT_KEYS}
        if extra:
            log_record["extra"] = extra

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record, ensure_ascii=False)


class DevFormatter(logging.Formatter):
    LEVEL_COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelname, self.RESET)
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%H:%M:%S")
        tid = getattr(record, "trace_id", None)
        jid = getattr(record, "job_id", None)
        uid = getattr(record, "user_id", None)
        ctx_parts: list[Any] = [
            f"t:{tid[:8]}" if tid else None,
            f"j:{jid[:8]}" if jid else None,
            f"u:{uid[:8]}" if uid else None,
        ]
        ctx = " [" + " ".join(p for p in ctx_parts if p) + "]" if any(ctx_parts) else ""

        base = (
            f"{color}{ts} {severity_text(record.levelname):<7}{self.RESET}"
            f" {record.name} · {record.funcName}:{record.lineno}"
            f"{ctx} — {record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)

        return base


class AsyncLoggerRoot:
    """Initializes the root 'app' logger once and manages the QueueListener."""

    def __init__(self) -> None:
        if not os.path.exists("logs"):
            os.makedirs("logs")

        settings = get_settings()
        is_dev = settings.ENVIRONMENT == "development"
        log_level = logging.getLevelNamesMapping().get(settings.LOG_LEVEL.upper(), logging.INFO)

        json_formatter = JsonFormatter()
        max_file_size = 10 * 1024 * 1024  # 10MB
        backup_count = 5

        # File handlers (always JSON)
        file_handler = RotatingFileHandler(
            "logs/app.json", maxBytes=max_file_size, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(json_formatter)
        file_handler.setLevel(log_level)

        error_handler = RotatingFileHandler(
            "logs/error.json", maxBytes=max_file_size, backupCount=backup_count, encoding="utf-8"
        )
        error_handler.setFormatter(json_formatter)
        error_handler.setLevel(logging.ERROR)

        # Console: plaintext in dev, JSON in production
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(DevFormatter() if is_dev else json_formatter)
        stream_handler.setLevel(log_level)

        # Centralized logging queue — snapshots context vars before enqueuing
        self.log_queue: Queue[logging.LogRecord] = Queue(-1)
        queue_handler = ContextQueueHandler(self.log_queue)

        # Root app logger
        root = logging.getLogger("app")
        root.setLevel(logging.DEBUG)
        root.addHandler(queue_handler)

        # Queue listener to handle log records asynchronously
        self.listener = QueueListener(
            self.log_queue,
            file_handler,
            error_handler,
            stream_handler,
            respect_handler_level=True,
        )
        self.listener.start()

    def stop(self) -> None:
        self.listener.stop()


class Logger:
    """Thin wrapper around a stdlib logger with stacklevel-aware convenience methods."""

    def __init__(self, name: str = "app") -> None:
        self._logger = logging.getLogger(name)

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("stacklevel", 2)
        self._logger.debug(message, *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("stacklevel", 2)
        self._logger.info(message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("stacklevel", 2)
        self._logger.warning(message, *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("stacklevel", 2)
        self._logger.error(message, *args, **kwargs)

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("stacklevel", 2)
        kwargs.setdefault("exc_info", True)
        self._logger.error(message, *args, **kwargs)


@lru_cache
def _init_root() -> AsyncLoggerRoot:
    return AsyncLoggerRoot()


def get_logger(name: str = "app") -> Logger:
    _init_root()
    return Logger(name)


def stop_logger() -> None:
    _init_root().stop()
