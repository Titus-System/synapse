from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.graph.core.state import AgentState
from app.graph.nodes import load_rule as modulo
from app.repositorio.regras import RegraInvalidaError
from app.representacao_regra import RepresentacaoRegra

JOB_ID = str(uuid4())
REGRA_ID = str(uuid4())


def _config(sessoes: object = None) -> dict[str, Any]:
    return {"configurable": {"sessoes": sessoes}}


async def test_load_rule_stores_the_validated_rule_in_the_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    regra = RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": []})
    buscar = AsyncMock(return_value=regra)
    monkeypatch.setattr(modulo, "buscar_regra", buscar)
    state: AgentState = {"job_id": JOB_ID, "regra_id": REGRA_ID}

    update = await modulo.load_rule(state, _config("sessoes-falsas"))

    assert update == {"representacao_regra": regra.para_contrato()}
    buscar.assert_awaited_once()


async def test_load_rule_passes_sessoes_job_id_and_regra_id_to_the_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    regra = RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": []})
    buscar = AsyncMock(return_value=regra)
    monkeypatch.setattr(modulo, "buscar_regra", buscar)
    state: AgentState = {"job_id": JOB_ID, "regra_id": REGRA_ID}

    await modulo.load_rule(state, _config("sessoes-falsas"))

    from uuid import UUID

    buscar.assert_awaited_once_with("sessoes-falsas", UUID(JOB_ID), UUID(REGRA_ID))


async def test_load_rule_raises_when_regra_id_is_missing_from_the_state() -> None:
    state: AgentState = {"job_id": JOB_ID}

    with pytest.raises(RegraInvalidaError):
        await modulo.load_rule(state, _config())


async def test_load_rule_propagates_the_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        modulo, "buscar_regra", AsyncMock(side_effect=RegraInvalidaError("not found"))
    )
    state: AgentState = {"job_id": JOB_ID, "regra_id": REGRA_ID}

    with pytest.raises(RegraInvalidaError):
        await modulo.load_rule(state, _config("sessoes-falsas"))
