"""Critério não reconhecido pela extração, pelos consumers, roteador, grafo e nós reais.

A cadeia é a do job que a simulação interrompia: a extração não reconhece um critério, a
validação da versão extraída pede a correção, a correção completa a regra e a versão corrigida
segue para a geração sem resíduo. Banco, modelos e produtores são os falsos dos ambientes de
extração, confirmação e reextração. `nucleo_sem_lastro` lê os rebaixamentos que a extração gravou
no banco falso; a consulta real é testada no Postgres
(`tests/app/repositorio/test_parametros_sem_lastro_postgres.py`).
"""

import logging
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import simplejson
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker

from app.core.logger import FormatadorJson, ManipuladorFilaContexto
from app.extracao.construtos.generico import DESCRICAO_SEM_LASTRO
from app.representacao_regra import RepresentacaoRegra
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.extracao_falsa import BancoExtracaoFalso
from tests.app.graph.test_extracao import AmbienteExtracao, amostra
from tests.app.graph.test_reextracao import AmbienteReextracao
from tests.app.test_mensageria import CONTRATOS, exemplo, oficial

TEXTO = "loja sessenta e oito marca preto para todos os cargos com 1% de comissão CRITERIO_PRIVADO"
# O modelo devolveu o código no lugar da citação, que não está no texto.
NUCLEO_SEM_A_LOJA = {
    "loja": [{"valor": "68", "trecho": "loja 68"}],
    "marca": [{"valor": "PRETO", "trecho": "marca preto"}],
    "cargo": {"valor": [], "trecho": "todos os cargos"},
    "percentual": {"valor": Decimal("0.01"), "trecho": "1%"},
}
NUCLEO_EXTRAIDO = {"marca": ["10"], "cargo": [], "percentual": Decimal("0.01")}
MOTIVO_DA_LOJA = (
    "escopo de loja citado sem código reconhecido; indique os destinatários ou declare todos"
)
MOTIVO_DO_ELEMENTO = "condição citada sem trecho reconhecido; descreva a condição novamente"
CONFLITOS = "validacao_conflitos_total"


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


def _nucleo_sem_lastro_do_banco(
    banco: BancoExtracaoFalso,
) -> Callable[[object, UUID, UUID], frozenset[str]]:
    def ler(_sessoes: object, job_id: UUID, _regra_id: UUID) -> frozenset[str]:
        return frozenset(
            str(rebaixamento["ref"]).removeprefix("nucleo.")
            for extracao in banco.tabela("extracoes_regras")
            if extracao["job_id"] == job_id
            for rebaixamento in simplejson.loads(extracao["rebaixamentos"])
            if str(rebaixamento["ref"]).startswith("nucleo.")
        )

    return ler


