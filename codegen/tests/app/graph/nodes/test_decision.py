from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson

from app.config import get_settings
from app.contratos.mensagens import EtapaAlterada
from app.contratos.serializacao import serializar
from app.graph.core.state import AgentState
from app.graph.nodes import decision as modulo
from app.repositorio.regras import TentativasDeTaxa
from tests.app.graph.nodes.test_suggest_adaptation import (
    tentativas_contadas,
    variacao_das_tentativas,
)
from tests.app.test_mensageria import oficial

JOB_ID = str(uuid4())
REGRA_ID = str(uuid4())
RESULTADO_ID = str(uuid4())


@pytest.fixture(autouse=True)
def consulta_tentativas(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    consulta = AsyncMock(return_value=TentativasDeTaxa(feitas=0, regra_e_tentativa=False))
    monkeypatch.setattr(modulo, "contar_tentativas", consulta)
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
        "representacao_regra": {
            "nucleo": {"percentual": Decimal("0.025")},
            "especificacoes": [],
        },
    }
    estado.update(sobrescritas)  # type: ignore[typeddict-item]
    return estado


async def test_encaminha_para_a_sugestao_quando_a_regra_nao_coube(
    consulta_tentativas: AsyncMock,
) -> None:
    producers = _producers()

    update = await modulo.decision(_estado(), _config(producers))

    assert update == {"encaminhamento": "sugestao_adaptacao", "tentativas_de_taxa": 0}
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.conclusao.encaminhamento == "sugestao_adaptacao"
    consulta_tentativas.assert_awaited_once_with(None, UUID(JOB_ID), UUID(REGRA_ID))


@pytest.mark.parametrize("feitas", [1, 2, 3])
async def test_a_alternativa_que_nao_coube_tambem_vai_a_sugestao_com_a_conta_das_tentativas(
    feitas: int, consulta_tentativas: AsyncMock
) -> None:
    """Inclusive a terceira: o limite é aplicado pela sugestão, que anuncia o fim (T-271)."""
    consulta_tentativas.return_value = TentativasDeTaxa(feitas=feitas, regra_e_tentativa=True)

    update = await modulo.decision(_estado(), _config(_producers()))

    assert update == {"encaminhamento": "sugestao_adaptacao", "tentativas_de_taxa": feitas}


async def test_regra_com_especificacoes_nao_vai_a_sugestao() -> None:
    estado = _estado()
    estado["representacao_regra"]["especificacoes"] = [
        {"ref": "elem.1", "construto": "bonus_fixo", "valor": Decimal("250")}
    ]

    update = await modulo.decision(estado, _config(_producers()))

    assert update["encaminhamento"] == "fim"


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

    assert update["encaminhamento"] == "fim"
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.conclusao.encaminhamento == "fim"


async def test_encerra_sem_sugestao_o_sucesso_sem_veredito_do_job_sem_orcamento(
    consulta_tentativas: AsyncMock,
) -> None:
    """Sem orçamento o worker devolve `sucesso` sem veredito (T-281), e a retomada não grava a
    chave. As duas sugestões dependem do orçamento, então não há o que propor."""
    producers = _producers()
    estado = _estado()
    del estado["veredito"]

    update = await modulo.decision(estado, _config(producers))

    assert update == {"encaminhamento": "fim"}
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.conclusao.encaminhamento == "fim"
    consulta_tentativas.assert_not_awaited()


@pytest.mark.parametrize(
    ("parametros", "com_orcamento", "com_meta_venda"),
    [
        ({"orcamento": "485000.10", "meta_venda": "26000000.77"}, True, True),
        ({}, False, False),
    ],
    ids=["com-orcamento-e-meta", "sem-orcamento-e-meta"],
)
async def test_registra_o_encaminhamento_e_a_presenca_do_orcamento_e_da_meta_sem_os_valores(
    parametros: dict[str, str],
    com_orcamento: bool,
    com_meta_venda: bool,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # O encaminhamento para a busca da meta maior tem testes próprios (`test_busca_meta.py`).
    monkeypatch.setattr(get_settings(), "BUSCA_META_ENABLED", False)
    estado = _estado(veredito="viavel", **parametros)

    with caplog.at_level("INFO", logger="app.graph.nodes.decision"):
        await modulo.decision(estado, _config(_producers()))

    [publicado] = [r for r in caplog.records if r.getMessage() == "node conclusion published"]
    assert publicado.encaminhamento == "fim"
    assert publicado.com_orcamento is com_orcamento
    assert publicado.com_meta_venda is com_meta_venda
    logs = repr([record.__dict__ for record in caplog.records])
    for valor in ("485000.10", "485000.1", "26000000.77"):
        assert valor not in logs


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


async def test_falha_com_veredito_antigo_nao_gera_sugestao(consulta_tentativas: AsyncMock) -> None:
    update = await modulo.decision(_estado(status_simulacao="erro_codigo"), _config(_producers()))
    assert update == {"encaminhamento": "fim"}
    consulta_tentativas.assert_not_awaited()


@pytest.mark.parametrize("veredito", ["viavel", "inviavel", "indeterminado"])
async def test_conta_o_desfecho_da_alternativa_simulada(
    veredito: str, consulta_tentativas: AsyncMock
) -> None:
    consulta_tentativas.return_value = TentativasDeTaxa(feitas=2, regra_e_tentativa=True)
    antes = tentativas_contadas()

    await modulo.decision(_estado(veredito=veredito), _config(_producers()))

    assert variacao_das_tentativas(antes) == {("2", veredito): 1.0}


async def test_a_regra_que_nao_veio_de_sugestao_nao_e_uma_tentativa_e_nao_conta(
    consulta_tentativas: AsyncMock,
) -> None:
    """Uma correção depois de uma sugestão: o job já tentou uma taxa, mas não esta regra."""
    consulta_tentativas.return_value = TentativasDeTaxa(feitas=1, regra_e_tentativa=False)
    antes = tentativas_contadas()

    await modulo.decision(_estado(veredito="viavel"), _config(_producers()))

    assert variacao_das_tentativas(antes) == {}


async def test_nao_conta_o_desfecho_quando_a_trilha_nao_foi_publicada(
    consulta_tentativas: AsyncMock,
) -> None:
    """A mensagem volta à fila e o nó roda de novo: contar agora contaria duas vezes."""
    consulta_tentativas.return_value = TentativasDeTaxa(feitas=1, regra_e_tentativa=True)
    producers = _producers()
    producers.no_concluido.side_effect = RuntimeError("broker fora")
    antes = tentativas_contadas()

    with pytest.raises(RuntimeError):
        await modulo.decision(_estado(veredito="viavel"), _config(producers))

    assert variacao_das_tentativas(antes) == {}


async def test_registra_a_conta_das_tentativas(
    consulta_tentativas: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    consulta_tentativas.return_value = TentativasDeTaxa(feitas=1, regra_e_tentativa=True)

    with caplog.at_level("INFO", logger="app.graph.nodes.decision"):
        await modulo.decision(_estado(), _config(_producers()))

    [publicado] = [r for r in caplog.records if r.getMessage() == "node conclusion published"]
    assert publicado.tentativas_de_taxa == 1
    assert publicado.encaminhamento == "sugestao_adaptacao"
