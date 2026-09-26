from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson

from app.contratos.mensagens import EtapaAlterada
from app.contratos.serializacao import serializar
from app.graph.core.state import AgentState
from app.graph.nodes import suggest_adaptation as modulo
from app.repositorio.resultados import ResultadoIndisponivelError, TotaisDaSimulacao
from tests.app.test_mensageria import oficial

JOB_ID = str(uuid4())
REGRA_ID = str(uuid4())
RESULTADO_ID = str(uuid4())

NUCLEO = {
    "vigencia": {"inicio": "2025-08", "fim": "2025-12"},
    "loja": ["13"],
    "marca": ["10"],
    "cargo": ["100"],
    "percentual": Decimal("0.025"),
}


def _producers() -> Any:
    return MagicMock(
        etapa_alterada=AsyncMock(),
        no_concluido=AsyncMock(),
        sugestao_adaptacao_proposta=AsyncMock(),
    )


def _config(producers: Any) -> dict[str, Any]:
    return {"configurable": {"producers": producers, "sessoes": "sessoes-falsas"}}


def _estado(**sobrescritas: Any) -> AgentState:
    estado: AgentState = {
        "job_id": JOB_ID,
        "regra_id": REGRA_ID,
        "resultado_id": RESULTADO_ID,
        "representacao_regra": {"nucleo": dict(NUCLEO), "especificacoes": []},
    }
    estado.update(sobrescritas)  # type: ignore[typeddict-item]
    return estado


def _totais(monkeypatch: pytest.MonkeyPatch, simulado: str, orcamento: str) -> None:
    monkeypatch.setattr(
        modulo,
        "buscar_totais",
        AsyncMock(
            return_value=TotaisDaSimulacao(
                Decimal(simulado), Decimal(orcamento), baseline=Decimal("480312")
            )
        ),
    )


async def test_propoe_a_alternativa_calculada_sobre_os_totais_apurados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _totais(monkeypatch, "492100", "485000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(), _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    assert proposta.job_id == UUID(JOB_ID)
    assert proposta.regra_origem_id == UUID(REGRA_ID)
    assert proposta.resultado_id == UUID(RESULTADO_ID)
    contrato = proposta.representacao.para_contrato()
    assert contrato["nucleo"]["percentual"] == Decimal("0.0099")
    assert contrato["nucleo"]["loja"] == ["13"]


async def test_a_proposta_sai_no_contrato_oficial(monkeypatch: pytest.MonkeyPatch) -> None:
    _totais(monkeypatch, "492100", "485000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(), _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    payload = simplejson.loads(serializar(proposta), use_decimal=True)
    oficial("sugestao-adaptacao-proposta").validate(payload)


async def test_anuncia_a_etapa_antes_de_propor(monkeypatch: pytest.MonkeyPatch) -> None:
    _totais(monkeypatch, "492100", "485000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(), _config(producers))

    [etapa] = producers.etapa_alterada.await_args.args
    assert etapa == EtapaAlterada(
        job_id=UUID(JOB_ID), etapa="sugestao_adaptacao", status="iniciada"
    )


async def test_conclui_a_trilha_mesmo_sem_alternativa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem margem não há proposta, e a trilha precisa dizer isso em vez de ficar muda."""
    _totais(monkeypatch, "400000", "485000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(), _config(producers))

    producers.sugestao_adaptacao_proposta.assert_not_awaited()
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.no == "sugestao_adaptacao"
    oficial("no-concluido").validate(simplejson.loads(serializar(conclusao), use_decimal=True))


async def test_a_trilha_nao_carrega_a_proposta(monkeypatch: pytest.MonkeyPatch) -> None:
    """A trilha guarda referência, nunca artefato: o conteúdo fica em `regras`."""
    _totais(monkeypatch, "492100", "485000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(), _config(producers))

    [conclusao] = producers.no_concluido.await_args.args
    assert "0.0099" not in serializar(conclusao).decode()


async def test_nao_propoe_quando_o_resultado_nao_tem_totais(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        modulo, "buscar_totais", AsyncMock(side_effect=ResultadoIndisponivelError("sem totais"))
    )
    producers = _producers()

    with pytest.raises(ResultadoIndisponivelError):
        await modulo.suggest_adaptation(_estado(), _config(producers))

    producers.sugestao_adaptacao_proposta.assert_not_awaited()


async def test_regra_com_especificacao_encerra_sem_publicar_alternativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _totais(monkeypatch, "492100", "485000")
    estado = _estado()
    estado["representacao_regra"]["especificacoes"] = [
        {"ref": "elem.1", "construto": "bonus_fixo", "valor": Decimal("250")}
    ]
    producers = _producers()

    atualizacao = await modulo.suggest_adaptation(estado, _config(producers))

    assert atualizacao == {}
    producers.sugestao_adaptacao_proposta.assert_not_awaited()
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.regra_id == UUID(REGRA_ID)
    assert conclusao.conclusao.resumo == modulo.RESUMO_SEM_PROPOSTA
