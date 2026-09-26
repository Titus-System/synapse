from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.config import get_settings
from app.core.logger import get_logger, stop_logger
from app.core.metrics.prometheus import prometheus
from app.db import criar_engine, criar_sessionmaker
from app.graph.core.checkpointer import get_checkpointer
from app.mensageria.broker import conectar
from app.mensageria.roteamento import GraphRouter, RoteadorGrafo


@asynccontextmanager
async def ciclo_de_vida(aplicacao: FastAPI) -> AsyncGenerator[None, None]:
    registrador = get_logger("app.main")
    registrador.info("aplicação codegen iniciada")
    engine = criar_engine(get_settings())
    try:
        sessoes = criar_sessionmaker(engine)
        if isinstance(aplicacao.state.roteador, GraphRouter):
            aplicacao.state.roteador.sessoes = sessoes

        async with get_checkpointer() as checkpointer:
            await checkpointer.setup()

        broker = await conectar(get_settings())
        aplicacao.state.producers = broker.producers
        if isinstance(aplicacao.state.roteador, GraphRouter):
            aplicacao.state.roteador.producers = broker.producers
        try:
            if aplicacao.state.roteador is not None:
                await broker.iniciar_consumers(aplicacao.state.roteador)
            else:
                registrador.warning("consumo não iniciado: roteador de grafos não configurado")
            yield
        finally:
            await broker.fechar()
    finally:
        await engine.dispose()
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


def criar_aplicacao_padrao() -> FastAPI:
    """Production entrypoint (`uvicorn app.main:criar_aplicacao_padrao --factory`).

    Wires the real `GraphRouter` before the app is created; `sessoes`/`producers` are filled
    in by `ciclo_de_vida` once the resources they depend on are ready.
    """
    return criar_aplicacao(GraphRouter())
