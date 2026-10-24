import logging
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import simplejson
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker
from prometheus_client.parser import text_string_to_metric_families

from app.core.logger import FormatadorJson, ManipuladorFilaContexto
from app.extracao.construtos.generico import DESCRICAO_SEM_LASTRO
from app.nos.codigos_conflito import CodigoConflito
from app.repositorio.regras import RegraInvalidaError, buscar_regra
from app.representacao_regra import RepresentacaoRegra
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.graph.test_validacao_principal import amostra
from tests.app.repositorio.test_regras import _sessionmaker
from tests.app.test_mensageria import CONTRATOS, exemplo

METRICA = "validacao_conflitos_total"
EXEMPLOS = CONTRATOS / "examples/domain"


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> ConfirmacaoFalsa:
    return ConfirmacaoFalsa(monkeypatch)


@pytest.fixture
def logs() -> Any:
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


def _faixa_invertida() -> dict[str, Any]:
    return {
        "ref": "elem.1",
        "construto": "faixa_valor",
        "limite_inferior": 50000,
        "limite_superior": 40000,
        "efeito": {"tipo": "bonus_fixo", "valor": 3500},
    }


def _regra(
    nucleo: dict[str, Any] | None = None, especificacoes: list[dict[str, Any]] | None = None
) -> RepresentacaoRegra:
    return RepresentacaoRegra.model_validate(
        {
            "nucleo": {
                "loja": [],
                "marca": [],
                "cargo": [],
                "percentual": Decimal("0.025"),
                **(nucleo or {}),
            },
            "especificacoes": especificacoes or [],
        }
    )


