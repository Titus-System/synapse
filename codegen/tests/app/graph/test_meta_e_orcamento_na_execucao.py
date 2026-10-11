"""A meta de venda e o orçamento do job, do evento que abre o ciclo ao comando do worker (T-272).

Consumer, roteador, entrypoint e nós são os reais; só as fronteiras externas são falsas, e
cada publicação é conferida contra o schema oficial (`ConfirmacaoFalsa`).
"""

import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import simplejson
from jsonschema import Draft202012Validator, FormatChecker

from app.contratos.mensagens import ParametrosConfirmados, RegraSubmetida, SimulacaoConcluida
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
async def test_ciclo_aberto_sem_meta_publica_o_comando_sem_o_campo(
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
    comando = _comando(ambiente)
    assert "meta_venda" not in comando
    assert comando["proposito"] == "simulacao"


@pytest.mark.parametrize(("modelo", "fila", "nome"), EVENTOS_DE_ENTRADA)
async def test_ciclo_sem_orcamento_simula_e_termina_sem_sugestao_e_sem_erro(
    ambiente: ConfirmacaoFalsa,
    monkeypatch: pytest.MonkeyPatch,
    modelo: type[ParametrosConfirmados | RegraSubmetida],
    fila: str,
    nome: str,
) -> None:
    payload = exemplo(nome)
    del payload["orcamento"]
    del payload["meta_venda"]
    recebida = mensagem(payload)

    await Consumer(modelo, fila, ambiente.roteador).receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert "orcamento" not in _comando(ambiente)
    assert (await ambiente.estado(payload)).next == ("await_execution",)

    monkeypatch.setattr(
        "app.mensageria.roteamento.buscar_regra_do_resultado",
        AsyncMock(return_value=UUID(payload["regra_id"])),
    )
    resultado = exemplo("simulacao-concluida-sem-orcamento") | {"job_id": payload["job_id"]}
    assert "veredito" not in resultado
    recebido = mensagem(resultado)

    await Consumer(SimulacaoConcluida, "simulacao-concluida", ambiente.roteador).receber(recebido)

    recebido.ack.assert_awaited_once_with()
    recebido.reject.assert_not_awaited()
    recebido.nack.assert_not_awaited()
    estado = await ambiente.estado(payload)
    assert estado.next == ()
    assert estado.values["encaminhamento"] == "fim"
    assert "sugestao-adaptacao-proposta" not in [n for n, _ in ambiente.publicacoes]
    etapas = [p for n, p in ambiente.publicacoes if n == "etapa-alterada"]
    assert [etapa for etapa in etapas if etapa["status"] == "erro"] == []
    [decisao] = [p for n, p in ambiente.publicacoes if n == "no-concluido" and p["no"] == "decisao"]
    assert decisao["conclusao"]["encaminhamento"] == "fim"


@pytest.mark.parametrize("meta", [Decimal("0"), Decimal("-1")])
async def test_meta_sem_vendas_a_escalar_termina_o_job_em_erro_sem_voltar_a_fila(
    ambiente: ConfirmacaoFalsa, meta: Decimal
) -> None:
    """A entrada aceita a meta como foi dita, para a validação de domínio apontá-la (T-280). Se
    ainda assim ela chega ao despacho, o job termina em erro: voltar à fila repetiria a mesma
    falha a cada reentrega."""
    payload = exemplo("parametros-confirmados-meta-venda") | {"meta_venda": meta}
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    recebida.nack.assert_not_awaited()
    recebida.ack.assert_not_awaited()
    assert "executar-codigo" not in [n for n, _ in ambiente.publicacoes]
    assert ambiente.publicacoes[-1] == (
        "etapa-alterada",
        {"job_id": payload["job_id"], "etapa": "delegacao_worker", "status": "erro"},
    )
