from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson
from prometheus_client import REGISTRY

from app.config import get_settings
from app.contratos.mensagens import EtapaAlterada
from app.contratos.serializacao import serializar
from app.correcao_codigo import LIMITE_DE_CODIGOS_POR_VERSAO, FalhaDaExecucao
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


CODIGO_ID = str(uuid4())


@pytest.fixture(autouse=True)
def consulta_tentativas(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    consulta = AsyncMock(return_value=TentativasDeTaxa(feitas=0, regra_e_tentativa=False))
    monkeypatch.setattr(modulo, "contar_tentativas", consulta)
    return consulta


@pytest.fixture(autouse=True)
def consulta_posicao(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """O último código da versão, salvo quando o teste diz outra posição."""
    consulta = AsyncMock(return_value=LIMITE_DE_CODIGOS_POR_VERSAO)
    monkeypatch.setattr(modulo, "posicao_do_codigo", consulta)
    return consulta


@pytest.fixture(autouse=True)
def consulta_falha(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    consulta = AsyncMock(
        return_value=FalhaDaExecucao(
            status="erro_codigo",
            diagnostico={
                "causa": "excecao",
                "falha": {"tipo": "TypeError", "mensagem": "MENSAGEM_PRIVADA", "traceback": "TB"},
            },
        )
    )
    monkeypatch.setattr(modulo, "buscar_falha_da_execucao", consulta)
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
        "codigo_gerado_id": CODIGO_ID,
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


async def test_regra_com_taxas_por_cargo_e_especificacoes_tambem_vai_a_sugestao() -> None:
    """Quem decide se há taxa a reduzir é a sugestão, para qualquer estrutura de regra."""
    estado = _estado(
        representacao_regra={
            "nucleo": {"taxas_por_cargo": [{"cargo": "100", "percentual": Decimal("0.03")}]},
            "especificacoes": [
                {"ref": "elem.1", "construto": "generico", "descricao": "Bônus condicionado."}
            ],
        }
    )

    update = await modulo.decision(estado, _config(_producers()))

    assert update == {"encaminhamento": "sugestao_adaptacao", "tentativas_de_taxa": 0}


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


def _amostras(familia: str, rotulos: tuple[str, str]) -> dict[tuple[str, str], float]:
    return {
        (amostra.labels[rotulos[0]], amostra.labels[rotulos[1]]): amostra.value
        for coletada in REGISTRY.collect()
        if coletada.name == familia
        for amostra in coletada.samples
        if amostra.name.endswith("_total")
    }


def _variacao(familia: str, rotulos: tuple[str, str], antes: dict[tuple[str, str], float]) -> dict:
    depois = _amostras(familia, rotulos)
    return {k: depois[k] - antes.get(k, 0.0) for k in depois if depois[k] != antes.get(k, 0.0)}


PEDIDOS = ("codegen_correcoes_codigo", ("tentativa", "causa"))
DESFECHOS = ("codegen_correcao_codigo_desfechos", ("tentativa", "desfecho"))


@pytest.mark.parametrize("status", ["erro_codigo", "assercao_violada"])
@pytest.mark.parametrize("posicao", [1, 2])
async def test_falha_do_codigo_antes_do_limite_volta_a_geracao_para_a_correcao(
    status: str, posicao: int, consulta_posicao: AsyncMock, consulta_falha: AsyncMock
) -> None:
    consulta_posicao.return_value = posicao
    producers = _producers()

    update = await modulo.decision(
        _estado(status_simulacao=status, veredito=None), _config(producers)
    )

    assert update == {"encaminhamento": "correcao_codigo", "correcao_pendente": posicao + 1}
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.conclusao.encaminhamento == "correcao_codigo"
    assert conclusao.conclusao.resumo == "Fluxo encaminhado para a correção do código gerado."
    consulta_posicao.assert_awaited_once_with(None, UUID(JOB_ID), UUID(CODIGO_ID))
    consulta_falha.assert_awaited_once_with(None, UUID(JOB_ID), UUID(RESULTADO_ID))


async def test_falha_do_ultimo_codigo_da_versao_encerra_o_fluxo(
    consulta_posicao: AsyncMock, consulta_falha: AsyncMock
) -> None:
    """A `api` conta a mesma posição e leva o job a `erro` nesse resultado."""
    consulta_posicao.return_value = LIMITE_DE_CODIGOS_POR_VERSAO
    antes = _amostras(*PEDIDOS)

    update = await modulo.decision(
        _estado(status_simulacao="erro_codigo", veredito=None), _config(_producers())
    )

    assert update == {"encaminhamento": "fim"}
    consulta_falha.assert_not_awaited()
    assert _variacao(*PEDIDOS, antes) == {}


async def test_erro_de_infraestrutura_nao_volta_ao_modelo(consulta_posicao: AsyncMock) -> None:
    """Outro código não resolve uma falha do ambiente."""
    consulta_posicao.return_value = 1

    update = await modulo.decision(
        _estado(status_simulacao="erro_infra", veredito=None), _config(_producers())
    )

    assert update == {"encaminhamento": "fim"}
    consulta_posicao.assert_not_awaited()


async def test_codigo_que_nao_esta_entre_os_gerados_falha_o_job(
    consulta_posicao: AsyncMock,
) -> None:
    consulta_posicao.return_value = 0
    producers = _producers()

    with pytest.raises(modulo.CodigoDesconhecidoError):
        await modulo.decision(
            _estado(status_simulacao="erro_codigo", veredito=None), _config(producers)
        )

    producers.no_concluido.assert_not_awaited()


async def test_conta_o_pedido_de_correcao_pela_causa_e_registra_sem_a_mensagem(
    consulta_posicao: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    consulta_posicao.return_value = 1
    antes = _amostras(*PEDIDOS)

    with caplog.at_level("INFO", logger="app.graph.nodes.decision"):
        await modulo.decision(
            _estado(status_simulacao="erro_codigo", veredito=None), _config(_producers())
        )

    assert _variacao(*PEDIDOS, antes) == {("2", "excecao"): 1.0}
    [publicado] = [r for r in caplog.records if r.getMessage() == "node conclusion published"]
    assert publicado.encaminhamento == "correcao_codigo"
    assert publicado.causa == "excecao"
    assert publicado.posicao_do_codigo == 1
    assert "MENSAGEM_PRIVADA" not in repr([record.__dict__ for record in caplog.records])


@pytest.mark.parametrize(("status", "desfecho"), [("sucesso", "sucesso"), ("erro_infra", "erro")])
async def test_conta_o_desfecho_do_codigo_corrigido_e_limpa_a_pendencia(
    status: str, desfecho: str
) -> None:
    antes = _amostras(*DESFECHOS)

    update = await modulo.decision(
        _estado(status_simulacao=status, veredito="viavel", correcao_pendente=2),
        _config(_producers()),
    )

    assert _variacao(*DESFECHOS, antes) == {("2", desfecho): 1.0}
    assert update["correcao_pendente"] is None


async def test_codigo_corrigido_que_falha_de_novo_pede_a_proxima_correcao(
    consulta_posicao: AsyncMock,
) -> None:
    consulta_posicao.return_value = 2
    antes = _amostras(*DESFECHOS)

    update = await modulo.decision(
        _estado(status_simulacao="assercao_violada", veredito=None, correcao_pendente=2),
        _config(_producers()),
    )

    assert _variacao(*DESFECHOS, antes) == {("2", "erro"): 1.0}
    assert update == {"encaminhamento": "correcao_codigo", "correcao_pendente": 3}