# `limiar_sem_escopo` fica de fora: `load_rule` recusa a condição sem escopo antes da validação.
_ALCANCAVEIS: list[tuple[CodigoConflito, RepresentacaoRegra]] = [
    (
        CodigoConflito.PERCENTUAL_AUSENTE,
        RepresentacaoRegra.model_validate(
            {"nucleo": {"loja": [], "marca": [], "cargo": []}, "especificacoes": []}
        ),
    ),
    (CodigoConflito.PERCENTUAL_NEGATIVO, _regra({"percentual": Decimal("-0.01")})),
    (
        CodigoConflito.VIGENCIA_INVERTIDA,
        _regra({"vigencia": {"inicio": "2025-11", "fim": "2025-08"}}),
    ),
    (
        CodigoConflito.EXCLUSAO_REPETIDA,
        _regra(
            {"cargo": ["100", "150"]},
            [{"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}],
        ),
    ),
    (CodigoConflito.FAIXA_INVERTIDA, _regra(especificacoes=[_faixa_invertida()])),
    (
        CodigoConflito.JANELA_INVERTIDA,
        _regra(
            especificacoes=[
                {
                    "ref": "elem.1",
                    "construto": "janela_datas",
                    "data_inicial": "2025-11-24",
                    "data_final": "2025-11-20",
                    "efeito": {"tipo": "acrescimo_pct", "valor": Decimal("0.01")},
                }
            ]
        ),
    ),
    (
        CodigoConflito.ELEMENTO_SEM_LASTRO,
        _regra(
            especificacoes=[
                {"ref": "elem.1", "construto": "generico", "descricao": DESCRICAO_SEM_LASTRO}
            ]
        ),
    ),
]


async def _processar(ambiente: ConfirmacaoFalsa, regra: RepresentacaoRegra) -> dict[str, Any]:
    payload = (exemplo("parametros-confirmados") | {"meta_venda": Decimal("12000000")}) | {
        "job_id": str(uuid4()),
        "regra_id": str(uuid4()),
    }
    ambiente.buscar_regra.return_value = regra
    await ambiente.consumer.receber(mensagem(payload))
    return payload


def _contagens(texto: str) -> dict[str, float]:
    return {c.value: amostra(texto, METRICA, {"codigo": c.value}) for c in CodigoConflito}


@pytest.mark.parametrize(("codigo", "regra"), _ALCANCAVEIS, ids=[c.value for c, _ in _ALCANCAVEIS])
async def test_regra_barrada_pelo_grafo_conta_o_conflito_com_o_codigo_correto(
    ambiente: ConfirmacaoFalsa,
    cliente: AsyncClient,
    codigo: CodigoConflito,
    regra: RepresentacaoRegra,
) -> None:
    antes = _contagens((await cliente.get("/metrics")).text)

    payload = await _processar(ambiente, regra)

    depois = _contagens((await cliente.get("/metrics")).text)
    assert (await ambiente.estado(payload)).values["regra_liberada"] is False
    assert ambiente.modelo.seen_messages == []
    assert ambiente.banco.linhas == {}
    assert {k: depois[k] - antes[k] for k in depois} == {
        c.value: 1.0 if c is codigo else 0.0 for c in CodigoConflito
    }


async def test_regra_com_dois_conflitos_conta_os_dois_codigos_e_uma_regra_barrada(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient
) -> None:
    regra = _regra({"percentual": Decimal("-0.01")}, [_faixa_invertida()])
    antes = (await cliente.get("/metrics")).text

    await _processar(ambiente, regra)

    depois = (await cliente.get("/metrics")).text
    delta = {
        c: _contagens(depois)[c] - _contagens(antes)[c] for c in (c.value for c in CodigoConflito)
    }
    assert delta["percentual_negativo"] == 1
    assert delta["faixa_invertida"] == 1
    assert sum(delta.values()) == 2
    barradas = {"resultado": "barrada"}
    nome = "codegen_validacao_dominio_resultados_total"
    assert amostra(depois, nome, barradas) - amostra(antes, nome, barradas) == 1


@pytest.mark.parametrize(
    "arquivo", ["representacao-regra-elementos", "representacao-regra-generico"]
)
async def test_exemplos_com_escopo_completado_sao_liberados_sem_conflito(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient, arquivo: str
) -> None:
    exemplo_regra = simplejson.loads((EXEMPLOS / f"{arquivo}.json").read_bytes(), use_decimal=True)
    exemplo_regra["nucleo"] = {"loja": [], "marca": [], "cargo": [], **exemplo_regra["nucleo"]}
    antes = _contagens((await cliente.get("/metrics")).text)

    payload = await _processar(ambiente, RepresentacaoRegra.model_validate(exemplo_regra))

    assert (await ambiente.estado(payload)).values["regra_liberada"] is True
    assert _contagens((await cliente.get("/metrics")).text) == antes


async def test_log_da_regra_barrada_traz_codigos_e_referencias_sem_motivo(
    ambiente: ConfirmacaoFalsa, logs: list[dict[str, Any]]
) -> None:
    regra = _regra({"percentual": Decimal("-0.01")}, [_faixa_invertida()])

    payload = await _processar(ambiente, regra)

    (final,) = [
        log
        for log in logs
        if log.get("no") == "validacao_dominio" and log["message"] == "domain validation finished"
    ]
    assert final["job_id"] == payload["job_id"]
    assert final["extra"] == {
        "resultado": "barrada",
        "quantidade_conflitos": 2,
        "elementos": ["nucleo.percentual", "elem.1"],
        "codigos": ["percentual_negativo", "faixa_invertida"],
    }
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    for log in logs:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(log)
    serializados = simplejson.dumps(logs)
    for privado in ("limite inferior", "percentual negativo", "50000", "40000"):
        assert privado not in serializados


async def test_criterio_sem_lastro_da_versao_extraida_pausa_conta_o_codigo_e_loga_sem_motivo(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    regra = RepresentacaoRegra.model_validate(
        {"nucleo": {"marca": [], "cargo": [], "percentual": Decimal("0.01")}, "especificacoes": []}
    )
    ambiente.nucleo_sem_lastro.return_value = frozenset({"loja"})
    antes = _contagens((await cliente.get("/metrics")).text)

    payload = await _processar(ambiente, regra)

    ambiente.nucleo_sem_lastro.assert_awaited_once_with(
        ambiente.banco, UUID(payload["job_id"]), UUID(payload["regra_id"])
    )
    motivo = (
        "escopo de loja citado sem código reconhecido; indique os destinatários ou declare todos"
    )
    assert ambiente.publicacoes[-1][1]["conflitos"] == [
        {"elementos": ["nucleo.loja"], "motivo": motivo}
    ]
    assert "executar-codigo" not in [nome for nome, _ in ambiente.publicacoes]
    depois = _contagens((await cliente.get("/metrics")).text)
    assert {k: depois[k] - antes[k] for k in depois} == {
        c.value: 1.0 if c is CodigoConflito.NUCLEO_SEM_LASTRO else 0.0 for c in CodigoConflito
    }
    (final,) = [
        log
        for log in logs
        if log.get("no") == "validacao_dominio" and log["message"] == "domain validation finished"
    ]
    assert final["extra"]["codigos"] == ["nucleo_sem_lastro"]
    assert final["extra"]["elementos"] == ["nucleo.loja"]
    assert "citado sem código" not in simplejson.dumps(logs)


async def test_estado_do_grafo_mantem_so_elementos_e_motivo(
    ambiente: ConfirmacaoFalsa,
) -> None:
    payload = await _processar(ambiente, _regra(especificacoes=[_faixa_invertida()]))

    conflitos = (await ambiente.estado(payload)).values["conflitos"]

    assert conflitos == [
        {"elementos": ["elem.1"], "motivo": "limite inferior 50000 maior que o superior 40000"}
    ]


async def test_metrics_so_expoe_codigos_do_conjunto_fechado_apos_barrar_cada_verificacao(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient
) -> None:
    for _, regra in _ALCANCAVEIS:
        await _processar(ambiente, regra)

    texto = (await cliente.get("/metrics")).text

    codigos = {
        a.labels["codigo"]
        for familia in text_string_to_metric_families(texto)
        for a in familia.samples
        if a.name == METRICA
    }
    assert codigos == {c.value for c in CodigoConflito}


async def test_condicao_limiar_sem_escopo_falha_na_leitura_como_regra_fora_do_contrato() -> None:
    limiar = {
        "ref": "elem.1",
        "construto": "condicao_limiar",
        "metrica": "venda_total",
        "operador": ">=",
        "limiar": 50000,
    }
    linha = {
        "nucleo": {"loja": [], "marca": [], "cargo": [], "percentual": 0.025},
        "especificacoes": [limiar],
    }

    with pytest.raises(RegraInvalidaError):
        await buscar_regra(_sessionmaker(linha), uuid4(), uuid4())


async def test_reentrega_de_regra_barrada_nao_incrementa_o_contador_de_conflitos(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient
) -> None:
    payload = await _processar(ambiente, _regra(especificacoes=[_faixa_invertida()]))
    antes = _contagens((await cliente.get("/metrics")).text)

    await ambiente.consumer.receber(mensagem(payload))

    assert _contagens((await cliente.get("/metrics")).text) == antes


async def test_falha_ao_publicar_a_regra_barrada_nao_conta_os_conflitos(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient
) -> None:
    ambiente.producers.no_concluido.side_effect = RuntimeError("CONTEUDO_PRIVADO")
    regra = _regra({"percentual": Decimal("-0.01")}, [_faixa_invertida()])
    antes = (await cliente.get("/metrics")).text

    await _processar(ambiente, regra)

    depois = (await cliente.get("/metrics")).text
    falhas = {"job_name": "validate_domain"}
    assert (
        amostra(depois, "job_failures_total", falhas) - amostra(antes, "job_failures_total", falhas)
        == 1
    )
    assert _contagens(depois) == _contagens(antes)
