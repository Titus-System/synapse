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


def _detalhamento(simulado: Decimal, fora: Decimal) -> dict[str, Any]:
    """Uma linha da loja 14, que a regra não alcança, com `fora`, e uma da loja 13, com o resto."""

    def linha(loja: str, comissao: Decimal, contribuicoes: dict[str, Decimal]) -> dict[str, Any]:
        return {
            "cod_loja": loja,
            "cod_marca": "10",
            "cod_cargo": "100",
            "comissao_baseline": comissao - sum(contribuicoes.values(), Decimal(0)),
            "comissao_simulada": comissao,
            "diferenca": sum(contribuicoes.values(), Decimal(0)),
            "contribuicoes": contribuicoes,
        }

    alcancada = simulado - fora
    return {
        "2025-11": {
            "MATRIC-14": linha("14", fora, {}),
            "MATRIC-13": linha("13", alcancada, {"nucleo.percentual": alcancada}),
        }
    }


def _totais(
    monkeypatch: pytest.MonkeyPatch, simulado: str, orcamento: str, fora: str | None = "480312"
) -> AsyncMock:
    """O resultado como o worker o grava; `fora` None é o resultado anterior ao detalhamento."""
    linhas = None if fora is None else _detalhamento(Decimal(simulado), Decimal(fora))
    consulta = AsyncMock(
        return_value=TotaisDaSimulacao(Decimal(simulado), Decimal(orcamento), linhas=linhas)
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


async def test_com_comissao_atual_no_escopo_a_primeira_taxa_e_a_que_cabe_no_orcamento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A regra troca 2% por 2,5% nas vendas de R$ 40.000 da loja 13, e a loja 14, fora dela, fica
    com R$ 1.000: a comissão é 1000 + 40000 * taxa, e cabe até 2,25% em R$ 1.900. Estimada sobre o
    baseline inteiro (R$ 1.800), a taxa sairia 1,25%, abaixo da que a loja 13 já recebe."""
    _totais(monkeypatch, "2000", "1900", fora="1000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(), _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    assert proposta.representacao.para_contrato()["nucleo"]["percentual"] == Decimal("0.0225")


async def test_parte_fixa_acima_do_orcamento_ainda_propoe_a_alternativa_pela_sondagem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A loja que a regra não alcança já custa mais que o orçamento, e nenhuma taxa cabe. A
    alternativa ainda é simulada, proporcional ao orçamento, para o usuário vê-la e ver o motivo;
    a reta do refinamento encerra a iteração na tentativa seguinte."""
    _totais(monkeypatch, "2200", "900", "1000")
    producers = _producers()

    await modulo.suggest_adaptation(_estado(), _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    assert proposta.representacao.para_contrato()["nucleo"]["percentual"] == Decimal("0.0102")


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
    """Pela parte fixa (1200) a taxa seria 0,0166; a reta das simuladas dá a que cabe."""
    _totais(monkeypatch, "1800", "1700", fora="1200")
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
    totais = _totais(monkeypatch, "1750", "1700", fora="1200")
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
    totais: tuple[str, ...],
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
    _totais(monkeypatch, "1800", "1700", fora="1200")
    taxas_simuladas.return_value = [ORIGINAL, PRIMEIRA]

    with caplog.at_level("INFO", logger="app.graph.nodes.suggest_adaptation"):
        await modulo.suggest_adaptation(_da_primeira_alternativa(), _config(_producers()))

    [proposta] = [r for r in caplog.records if r.getMessage() == "adaptation proposal published"]
    assert proposta.tentativa == 2
    assert proposta.metodo == "refinamento"
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


async def test_sem_detalhamento_propoe_a_sondagem_e_registra_o_metodo(
    monkeypatch: pytest.MonkeyPatch, taxas_simuladas: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Um resultado gravado antes do detalhamento: 10% na meta, orçamento abaixo do baseline. Sem
    as linhas, a parte fixa é zero (T-283)."""
    _totais(monkeypatch, "7400123.65", "5000000", fora=None)
    taxas_simuladas.return_value = [TaxaSimulada(Decimal("0.1"), Decimal("7400123.65"))]
    estado = _estado()
    estado["representacao_regra"]["nucleo"]["percentual"] = Decimal("0.1")
    producers = _producers()

    with caplog.at_level("INFO", logger="app.graph.nodes.suggest_adaptation"):
        await modulo.suggest_adaptation(estado, _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    assert proposta.tentativa == 1
    assert proposta.representacao.para_contrato()["nucleo"]["percentual"] == Decimal("0.0675")
    assert [e.status for e in (c.args[0] for c in producers.etapa_alterada.await_args_list)] == [
        "iniciada"
    ]
    [registro] = [r for r in caplog.records if r.getMessage() == "adaptation proposal published"]
    assert (registro.tentativa, registro.metodo) == (1, "sondagem")
    padrao = logging.makeLogRecord({}).__dict__.keys()
    extras = repr(
        [{k: v for k, v in r.__dict__.items() if k not in padrao} for r in caplog.records]
    )
    for valor in ("0.0675", "0.1", "7400123", "5000000", "5730771"):
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


def _com_taxas_por_cargo_e_bonus() -> AgentState:
    """A forma do caso relatado: taxas por cargo e um bônus condicionado, em texto livre."""
    nucleo = {chave: valor for chave, valor in NUCLEO.items() if chave != "percentual"}
    return _estado(
        representacao_regra={
            "nucleo": {
                **nucleo,
                "cargo": ["100", "150"],
                "taxas_por_cargo": [
                    {"cargo": "100", "percentual": Decimal("0.03")},
                    {"cargo": "150", "percentual": Decimal("0.05")},
                ],
            },
            "especificacoes": [
                {
                    "ref": "elem.1",
                    "construto": "generico",
                    "descricao": "Bônus de R$ 350 para quem vender R$ 40.000 no mês.",
                }
            ],
        }
    )


async def test_propoe_para_regra_com_taxas_por_cargo_e_bonus_no_contrato_oficial(
    monkeypatch: pytest.MonkeyPatch, taxas_simuladas: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    _totais(monkeypatch, "492100", "485000")
    taxas_simuladas.return_value = [TaxaSimulada(Decimal("0.03"), Decimal("492100"))]
    estado = _com_taxas_por_cargo_e_bonus()
    producers = _producers()
    antes = tentativas_contadas()

    with caplog.at_level("INFO", logger="app.graph.nodes.suggest_adaptation"):
        await modulo.suggest_adaptation(estado, _config(producers))

    [proposta] = producers.sugestao_adaptacao_proposta.await_args.args
    payload = simplejson.loads(serializar(proposta), use_decimal=True)
    oficial("sugestao-adaptacao-proposta").validate(payload)
    assert payload["representacao"]["nucleo"]["taxas_por_cargo"] == [
        {"cargo": "100", "percentual": Decimal("0.0119")},
        {"cargo": "150", "percentual": Decimal("0.0198")},
    ]
    assert (
        payload["representacao"]["especificacoes"]
        == (estado["representacao_regra"]["especificacoes"])
    )
    [registro] = [r for r in caplog.records if r.getMessage() == "adaptation proposal published"]
    assert (registro.no, registro.tentativa, registro.metodo, registro.taxas_ajustadas) == (
        "sugestao_adaptacao",
        1,
        "estimativa",
        2,
    )
    padrao = logging.makeLogRecord({}).__dict__.keys()
    extras = repr(
        [{k: v for k, v in r.__dict__.items() if k not in padrao} for r in caplog.records]
    )
    for valor in ("0.0119", "0.0198", "0.03", "0.05", "R$ 350", "492100", "485000"):
        assert valor not in extras
    # A proposta ainda não é desfecho: quem conta o veredito dela é a decisão.
    assert variacao_das_tentativas(antes) == {}


async def test_regra_sem_taxa_positiva_encerra_sem_publicar_alternativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _totais(monkeypatch, "492100", "485000")
    estado = _estado()
    estado["representacao_regra"]["nucleo"]["percentual"] = Decimal("0")
    producers = _producers()
    antes = tentativas_contadas()

    atualizacao = await modulo.suggest_adaptation(estado, _config(producers))

    assert atualizacao == {}
    producers.sugestao_adaptacao_proposta.assert_not_awaited()
    assert producers.etapa_alterada.await_args.args[0].status == "sem_alternativa"
    [conclusao] = producers.no_concluido.await_args.args
    assert conclusao.regra_id == UUID(REGRA_ID)
    assert conclusao.conclusao.resumo == modulo.RESUMOS["nao_suportada"]
    assert variacao_das_tentativas(antes) == {("1", "nao_suportada"): 1.0}
