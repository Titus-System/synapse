from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson

from app.contratos.mensagens import EtapaAlterada
from app.contratos.serializacao import serializar
from app.graph.core.state import AgentState
from app.graph.nodes import decision as modulo
from tests.app.test_mensageria import oficial

JOB_ID = str(uuid4())
REGRA_ID = str(uuid4())
RESULTADO_ID = str(uuid4())


@pytest.fixture(autouse=True)
def consulta_sugestao(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    consulta = AsyncMock(return_value=False)
    monkeypatch.setattr(modulo, "tem_sugestao", consulta)
    return consulta


def _producers() -> Any:
    return MagicMock(etapa_alterada=AsyncMock(), no_concluido=AsyncMock())


def _config(producers: Any) -> dict[str, Any]:
    return {"configurable": {"producers": producers, "sessoes": None}}


def _estado(**sobrescritas: Any) -> AgentState:
    estado: AgentState = {
        "job_id": JOB_ID,
        "regra_id": REGRA_ID,
        "resultado_id": RESULTADO_ID,
        "status_simulacao": "sucesso",
        "veredito": "inviavel",
    }
    estado.update(sobrescritas)  # type: ignore[typeddict-item]
    return estado


async def test_encaminha_para_a_sugestao_quando_a_regra_nao_coube() -> None:
    producers = _producers()

    update = await modulo.decision(_estado(), _config(producers))

    assert update == {"encaminhamento": "sugestao_adaptacao"}
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.conclusao.encaminhamento == "sugestao_adaptacao"


@pytest.mark.parametrize(
    "estado",
    [
        {"veredito": "viavel"},
        {"veredito": "indeterminado"},
        {"veredito": None, "status_simulacao": "erro_codigo"},
    ],
    ids=["viavel", "indeterminado", "sem_veredito"],
)
async def test_encerra_o_fluxo_nos_demais_desfechos(estado: dict[str, Any]) -> None:
    """Só a inviabilidade por orçamento rende adaptação; o resto não tem o que propor."""
    producers = _producers()

    update = await modulo.decision(_estado(**estado), _config(producers))

    assert update == {"encaminhamento": "fim"}
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.conclusao.encaminhamento == "fim"


async def test_publica_a_etapa_e_a_trilha_no_contrato_oficial() -> None:
    producers = _producers()

    await modulo.decision(_estado(), _config(producers))

    [etapa] = producers.etapa_alterada.await_args.args
    assert etapa == EtapaAlterada(job_id=UUID(JOB_ID), etapa="decisao", status="iniciada")
    [conclusao] = producers.no_concluido.await_args.args
    oficial("no-concluido").validate(simplejson.loads(serializar(conclusao), use_decimal=True))
    assert conclusao.no == "decisao"
    assert str(conclusao.regra_id) == REGRA_ID


async def test_o_resumo_da_trilha_nao_repete_o_veredito() -> None:
    """`resultados_simulacao.veredito` já registra isso; a trilha guarda o que o nó decidiu."""
    producers = _producers()

    await modulo.decision(_estado(), _config(producers))

    [conclusao] = producers.no_concluido.await_args.args
    assert "inviável" not in conclusao.conclusao.resumo.lower()
    assert "viável" not in conclusao.conclusao.resumo.lower()


async def test_o_mesmo_resultado_rende_sempre_o_mesmo_evento_de_trilha() -> None:
    """Reexecução do nó não pode duplicar a linha da trilha na api."""
    producers = _producers()

    await modulo.decision(_estado(), _config(producers))
    await modulo.decision(_estado(), _config(producers))

    primeiro, segundo = producers.no_concluido.await_args_list
    assert primeiro.args[0].evento_id == segundo.args[0].evento_id


async def test_recusa_decidir_sem_o_resultado_da_simulacao() -> None:
    estado = _estado()
    del estado["resultado_id"]  # type: ignore[misc]

    with pytest.raises(modulo.DecisaoSemResultadoError):
        await modulo.decision(estado, _config(_producers()))


async def test_nao_propoe_outra_adaptacao_no_mesmo_job(consulta_sugestao: AsyncMock) -> None:
    consulta_sugestao.return_value = True
    update = await modulo.decision(_estado(), _config(_producers()))
    assert update == {"encaminhamento": "fim"}


async def test_falha_com_veredito_antigo_nao_gera_sugestao(consulta_sugestao: AsyncMock) -> None:
    update = await modulo.decision(_estado(status_simulacao="erro_codigo"), _config(_producers()))
    assert update == {"encaminhamento": "fim"}
    consulta_sugestao.assert_not_awaited()
