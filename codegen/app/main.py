from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.logger import get_logger, stop_logger
from app.core.metrics.prometheus import prometheus

settings = get_settings()

health_router = APIRouter()


@health_router.get("/health", tags=["Health Check"])
async def check_health() -> JSONResponse:
    return JSONResponse(content="ok", status_code=status.HTTP_200_OK)


@health_router.get("/ready", tags=["Health Check"])
async def check_ready() -> JSONResponse:
    return JSONResponse({})


metrics_router = APIRouter(include_in_schema=False)


@metrics_router.get("/metrics", tags=["Metrics"])
async def get_metrics(request: Request) -> Response:
    return Response(prometheus.get_all(), media_type="text/plain; version=0.0.4")


@metrics_router.get("/metrics/{prefix}", tags=["Metrics"])
async def filter_metrics(request: Request, prefix: str) -> Response:
    return Response(prometheus.get_all_by_prefix(prefix), media_type="text/plain; version=0.0.4")


def initiate_routers(app: FastAPI) -> None:
    app.include_router(metrics_router)
    app.include_router(health_router)

    @app.get("/", tags=["Health Check"])
    async def read_root() -> JSONResponse:
        """root endpoint to verify the API's heakth status."""

        data = {"name": app.title, "status": "ok", "environment": settings.ENVIRONMENT}

        return JSONResponse(
            content=data,
            status_code=status.HTTP_200_OK,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger = get_logger("app.main")
    settings = get_settings()
    logger.info(f"Starting Application {settings.SERVICE_NAME}...")

    try:
        yield
    finally:
        logger.info("Shutting down application...")
        stop_logger()


async def validation_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    errors: Sequence[Any] = exc.errors() if isinstance(exc, RequestValidationError) else []
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": jsonable_encoder(errors)},
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.SERVICE_NAME,
        description=settings.SERVICE_DESCRIPTION,
        version=settings.VERSION,
        lifespan=lifespan,
    )
    initiate_routers(app)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    return app
