from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.config import get_settings
from app.core.logger import get_logger, stop_logger
from app.core.metrics.prometheus import prometheus


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI) -> AsyncGenerator[None, None]:
    registrador = get_logger("app.main")
    registrador.info("aplicação codegen iniciada")
    try:
        yield
    finally:
        registrador.info("aplicação codegen encerrada")
        stop_logger()


def criar_aplicacao() -> FastAPI:
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

    @aplicacao.get("/health", include_in_schema=False)
    async def verificar_saude() -> dict[str, str]:
        return {"status": "UP"}

    @aplicacao.get("/metrics", include_in_schema=False)
    async def obter_metricas() -> Response:
        return Response(prometheus.get_all(), media_type=CONTENT_TYPE_LATEST)

    return aplicacao
