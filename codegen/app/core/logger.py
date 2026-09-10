import copy
import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import lru_cache
from logging.handlers import QueueHandler, QueueListener
from queue import Queue
from typing import Any

from opentelemetry import trace as rastreamento_otel

from app.config import get_settings

job_id_ctx: ContextVar[str | None] = ContextVar("job_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)
no_ctx: ContextVar[str | None] = ContextVar("no", default=None)
competencia_ctx: ContextVar[str | None] = ContextVar("competencia", default=None)

_NOMES_SEVERIDADE = {"WARNING": "WARN", "CRITICAL": "FATAL"}


def nome_severidade(nome_nivel: str) -> str:
    return _NOMES_SEVERIDADE.get(nome_nivel, nome_nivel)


def identificadores_rastreamento_atuais() -> tuple[str, str] | None:
    contexto_span = rastreamento_otel.get_current_span().get_span_context()
    if not contexto_span.is_valid:
        return None
    return format(contexto_span.trace_id, "032x"), format(contexto_span.span_id, "016x")


class ManipuladorFilaContexto(QueueHandler):
    """Copia ContextVars antes de a fila entregar o registro em outra thread."""

    def prepare(self, registro: logging.LogRecord) -> logging.LogRecord:
        copia_registro = copy.copy(registro)
        identificadores_rastreamento = identificadores_rastreamento_atuais()
        if identificadores_rastreamento:
            copia_registro.trace_id, copia_registro.span_id = identificadores_rastreamento

        for campo, contexto in (
            ("job_id", job_id_ctx),
            ("user_id", user_id_ctx),
            ("no", no_ctx),
            ("competencia", competencia_ctx),
        ):
            valor = contexto.get()
            if valor:
                setattr(copia_registro, campo, valor)
        return copia_registro


class FormatadorJson(logging.Formatter):
    _CHAVES_PADRAO = frozenset(
        logging.LogRecord("", 0, "", 0, None, None, None).__dict__.keys()
        | {
            "message",
            "taskName",
            "color_message",
            "trace_id",
            "span_id",
            "job_id",
            "user_id",
            "no",
            "competencia",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        configuracoes = get_settings()
        self._servico = configuracoes.SERVICE_NAME
        self._ambiente = configuracoes.ENVIRONMENT
        self._versao_servico = configuracoes.VERSION
        self._host = configuracoes.hostname

    def format(self, registro: logging.LogRecord) -> str:
        linha_log: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(registro.created, UTC).isoformat(),
            "level": nome_severidade(registro.levelname),
            "message": registro.getMessage(),
            "service.name": self._servico,
            "environment": self._ambiente,
            "service.version": self._versao_servico,
            "host.name": self._host,
            "logger": registro.name,
            "code": {
                "module": registro.module,
                "function": registro.funcName,
                "line": registro.lineno,
            },
        }

        for campo in ("trace_id", "span_id", "job_id", "user_id", "no", "competencia"):
            valor = getattr(registro, campo, None)
            if valor:
                linha_log[campo] = valor

        extra = {
            chave: valor
            for chave, valor in registro.__dict__.items()
            if chave not in self._CHAVES_PADRAO
        }
        if extra:
            linha_log["extra"] = extra

        if registro.exc_info:
            linha_log["exception"] = self.formatException(registro.exc_info)
        return json.dumps(linha_log, ensure_ascii=False)


class RaizRegistradorAssincrono:
    def __init__(self) -> None:
        configuracoes = get_settings()
        nivel_log = logging.getLevelNamesMapping().get(
            configuracoes.LOG_LEVEL.upper(), logging.INFO
        )

        manipulador_saida = logging.StreamHandler()
        manipulador_saida.setFormatter(FormatadorJson())
        manipulador_saida.setLevel(nivel_log)

        self._fila: Queue[logging.LogRecord] = Queue(-1)
        registrador_raiz = logging.getLogger("app")
        registrador_raiz.setLevel(logging.DEBUG)
        registrador_raiz.addHandler(ManipuladorFilaContexto(self._fila))

        self._ouvinte = QueueListener(self._fila, manipulador_saida, respect_handler_level=True)
        self._ouvinte.start()

    def encerrar(self) -> None:
        self._ouvinte.stop()


class Registrador:
    def __init__(self, nome: str = "app") -> None:
        self._registrador = logging.getLogger(nome)

    def debug(self, mensagem: str, *argumentos: Any, **argumentos_nomeados: Any) -> None:
        argumentos_nomeados.setdefault("stacklevel", 2)
        self._registrador.debug(mensagem, *argumentos, **argumentos_nomeados)

    def info(self, mensagem: str, *argumentos: Any, **argumentos_nomeados: Any) -> None:
        argumentos_nomeados.setdefault("stacklevel", 2)
        self._registrador.info(mensagem, *argumentos, **argumentos_nomeados)

    def warning(self, mensagem: str, *argumentos: Any, **argumentos_nomeados: Any) -> None:
        argumentos_nomeados.setdefault("stacklevel", 2)
        self._registrador.warning(mensagem, *argumentos, **argumentos_nomeados)

    def error(self, mensagem: str, *argumentos: Any, **argumentos_nomeados: Any) -> None:
        argumentos_nomeados.setdefault("stacklevel", 2)
        self._registrador.error(mensagem, *argumentos, **argumentos_nomeados)

    def exception(self, mensagem: str, *argumentos: Any, **argumentos_nomeados: Any) -> None:
        argumentos_nomeados.setdefault("stacklevel", 2)
        argumentos_nomeados.setdefault("exc_info", True)
        self._registrador.error(mensagem, *argumentos, **argumentos_nomeados)


@lru_cache
def _inicializar_raiz() -> RaizRegistradorAssincrono:
    return RaizRegistradorAssincrono()


def get_logger(nome: str = "app") -> Registrador:
    _inicializar_raiz()
    return Registrador(nome)


def stop_logger() -> None:
    _inicializar_raiz().encerrar()
