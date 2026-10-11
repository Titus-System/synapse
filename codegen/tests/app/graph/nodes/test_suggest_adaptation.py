import logging
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson
from prometheus_client import REGISTRY

from app import sugestao_adaptacao
from app.contratos.mensagens import EtapaAlterada
from app.contratos.serializacao import serializar
from app.graph.core.state import AgentState
from app.graph.nodes import suggest_adaptation as modulo
from app.repositorio.resultados import ResultadoIndisponivelError, TotaisDaSimulacao
from app.sugestao_adaptacao import TaxaSimulada
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

# A comissão é 1000 + 40000 * taxa: a original e a primeira alternativa já simuladas.
ORIGINAL = TaxaSimulada(Decimal("0.025"), Decimal("2000"))
PRIMEIRA = TaxaSimulada(Decimal("0.02"), Decimal("1800"))


@pytest.fixture(autouse=True)
def taxas_simuladas(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Por padrão, a cadeia de uma regra que ainda não foi adaptada: só a taxa dela."""
    consulta = AsyncMock(return_value=[TaxaSimulada(Decimal("0.025"), Decimal("492100"))])
    monkeypatch.setattr(modulo, "buscar_taxas_simuladas", consulta)
    return consulta


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


def _da_primeira_alternativa() -> AgentState:
    """O ciclo da primeira alternativa, que simulou 1800 contra o orçamento de 1700."""
    estado = _estado(tentativas_de_taxa=1)
    estado["representacao_regra"]["nucleo"]["percentual"] = Decimal("0.02")
    return estado


def _totais(
    monkeypatch: pytest.MonkeyPatch, simulado: str, orcamento: str, baseline: str = "480312"
) -> AsyncMock:
    consulta = AsyncMock(
        return_value=TotaisDaSimulacao(
            Decimal(simulado), Decimal(orcamento), baseline=Decimal(baseline)
        )
    )
    monkeypatch.setattr(modulo, "buscar_totais", consulta)
    return consulta


def tentativas_contadas() -> dict[tuple[str, str], float]:
    """Todas as amostras da família, inclusive uma combinação de rótulos fora da esperada."""
    return {
        (amostra.labels["tentativa"], amostra.labels["desfecho"]): amostra.value
        for familia in REGISTRY.collect()
        if familia.name == "codegen_sugestao_adaptacao_tentativas"
        for amostra in familia.samples
        if amostra.name.endswith("_total")
    }


def variacao_das_tentativas(antes: dict[tuple[str, str], float]) -> dict[tuple[str, str], float]:
    depois = tentativas_contadas()
    return {
        chave: depois[chave] - antes.get(chave, 0.0)
        for chave in depois
        if depois[chave] != antes.get(chave, 0.0)
    }


def _publicacoes(producers: Any) -> list[tuple[str, Any]]:
    """Os eventos na ordem em que o nó os publicou."""
    return [(nome, args[0]) for nome, args, _ in producers.mock_calls]


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


async def test_a_primeira_proposta_e_a_tentativa_1(monkeypatch: pytest.MonkeyPatch) -> None:
    _totais(monkeypatch, "492100", "485000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(tentativas_de_taxa=0), _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    assert proposta.tentativa == 1


async def test_regra_que_nao_veio_de_sugestao_estima_pelos_totais_mesmo_na_segunda_tentativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O job já tentou uma taxa para outra regra: a conta é do job, mas não há reta a traçar."""
    _totais(monkeypatch, "492100", "485000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(tentativas_de_taxa=1), _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    assert proposta.tentativa == 2
    assert proposta.representacao.para_contrato()["nucleo"]["percentual"] == Decimal("0.0099")


async def test_a_proposta_sai_no_contrato_oficial_com_a_tentativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _totais(monkeypatch, "492100", "485000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(), _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    payload = simplejson.loads(serializar(proposta), use_decimal=True)
    oficial("sugestao-adaptacao-proposta").validate(payload)
    assert payload["tentativa"] == 1


async def test_a_segunda_tentativa_refina_a_taxa_pelas_ja_simuladas(
    monkeypatch: pytest.MonkeyPatch, taxas_simuladas: AsyncMock
) -> None:
    """Pelo baseline (1200) a taxa seria 0,0166; a reta das simuladas dá a que cabe."""
    _totais(monkeypatch, "1800", "1700", baseline="1200")
    taxas_simuladas.return_value = [ORIGINAL, PRIMEIRA]
    producers = _producers()

    await modulo.suggest_adaptation(_da_primeira_alternativa(), _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    assert proposta.tentativa == 2
    assert proposta.regra_origem_id == UUID(REGRA_ID)
    assert proposta.representacao.para_contrato()["nucleo"]["percentual"] == Decimal("0.0175")
    taxas_simuladas.assert_awaited_once_with("sessoes-falsas", UUID(JOB_ID), UUID(REGRA_ID))


async def test_a_terceira_alternativa_que_nao_coube_encerra_sem_quarta_proposta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    totais = _totais(monkeypatch, "1750", "1700", baseline="1200")
    producers = _producers()
    antes = tentativas_contadas()

    atualizacao = await modulo.suggest_adaptation(_estado(tentativas_de_taxa=3), _config(producers))

    assert atualizacao == {}
    producers.sugestao_adaptacao_proposta.assert_not_awaited()
    totais.assert_not_awaited()
    [iniciada, sem_alternativa] = [c.args[0] for c in producers.etapa_alterada.await_args_list]
    assert iniciada.status == "iniciada"
    assert sem_alternativa == EtapaAlterada(
        job_id=UUID(JOB_ID), etapa="sugestao_adaptacao", status="sem_alternativa"
    )
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.conclusao.resumo == modulo.RESUMOS["limite"]
    # A terceira já foi contada como inviável pela decisão; o limite não é outra tentativa.
    assert variacao_das_tentativas(antes) == {}


@pytest.mark.parametrize(
    ("estado", "totais", "anteriores", "desfecho"),
    [
        pytest.param(
            {}, ("400000", "485000"), None, ("1", "sem_margem"), id="sem-margem-na-primeira"
        ),
        pytest.param(
            {"tentativas_de_taxa": 1},
            ("1800", "900"),
            [ORIGINAL, PRIMEIRA],
            ("2", "sem_margem"),
            id="sem-reta-na-segunda",
        ),
        pytest.param(
            {
                "representacao_regra": {
                    "nucleo": {**NUCLEO, "vigencia": {"inicio": "2025-12", "fim": "2025-08"}},
                    "especificacoes": [],
                }
            },
            ("492100", "485000"),
            None,
            ("1", "incoerente"),
            id="incoerente",
        ),
    ],
)
async def test_sem_taxa_a_propor_encerra_a_iteracao_sem_alternativa(
    monkeypatch: pytest.MonkeyPatch,
    taxas_simuladas: AsyncMock,
    estado: dict[str, Any],
    totais: tuple[str, str],
    anteriores: list[TaxaSimulada] | None,
    desfecho: tuple[str, str],
) -> None:
    _totais(monkeypatch, *totais)
    if anteriores is not None:
        taxas_simuladas.return_value = anteriores
    producers = _producers()
    antes = tentativas_contadas()

    await modulo.suggest_adaptation(_estado(**estado), _config(producers))

    producers.sugestao_adaptacao_proposta.assert_not_awaited()
    assert [nome for nome, _ in _publicacoes(producers)] == [
        "etapa_alterada",
        "etapa_alterada",
        "no_concluido",
    ]
    _, (_, sem_alternativa), (_, conclusao) = _publicacoes(producers)
    oficial("etapa-alterada").validate(simplejson.loads(serializar(sem_alternativa)))
    assert sem_alternativa.status == "sem_alternativa"
    _, motivo = desfecho
    assert conclusao.conclusao.resumo == modulo.RESUMOS[motivo]
    assert variacao_das_tentativas(antes) == {desfecho: 1.0}


def test_a_trilha_tem_um_resumo_proprio_para_cada_motivo() -> None:
    """Um motivo novo sem resumo seria uma trilha que conta outra razão, ou uma falha do nó."""
    motivos = {
        valor for nome, valor in vars(sugestao_adaptacao).items() if nome.startswith("MOTIVO_")
    }

    assert set(modulo.RESUMOS) == motivos
    assert len(set(modulo.RESUMOS.values())) == len(motivos)


async def test_publica_a_proposta_entre_a_etapa_e_a_trilha(monkeypatch: pytest.MonkeyPatch) -> None:
    _totais(monkeypatch, "492100", "485000")
    producers = _producers()
    antes = tentativas_contadas()

    await modulo.suggest_adaptation(_estado(), _config(producers))

    assert [nome for nome, _ in _publicacoes(producers)] == [
        "etapa_alterada",
        "sugestao_adaptacao_proposta",
        "no_concluido",
    ]
    [etapa] = producers.etapa_alterada.await_args.args
    assert etapa == EtapaAlterada(
        job_id=UUID(JOB_ID), etapa="sugestao_adaptacao", status="iniciada"
    )
    # O desfecho de uma proposta é o veredito da simulação dela, que a decisão conta.
    assert variacao_das_tentativas(antes) == {}


async def test_nao_conta_o_desfecho_quando_a_trilha_nao_foi_publicada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mensagem volta à fila e o nó roda de novo: contar agora contaria duas vezes."""
    _totais(monkeypatch, "400000", "485000")
    producers = _producers()
    producers.no_concluido.side_effect = RuntimeError("broker fora")
    antes = tentativas_contadas()

    with pytest.raises(RuntimeError):
        await modulo.suggest_adaptation(_estado(), _config(producers))

    assert variacao_das_tentativas(antes) == {}


async def test_conclui_a_trilha_no_contrato_oficial_mesmo_sem_alternativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem margem não há proposta, e a trilha precisa dizer isso em vez de ficar muda."""
    _totais(monkeypatch, "400000", "485000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(), _config(producers))

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


async def test_registra_a_tentativa_e_o_motivo_sem_taxas_nem_totais(
    monkeypatch: pytest.MonkeyPatch, taxas_simuladas: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    _totais(monkeypatch, "1800", "1700", baseline="1200")
    taxas_simuladas.return_value = [ORIGINAL, PRIMEIRA]

    with caplog.at_level("INFO", logger="app.graph.nodes.suggest_adaptation"):
        await modulo.suggest_adaptation(_da_primeira_alternativa(), _config(_producers()))

    [proposta] = [r for r in caplog.records if r.getMessage() == "adaptation proposal published"]
    assert proposta.tentativa == 2
    [conclusao] = [r for r in caplog.records if r.getMessage() == "node conclusion published"]
    assert conclusao.motivo == "proposta"
    assert conclusao.tentativas_de_taxa == 1
    # Só os campos que o nó acrescenta: os do `LogRecord` (horário, linha) trariam números ao acaso.
    padrao = logging.makeLogRecord({}).__dict__.keys()
    extras = repr(
        [{k: v for k, v in r.__dict__.items() if k not in padrao} for r in caplog.records]
    )
    for valor in ("0.0175", "0.02", "0.025", "1800", "1700", "1200", "2000"):
        assert valor not in extras


async def test_registra_o_fim_da_iteracao(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _totais(monkeypatch, "1750", "1700")

    with caplog.at_level("INFO", logger="app.graph.nodes.suggest_adaptation"):
        await modulo.suggest_adaptation(_estado(tentativas_de_taxa=3), _config(_producers()))

    [fim] = [
        r
        for r in caplog.records
        if r.getMessage() == "adaptation iteration ended without alternative"
    ]
    assert fim.motivo == "limite"
    assert fim.tentativas_de_taxa == 3


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
    """A decisão já não a manda para cá; se chegar, a iteração termina sem alternativa."""
    _totais(monkeypatch, "492100", "485000")
    estado = _estado()
    estado["representacao_regra"]["especificacoes"] = [
        {"ref": "elem.1", "construto": "bonus_fixo", "valor": Decimal("250")}
    ]
    producers = _producers()

    atualizacao = await modulo.suggest_adaptation(estado, _config(producers))

    assert atualizacao == {}
    producers.sugestao_adaptacao_proposta.assert_not_awaited()
    assert producers.etapa_alterada.await_args.args[0].status == "sem_alternativa"
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.regra_id == UUID(REGRA_ID)
    assert conclusao.conclusao.resumo == modulo.RESUMOS["nao_suportada"]
