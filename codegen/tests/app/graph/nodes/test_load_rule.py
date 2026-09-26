from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson

from app.contratos.mensagens import EtapaAlterada
from app.contratos.serializacao import serializar
from app.graph.core.state import AgentState
from app.graph.nodes import load_rule as modulo
from app.repositorio.regras import RegraInvalidaError
from app.representacao_regra import RepresentacaoRegra
from tests.app.test_mensageria import oficial

JOB_ID = str(uuid4())
REGRA_ID = str(uuid4())


def _producers() -> Any:
    return MagicMock(etapa_alterada=AsyncMock())


def _config(sessoes: object = None, producers: Any = None) -> dict[str, Any]:
    return {"configurable": {"sessoes": sessoes, "producers": producers or _producers()}}


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


async def test_load_rule_anuncia_a_entrada_da_etapa_de_geracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O contrato manda disparar `etapa-alterada` na ENTRADA da etapa, e esta é a entrada de
    `geracao_codigo` - o único sinal de progresso que a tela recebe durante a geração."""
    regra = RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": []})
    monkeypatch.setattr(modulo, "buscar_regra", AsyncMock(return_value=regra))
    producers = _producers()

    await modulo.load_rule(
        {"job_id": JOB_ID, "regra_id": REGRA_ID}, _config("sessoes-falsas", producers)
    )

    [evento] = producers.etapa_alterada.await_args.args
    assert evento == EtapaAlterada(job_id=UUID(JOB_ID), etapa="geracao_codigo", status="iniciada")
    oficial("etapa-alterada").validate(simplejson.loads(serializar(evento), use_decimal=True))


async def test_load_rule_anuncia_a_etapa_antes_de_ler_a_regra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anunciar depois da leitura tornaria o evento uma mentira quando a regra não existe: a
    etapa começou, e é isso que o cliente precisa saber antes de receber o erro."""
    ordem: list[str] = []
    producers = MagicMock(etapa_alterada=AsyncMock(side_effect=lambda _: ordem.append("etapa")))

    async def buscar(*_: object) -> RepresentacaoRegra:
        ordem.append("buscar")
        raise RegraInvalidaError("not found")

    monkeypatch.setattr(modulo, "buscar_regra", buscar)

    with pytest.raises(RegraInvalidaError):
        await modulo.load_rule(
            {"job_id": JOB_ID, "regra_id": REGRA_ID}, _config("sessoes-falsas", producers)
        )

    assert ordem == ["etapa", "buscar"]


async def test_load_rule_nao_anuncia_etapa_sem_regra_id_no_estado() -> None:
    """Sem `regra_id` não há o que gerar; a etapa não chega a começar."""
    producers = _producers()

    with pytest.raises(RegraInvalidaError):
        await modulo.load_rule({"job_id": JOB_ID}, _config(producers=producers))

    producers.etapa_alterada.assert_not_awaited()
