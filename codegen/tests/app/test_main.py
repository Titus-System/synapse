from fastapi import FastAPI
from httpx import AsyncClient


async def test_health_retorna_servico_disponivel(cliente: AsyncClient) -> None:
    resposta = await cliente.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "UP"}


async def test_metrics_expoe_formato_prometheus(cliente: AsyncClient) -> None:
    resposta = await cliente.get("/metrics")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/plain")
    assert "# HELP" in resposta.text


def test_expoe_apenas_rotas_operacionais(aplicacao: FastAPI) -> None:
    assert {rota.path for rota in aplicacao.routes} == {"/health", "/metrics"}
