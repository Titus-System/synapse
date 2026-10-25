"""Parâmetros da simulação na validação de domínio (T-280), pelo consumer, roteador e grafo reais.

Banco, modelo e produtores são os falsos de `ConfirmacaoFalsa`. A consulta dos parâmetros sem
lastro é trocada por um falso aqui; a real, com o filtro pela origem da versão, é testada no
Postgres (`tests/app/repositorio/test_parametros_sem_lastro_postgres.py`).
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.contratos.mensagens import RegraSubmetida
from app.mensageria.consumers import Consumer
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.graph.test_extracao import amostra
from tests.app.test_mensageria import exemplo


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> ConfirmacaoFalsa:
    return ConfirmacaoFalsa(monkeypatch)


def _pausa(payload: dict[str, Any], referencia: str, motivo: str) -> tuple[str, dict[str, Any]]:
    return (
        "etapa-alterada",
        {
            "job_id": payload["job_id"],
            "etapa": "confirmacao",
            "status": "aguardando_correcao",
            "regra_id": payload["regra_id"],
            "conflitos": [{"elementos": [referencia], "motivo": motivo}],
        },
    )


@pytest.mark.parametrize(
    ("alteracao", "referencia", "motivo", "codigo"),
    [
        (
            {"orcamento": Decimal("-1")},
            "parametros.orcamento",
            "orçamento negativo",
            "orcamento_negativo",
        ),
        (
            {"meta_venda": Decimal("0")},
            "parametros.meta_venda",
            "meta de venda zero ou negativa",
            "meta_venda_nao_positiva",
        ),
        (
            {"competencias": ["2025-11", "2026-01"]},
            "parametros.competencias",
            "competência sem dados publicados",
            "competencia_nao_publicada",
        ),
    ],
    ids=["orcamento_negativo", "meta_zero", "competencia_fora_das_publicadas"],
)
async def test_parametro_invalido_barra_a_regra_e_pausa_sem_chegar_a_geracao(
    ambiente: ConfirmacaoFalsa,
    cliente: AsyncClient,
    alteracao: dict[str, Any],
    referencia: str,
    motivo: str,
    codigo: str,
) -> None:
    payload = (exemplo("parametros-confirmados") | {"meta_venda": Decimal("12000000")}) | alteracao
    recebida = mensagem(payload)
    antes = (await cliente.get("/metrics")).text

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert ambiente.publicacoes[-1] == _pausa(payload, referencia, motivo)
    assert ambiente.modelo.seen_messages == []
    assert "executar-codigo" not in [nome for nome, _ in ambiente.publicacoes]
    assert (await ambiente.estado(payload)).next == ()
    depois = (await cliente.get("/metrics")).text
    rotulos = {"codigo": codigo}
    assert (
        amostra(depois, "validacao_conflitos_total", rotulos)
        - amostra(antes, "validacao_conflitos_total", rotulos)
        == 1
    )
    barrada = {"resultado": "barrada"}
    nome = "codegen_validacao_dominio_resultados_total"
    assert amostra(depois, nome, barrada) - amostra(antes, nome, barrada) == 1


async def test_orcamento_negativo_da_regra_submetida_chega_a_validacao_e_pausa(
    ambiente: ConfirmacaoFalsa,
) -> None:
    """É por `regra-submetida` que a versão nascida da extração abre o ciclo (T-278)."""
    payload = exemplo("regra-submetida-parametros") | {"orcamento": Decimal("-1")}
    recebida = mensagem(payload)

    await Consumer(RegraSubmetida, "regra-submetida", ambiente.roteador).receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert ambiente.publicacoes[-1] == _pausa(payload, "parametros.orcamento", "orçamento negativo")
    assert ambiente.modelo.seen_messages == []


async def test_parametro_sem_lastro_barra_a_versao_extraida_na_referencia_do_parametro(
    ambiente: ConfirmacaoFalsa, cliente: AsyncClient
) -> None:
    ambiente.sem_lastro.return_value = frozenset({"orcamento"})
    payload = exemplo("parametros-confirmados") | {"meta_venda": Decimal("12000000")}
    antes = (await cliente.get("/metrics")).text

    await ambiente.consumer.receber(mensagem(payload))

    ambiente.sem_lastro.assert_awaited_once_with(
        ambiente.banco, UUID(payload["job_id"]), UUID(payload["regra_id"])
    )
    assert ambiente.publicacoes[-1] == _pausa(
        payload, "parametros.orcamento", "orçamento citado sem valor reconhecido"
    )
    assert ambiente.modelo.seen_messages == []
    depois = (await cliente.get("/metrics")).text
    rotulos = {"codigo": "parametro_sem_lastro"}
    assert (
        amostra(depois, "validacao_conflitos_total", rotulos)
        - amostra(antes, "validacao_conflitos_total", rotulos)
        == 1
    )


async def test_job_sem_orcamento_e_sem_meta_pausa_antes_da_geracao(
    ambiente: ConfirmacaoFalsa,
) -> None:
    payload = exemplo("parametros-confirmados") | {"meta_venda": Decimal("12000000")}
    for campo in ("orcamento", "meta_venda"):
        payload.pop(campo, None)
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [pausa] = [p for _, p in ambiente.publicacoes if p.get("status") == "aguardando_correcao"]
    assert {ref for conflito in pausa["conflitos"] for ref in conflito["elementos"]} == {
        "parametros.orcamento",
        "parametros.meta_venda",
    }
    assert ambiente.modelo.seen_messages == []
    assert "executar-codigo" not in [nome for nome, _ in ambiente.publicacoes]


async def test_loja_fora_do_catalogo_pede_correcao_e_nao_amplia_simulacao_para_todas(
    ambiente: ConfirmacaoFalsa,
) -> None:
    from tests.app.extracao.test_motor import extrair, modelo_falso

    texto = "Pague 3% na loja 9999, para todas as marcas e todos os cargos."
    extraida = await extrair(
        modelo_falso(
            {
                "nucleo": {
                    "percentual": {"valor": Decimal("0.03"), "trecho": "3%"},
                    "loja": [{"valor": "9999", "trecho": "loja 9999"}],
                    "marca": {"valor": [], "trecho": "todas as marcas"},
                    "cargo": {"valor": [], "trecho": "todos os cargos"},
                },
                "elementos": [],
                "parametros": {},
            }
        ),
        texto,
    )
    ambiente.buscar_regra.return_value = extraida.representacao
    # O que `nucleo_sem_lastro` leria de `extracoes_regras.rebaixamentos` para essa versão.
    ambiente.nucleo_sem_lastro.return_value = frozenset(
        r.ref.removeprefix("nucleo.") for r in extraida.rebaixamentos if r.ref.startswith("nucleo.")
    )
    payload = exemplo("parametros-confirmados") | {"meta_venda": Decimal("12000000")}

    await ambiente.consumer.receber(mensagem(payload))

    representacao = extraida.representacao.para_contrato()
    assert "loja" not in representacao["nucleo"]
    assert representacao["especificacoes"] == []
    assert ambiente.publicacoes[-1] == _pausa(
        payload,
        "nucleo.loja",
        "escopo de loja citado sem código reconhecido; indique os destinatários ou declare todos",
    )
    assert ambiente.modelo.seen_messages == []
    assert "executar-codigo" not in [nome for nome, _ in ambiente.publicacoes]
