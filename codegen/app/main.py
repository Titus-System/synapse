from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.config import get_settings
from app.core.logger import get_logger, stop_logger
from app.core.metrics.prometheus import prometheus
from app.mensageria.broker import conectar
from app.mensageria.roteamento import RoteadorGrafo


@asynccontextmanager
async def ciclo_de_vida(aplicacao: FastAPI) -> AsyncGenerator[None, None]:
    registrador = get_logger("app.main")
    registrador.info("aplicação codegen iniciada")
    try:
        broker = await conectar(get_settings())
        aplicacao.state.producers = broker.producers
        try:
            if aplicacao.state.roteador is not None:
                await broker.iniciar_consumers(aplicacao.state.roteador)
            else:
                registrador.warning("consumo não iniciado: roteador de grafos não configurado")
            yield
        finally:
            await broker.fechar()
    finally:
        registrador.info("aplicação codegen encerrada")
        stop_logger()


def criar_aplicacao(roteador: RoteadorGrafo | None = None) -> FastAPI:
    configuracoes = get_settings()
    aplicacao = FastAPI(
        title=configuracoes.SERVICE_NAME,
        description=configuracoes.SERVICE_DESCRIPTION,
        version=configuracoes.VERSION,
        lifespan=ciclo_de_vida,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    aplicacao.state.roteador = roteador

    @aplicacao.get("/health", include_in_schema=False)
    async def verificar_saude() -> dict[str, str]:
        return {"status": "UP"}

    @aplicacao.get("/metrics", include_in_schema=False)
    async def obter_metricas() -> Response:
        return Response(prometheus.get_all(), media_type=CONTENT_TYPE_LATEST)

    return aplicacao
