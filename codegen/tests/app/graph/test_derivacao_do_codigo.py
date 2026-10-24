"""O código da alternativa de taxa derivado do código já simulado, pelo grafo real.

Consumer, roteador, entrypoint e nós são os reais, como em `test_iteracao_da_taxa_nova.py`. O
código da versão de origem que o worker simulou com sucesso vem do `buscar_codigo_simulado`
trocado aqui; a consulta real está em `tests/app/repositorio/test_derivacao_postgres.py`.
"""

import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import simplejson
from prometheus_client import REGISTRY

from app.core.logger import FormatadorJson, ManipuladorFilaContexto
from app.graph.nodes.derive_code import RESUMO_DA_TRILHA
from app.repositorio.artefatos import CodigoSimulado
from tests.app.graph.test_iteracao_da_taxa_nova import Job

FONTE_COM_A_TAXA = (
    "def aplicar_regra(bases, apuracao_base, competencias):\n    taxa = 0.03\n    return {}\n"
)
FONTE_SEM_A_TAXA = "def aplicar_regra(bases, apuracao_base, competencias):\n    return {}\n"
METRICA = "codegen_derivacao_codigo_total"


@pytest.fixture
def logs() -> Iterator[list[dict[str, Any]]]:
    envelopes: list[dict[str, Any]] = []

    class Captura(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            preparado = ManipuladorFilaContexto(None).prepare(record)
            envelopes.append(simplejson.loads(FormatadorJson().format(preparado)))

    logger = logging.getLogger("app")
    handler = Captura()
    nivel = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield envelopes
    finally:
        logger.removeHandler(handler)
        logger.setLevel(nivel)


def _contagem(desfecho: str) -> float:
    return REGISTRY.get_sample_value(METRICA, {"desfecho": desfecho}) or 0.0


async def _ate_a_alternativa(
    monkeypatch: pytest.MonkeyPatch, fonte_da_origem: str
) -> tuple[Job, UUID, CodigoSimulado]:
    """A original simulada sem caber, a proposta publicada e o ciclo da alternativa aberto."""
    job = Job(monkeypatch)
    original = job.original()
    codigo_da_origem = CodigoSimulado(id=uuid4(), prompt_id=uuid4(), fonte=fonte_da_origem)

    async def buscar_codigo_simulado(sessoes: Any, job_id: UUID, regra_id: UUID) -> Any:
        return codigo_da_origem if regra_id == original else None

    monkeypatch.setattr(
        "app.graph.nodes.derive_code.buscar_codigo_simulado",
        AsyncMock(side_effect=buscar_codigo_simulado),
    )
    await job.abrir_ciclo(original)
    await job.simular(original, Decimal("2200"))
    (proposta,) = job.propostas()
    alternativa = await job.alternativa(proposta)
    return job, alternativa, codigo_da_origem


async def test_alternativa_recebe_o_codigo_da_origem_com_a_taxa_nova_sem_chamar_o_modelo(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    antes = _contagem("derivado")

    job, alternativa, origem = await _ate_a_alternativa(monkeypatch, FONTE_COM_A_TAXA)

    # Só a original passou pelo modelo.
    assert len(job.ambiente.modelo.seen_messages) == 1
    (derivado,) = [
        c for c in job.ambiente.banco.tabela("codigos_gerados") if c["regra_id"] == alternativa
    ]
    assert derivado["fonte"] == FONTE_COM_A_TAXA.replace("0.03", "0.0175")
    assert derivado["prompt_id"] == origem.prompt_id
    (comando,) = [
        c for c in job.publicadas("executar-codigo") if c["codigo_gerado_id"] == str(derivado["id"])
    ]
    assert comando["job_id"] == str(job.historico.job_id)
    (trilha,) = [
        n
        for n in job.publicadas("no-concluido")
        if n.get("codigo_gerado_id") == str(derivado["id"]) and n["no"] == "geracao_codigo"
    ]
    assert trilha["conclusao"]["resumo"] == RESUMO_DA_TRILHA
    assert trilha["prompt_id"] == str(origem.prompt_id)
    assert _contagem("derivado") == antes + 1
    (log,) = [e for e in logs if e["message"] == "alternative code derived from the origin code"]
    assert log["job_id"] == str(job.historico.job_id)
    assert log["no"] == "geracao_codigo"
    assert log["extra"]["taxas_trocadas"] == 1
    assert "aplicar_regra" not in simplejson.dumps(logs)


async def test_alternativa_cujo_codigo_nao_escreve_a_taxa_e_gerada_pelo_modelo(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    antes = _contagem("taxas_nao_localizadas")

    job, alternativa, _ = await _ate_a_alternativa(monkeypatch, FONTE_SEM_A_TAXA)

    assert len(job.ambiente.modelo.seen_messages) == 2
    assert [c["regra_id"] for c in job.ambiente.banco.tabela("codigos_gerados")].count(
        alternativa
    ) == 1
    assert _contagem("taxas_nao_localizadas") == antes + 1
    (log,) = [
        e for e in logs if e["message"] == "alternative code not derived; generating with the model"
    ]
    assert log["extra"]["motivo"] == "taxas_nao_localizadas"
