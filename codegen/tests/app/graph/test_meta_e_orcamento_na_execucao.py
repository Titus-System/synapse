"""A meta de venda e o orçamento do job, do evento que abre o ciclo ao comando do worker (T-272).

Consumer, roteador, entrypoint e nós são os reais; só as fronteiras externas são falsas, e
cada publicação é conferida contra o schema oficial (`ConfirmacaoFalsa`).
"""

import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
import simplejson
from jsonschema import Draft202012Validator, FormatChecker

from app.contratos.mensagens import ParametrosConfirmados, RegraSubmetida
from app.core.logger import FormatadorJson, ManipuladorFilaContexto
from app.mensageria.consumers import Consumer
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.test_mensageria import CONTRATOS, exemplo

META = Decimal("9000000.123456789012345")

# O ciclo da versão abre pelos dois eventos: `parametros-confirmados` e `regra-submetida`, que é
# também por onde a api reabre o ciclo da regra alternativa com os parâmetros do job.
EVENTOS_DE_ENTRADA = [
    (ParametrosConfirmados, "parametros-confirmados", "parametros-confirmados-meta-venda"),
    (RegraSubmetida, "regra-submetida", "regra-submetida-parametros"),
]


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> ConfirmacaoFalsa:
    return ConfirmacaoFalsa(monkeypatch)


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


def _comando(ambiente: ConfirmacaoFalsa) -> dict[str, Any]:
    [comando] = [payload for nome, payload in ambiente.publicacoes if nome == "executar-codigo"]
    return comando


@pytest.mark.parametrize(("modelo", "fila", "nome"), EVENTOS_DE_ENTRADA)
async def test_ciclo_aberto_com_meta_publica_o_comando_com_a_mesma_meta(
    ambiente: ConfirmacaoFalsa,
    logs: list[dict[str, Any]],
    modelo: type[ParametrosConfirmados | RegraSubmetida],
    fila: str,
    nome: str,
) -> None:
    payload = exemplo(nome) | {"meta_venda": META}
    recebida = mensagem(payload)

    await Consumer(modelo, fila, ambiente.roteador).receber(recebida)

    recebida.ack.assert_awaited_once_with()
    comando = _comando(ambiente)
    assert comando["meta_venda"] == META
    assert comando["orcamento"] == payload["orcamento"]
    assert comando["competencias"] == payload["competencias"]
    assert comando["proposito"] == "simulacao"
    assert (await ambiente.estado(payload)).values["meta_venda"] == str(META)
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    for log in logs:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(log)
        assert log["job_id"] == payload["job_id"]
    assert str(META) not in simplejson.dumps(logs)
    assert "9000000.12" not in simplejson.dumps(logs)


@pytest.mark.parametrize(("modelo", "fila", "nome"), EVENTOS_DE_ENTRADA)
async def test_ciclo_aberto_sem_meta_pausa_para_correcao(
    ambiente: ConfirmacaoFalsa,
    modelo: type[ParametrosConfirmados | RegraSubmetida],
    fila: str,
    nome: str,
) -> None:
    payload = exemplo(nome)
    del payload["meta_venda"]
    recebida = mensagem(payload)

    await Consumer(modelo, fila, ambiente.roteador).receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert ambiente.modelo.seen_messages == []
    assert "executar-codigo" not in [nome for nome, _ in ambiente.publicacoes]
    assert ambiente.publicacoes[-1][1]["conflitos"] == [
        {"elementos": ["parametros.meta_venda"], "motivo": "meta de vendas não informada"}
    ]


@pytest.mark.parametrize(("modelo", "fila", "nome"), EVENTOS_DE_ENTRADA)
async def test_ciclo_sem_orcamento_pausa_sem_gerar_sugestao(
    ambiente: ConfirmacaoFalsa,
    modelo: type[ParametrosConfirmados | RegraSubmetida],
    fila: str,
    nome: str,
) -> None:
    payload = exemplo(nome)
    del payload["orcamento"]
    recebida = mensagem(payload)
    await Consumer(modelo, fila, ambiente.roteador).receber(recebida)
    recebida.ack.assert_awaited_once_with()
    assert ambiente.modelo.seen_messages == []
    assert "executar-codigo" not in [nome for nome, _ in ambiente.publicacoes]
    assert "sugestao-adaptacao-proposta" not in [nome for nome, _ in ambiente.publicacoes]
    assert ambiente.publicacoes[-1][1]["conflitos"] == [
        {"elementos": ["parametros.orcamento"], "motivo": "orçamento não informado"}
    ]


@pytest.mark.parametrize("meta", [Decimal("0"), Decimal("-1")])
async def test_meta_sem_vendas_a_escalar_pausa_para_correcao_sem_chegar_a_geracao(
    ambiente: ConfirmacaoFalsa, meta: Decimal
) -> None:
    """A entrada aceita a meta como foi dita, e a validação de domínio a aponta (T-280). A guarda
    do despacho, que encerra o job em erro, tem o próprio teste em `test_artifact_nodes.py`."""
    payload = exemplo("parametros-confirmados-meta-venda") | {"meta_venda": meta}
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    recebida.reject.assert_not_awaited()
    recebida.nack.assert_not_awaited()
    assert ambiente.modelo.seen_messages == []
    assert "executar-codigo" not in [n for n, _ in ambiente.publicacoes]
    assert all(p.get("status") != "erro" for _, p in ambiente.publicacoes)
    assert ambiente.publicacoes[-1] == (
        "etapa-alterada",
        {
            "job_id": payload["job_id"],
            "etapa": "confirmacao",
            "status": "aguardando_correcao",
            "regra_id": payload["regra_id"],
            "conflitos": [
                {
                    "elementos": ["parametros.meta_venda"],
                    "motivo": "meta de venda zero ou negativa",
                }
            ],
        },
    )