async def _extrair(
    ambiente: AmbienteExtracao, texto: str = TEXTO
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = ambiente.entrada(origem="voz")
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = texto
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    return payload, extracao


async def _validar_versao_extraida(
    ambiente: AmbienteExtracao, payload: dict[str, Any], extracao: dict[str, Any]
) -> dict[str, Any]:
    """Abre o ciclo da versão nascida da extração, como a api faz depois de `regra-extraida`."""
    ambiente.buscar_regra.return_value = RepresentacaoRegra.model_validate(
        simplejson.loads(extracao["representacao"], use_decimal=True)
    )
    ambiente.nucleo_sem_lastro.side_effect = _nucleo_sem_lastro_do_banco(ambiente.banco)
    versao = exemplo("regra-submetida-parametros") | {
        "job_id": payload["job_id"],
        "submissao_id": payload["submissao_id"],
        "regra_id": str(uuid4()),
    }
    recebida = mensagem(versao)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    return versao


async def _validar_versao_corrigida(
    monkeypatch: pytest.MonkeyPatch, job_id: str, representacao: dict[str, Any]
) -> tuple[ConfirmacaoFalsa, dict[str, Any]]:
    ambiente = ConfirmacaoFalsa(monkeypatch)
    ambiente.buscar_regra.return_value = RepresentacaoRegra.model_validate(representacao)
    payload = exemplo("parametros-confirmados") | {
        "job_id": job_id,
        "regra_id": str(uuid4()),
        "meta_venda": Decimal("12000000"),
    }

    await ambiente.consumer.receber(mensagem(payload))

    return ambiente, payload


def _pausa(versao: dict[str, Any], referencia: str, motivo: str) -> tuple[str, dict[str, Any]]:
    return (
        "etapa-alterada",
        {
            "job_id": versao["job_id"],
            "etapa": "confirmacao",
            "status": "aguardando_correcao",
            "regra_id": versao["regra_id"],
            "conflitos": [{"elementos": [referencia], "motivo": motivo}],
        },
    )


async def test_extracao_registra_a_loja_nao_reconhecida_sem_criar_elemento(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": NUCLEO_SEM_A_LOJA, "elementos": [], "parametros": {}}]
    )
    antes = (await cliente.get("/metrics")).text

    payload, extracao = await _extrair(ambiente)

    assert simplejson.loads(extracao["representacao"], use_decimal=True) == {
        "nucleo": NUCLEO_EXTRAIDO,
        "especificacoes": [],
    }
    assert simplejson.loads(extracao["rebaixamentos"]) == [
        {"ref": "nucleo.loja", "motivo": "valor_sem_lastro"}
    ]
    depois = (await cliente.get("/metrics")).text
    for nome, rotulos, delta in (
        ("codegen_extracao_rebaixamentos_total", {"motivo": "valor_sem_lastro"}, 1),
        ("codegen_extracao_elementos_total", {"construto": "generico"}, 0),
    ):
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == delta
    do_no = [log for log in logs if log.get("no") == "extracao_parametros"]
    assert [log["message"] for log in do_no] == ["extraction started", "extraction finished"]
    assert do_no[-1]["extra"]["rebaixamentos_por_motivo"] == {"valor_sem_lastro": 1}
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    for log in logs:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(log)
        assert log["job_id"] == payload["job_id"]
    for privado in ("sessenta", "CRITERIO_PRIVADO"):
        assert privado not in simplejson.dumps(logs)


async def test_versao_extraida_pausa_pedindo_a_loja_sem_chegar_a_geracao(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": NUCLEO_SEM_A_LOJA, "elementos": [], "parametros": {}}]
    )
    payload, extracao = await _extrair(ambiente)
    antes = (await cliente.get("/metrics")).text

    versao = await _validar_versao_extraida(ambiente, payload, extracao)

    assert ambiente.publicacoes[-1] == _pausa(versao, "nucleo.loja", MOTIVO_DA_LOJA)
    assert "executar-codigo" not in [nome for nome, _ in ambiente.publicacoes]
    assert ambiente.modelo.seen_messages == []
    depois = (await cliente.get("/metrics")).text
    for codigo, delta in (("nucleo_sem_lastro", 1), ("escopo_ausente", 0)):
        rotulos = {"codigo": codigo}
        assert amostra(depois, CONFLITOS, rotulos) - amostra(antes, CONFLITOS, rotulos) == delta
    [final] = [log for log in logs if log["message"] == "domain validation finished"]
    assert final["extra"]["codigos"] == ["nucleo_sem_lastro"]
    assert MOTIVO_DA_LOJA not in simplejson.dumps(logs)


async def test_correcao_da_loja_completa_a_regra_sem_residuo_e_a_versao_segue_para_a_geracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trecho = "loja 68"
    saida = {
        "operacoes": [
            {
                "tipo": "definir_nucleo",
                "trecho": trecho,
                "campo": "loja",
                "valor": [{"valor": "68", "trecho": trecho}],
            }
        ]
    }
    correcao = AmbienteReextracao(monkeypatch, [saida])
    correcao.regra.return_value = RepresentacaoRegra.model_validate(
        {"nucleo": NUCLEO_EXTRAIDO, "especificacoes": []}
    )
    correcao.nucleo_sem_lastro.return_value = frozenset({"loja"})
    payload = correcao.entrada("É a loja 68. CORRECAO_PRIVADA")

    await correcao.consumer.receber(mensagem(payload))

    [[enviada]] = correcao.modelo_reextracao.seen_messages
    conflitos = simplejson.loads(str(enviada.content))["dados_do_sistema"]["conflitos"]
    assert [c for c in conflitos if c["elementos"] == ["nucleo.loja"]] == [
        {"elementos": ["nucleo.loja"], "motivo": MOTIVO_DA_LOJA}
    ]
    [proposta] = correcao.publicadas("correcao-proposta")
    oficial("correcao-proposta").validate(proposta)
    assert proposta["representacao"] == {
        "nucleo": {**NUCLEO_EXTRAIDO, "loja": ["68"]},
        "especificacoes": [],
    }

    validacao, versao = await _validar_versao_corrigida(
        monkeypatch, payload["job_id"], proposta["representacao"]
    )

    assert (await validacao.estado(versao)).values["regra_liberada"] is True
    assert "executar-codigo" in [nome for nome, _ in validacao.publicacoes]


async def test_elemento_sem_trecho_pausa_e_a_substituicao_libera_a_versao_corrigida(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient
) -> None:
    texto = "loja 68 para todas as marcas e todos os cargos com 1% de comissão"
    nucleo = {
        "loja": [{"valor": "68", "trecho": "loja 68"}],
        "marca": {"valor": [], "trecho": "todas as marcas"},
        "cargo": {"valor": [], "trecho": "todos os cargos"},
        "percentual": {"valor": Decimal("0.01"), "trecho": "1%"},
    }
    bonus = "bônus de R$ 350 para vendedores"
    elemento = {"construto_pretendido": "generico", "descricao": bonus, "trecho": bonus}
    extracao_ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": nucleo, "elementos": [elemento], "parametros": {}}]
    )
    payload, extracao = await _extrair(extracao_ambiente, texto)
    representacao = simplejson.loads(extracao["representacao"], use_decimal=True)
    assert representacao["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": DESCRICAO_SEM_LASTRO}
    ]
    antes = (await cliente.get("/metrics")).text

    versao = await _validar_versao_extraida(extracao_ambiente, payload, extracao)

    assert extracao_ambiente.publicacoes[-1] == _pausa(versao, "elem.1", MOTIVO_DO_ELEMENTO)
    depois = (await cliente.get("/metrics")).text
    rotulos = {"codigo": "elemento_sem_lastro"}
    assert amostra(depois, CONFLITOS, rotulos) - amostra(antes, CONFLITOS, rotulos) == 1

    saida = {
        "operacoes": [
            {"tipo": "substituir_elemento", "ref": "elem.1", "trecho": bonus, "elemento": elemento}
        ]
    }
    correcao = AmbienteReextracao(monkeypatch, [saida])
    correcao.regra.return_value = RepresentacaoRegra.model_validate(representacao)
    correcao_payload = correcao.entrada(f"O que eu disse foi {bonus}.") | {
        "job_id": payload["job_id"]
    }

    await correcao.consumer.receber(mensagem(correcao_payload))

    [proposta] = correcao.publicadas("correcao-proposta")
    assert proposta["representacao"]["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": bonus}
    ]
    validacao, versao_corrigida = await _validar_versao_corrigida(
        monkeypatch, payload["job_id"], proposta["representacao"]
    )
    assert (await validacao.estado(versao_corrigida)).values["regra_liberada"] is True
