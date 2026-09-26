import json
import logging
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from queue import Queue
from typing import Any

import pytest

from app.config import Settings
from app.core.logger import (
    FormatadorJson,
    ManipuladorFilaContexto,
    competencia_ctx,
    job_id_ctx,
    no_ctx,
    user_id_ctx,
)

CAMPOS_CONTRATO = frozenset(
    {
        "timestamp",
        "level",
        "message",
        "service.name",
        "environment",
        "service.version",
        "host.name",
        "logger",
        "code",
    }
)

EmitirLinha = Callable[..., str]
TipoEnvelope = Callable[..., dict[str, Any]]


@pytest.fixture(autouse=True)
def contexto_isolado() -> Iterator[None]:
    tokens = [
        job_id_ctx.set(None),
        user_id_ctx.set(None),
        no_ctx.set(None),
        competencia_ctx.set(None),
    ]
    yield
    job_id_ctx.reset(tokens[0])
    user_id_ctx.reset(tokens[1])
    no_ctx.reset(tokens[2])
    competencia_ctx.reset(tokens[3])


@pytest.fixture
def emitir_linha() -> EmitirLinha:
    manipulador = ManipuladorFilaContexto(Queue(-1))
    formatador = FormatadorJson()

    def emitir(
        mensagem: str = "execução de código concluída",
        *,
        nivel: int = logging.INFO,
        informacoes_excecao: Any = None,
        campos_extras: dict[str, Any] | None = None,
    ) -> str:
        registro = logging.getLogger("app.mensageria.consumidor").makeRecord(
            "app.mensageria.consumidor",
            nivel,
            "app/mensageria/consumidor.py",
            42,
            mensagem,
            (),
            informacoes_excecao,
            "consumir_mensagem",
            campos_extras,
        )
        return formatador.format(manipulador.prepare(registro))

    return emitir


@pytest.fixture
def envelope(emitir_linha: EmitirLinha) -> TipoEnvelope:
    def criar_envelope(*argumentos: Any, **argumentos_nomeados: Any) -> dict[str, Any]:
        return json.loads(emitir_linha(*argumentos, **argumentos_nomeados))

    return criar_envelope


def test_campos_de_topo_sao_exatamente_o_contrato(envelope: TipoEnvelope) -> None:
    assert set(envelope()) == CAMPOS_CONTRATO


def test_identidade_do_servico_vem_das_configuracoes(
    envelope: TipoEnvelope, configuracoes: Settings
) -> None:
    linha = envelope()

    assert linha["service.name"] == configuracoes.SERVICE_NAME
    assert linha["environment"] == configuracoes.ENVIRONMENT
    assert linha["service.version"] == configuracoes.VERSION
    assert linha["host.name"] == configuracoes.hostname


def test_timestamp_esta_em_utc_no_formato_iso8601(envelope: TipoEnvelope) -> None:
    assert datetime.fromisoformat(envelope()["timestamp"]).utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("nivel", "esperado"),
    [
        (logging.DEBUG, "DEBUG"),
        (logging.INFO, "INFO"),
        (logging.WARNING, "WARN"),
        (logging.ERROR, "ERROR"),
        (logging.CRITICAL, "FATAL"),
    ],
)
def test_nivel_usa_nomes_curtos_do_opentelemetry(
    envelope: TipoEnvelope, nivel: int, esperado: str
) -> None:
    assert envelope(nivel=nivel)["level"] == esperado


def test_codigo_identifica_o_ponto_da_chamada(envelope: TipoEnvelope) -> None:
    assert envelope()["code"] == {
        "module": "consumidor",
        "function": "consumir_mensagem",
        "line": 42,
    }


def test_campos_de_correlacao_sao_omitidos_quando_ausentes(envelope: TipoEnvelope) -> None:
    assert not {"trace_id", "span_id", "job_id", "user_id", "no", "competencia"} & set(envelope())


def test_no_do_grafo_e_emitido_no_topo_do_log(envelope: TipoEnvelope) -> None:
    no_ctx.set("gerar_codigo")

    assert envelope()["no"] == "gerar_codigo"


def test_campos_extras_ficam_no_objeto_extra(envelope: TipoEnvelope) -> None:
    linha = envelope(campos_extras={"tentativa": 1})

    assert linha["extra"] == {"tentativa": 1}
    assert "tentativa" not in linha


def test_excecao_tem_campo_proprio_e_mantem_a_mensagem_constante(
    envelope: TipoEnvelope,
) -> None:
    try:
        raise ValueError("falhou")
    except ValueError:
        linha = envelope(
            "processamento interrompido",
            nivel=logging.ERROR,
            informacoes_excecao=sys.exc_info(),
        )

    assert linha["message"] == "processamento interrompido"
    assert "ValueError: falhou" in linha["exception"]
