import os
import socket
from functools import lru_cache
from urllib.parse import quote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "synapse-codegen"
    SERVICE_DESCRIPTION: str = "Processo de geração assistida do Synapse"
    SERVICE_PUBLIC_URL: str = "http://localhost:8000"
    VERSION: str = "0.1.0"

    @property
    def project_identifier(self) -> str:
        return self.SERVICE_NAME.lower().replace(" ", "-")

    ENVIRONMENT: str = "development"

    # Observabilidade
    LOG_LEVEL: str = "INFO"

    RABBITMQ_HOST: str = "localhost"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = "guest"
    RABBITMQ_PASSWORD: str = "guest"
    RABBITMQ_VHOST: str = "/"
    RABBITMQ_PREFETCH: int = Field(default=1, ge=1)

    @property
    def rabbitmq_url(self) -> str:
        usuario = quote(self.RABBITMQ_USER, safe="")
        senha = quote(self.RABBITMQ_PASSWORD, safe="")
        vhost = quote(self.RABBITMQ_VHOST, safe="")
        return f"amqp://{usuario}:{senha}@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/{vhost}"

    @property
    def hostname(self) -> str:
        """Instância onde o processo roda — vai no campo "host.name" do log.

        Em k8s/Docker o runtime injeta HOSTNAME (nome do pod/container);
        fora deles cai no hostname da máquina.
        """
        return os.getenv("HOSTNAME") or socket.gethostname()

    # Configurações de Postgres
    SYNAPSE_CODEGEN_DB_USER: str = "synapse_codegen"
    SYNAPSE_CODEGEN_DB_PASSWORD: str = "synapse_codegen"
    POSTGRES_DB: str = "synapse_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    @property
    def postgres_db_test(self) -> str:
        return f"{self.POSTGRES_DB}_test"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.SYNAPSE_CODEGEN_DB_USER}:"
            f"{self.SYNAPSE_CODEGEN_DB_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def test_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.SYNAPSE_CODEGEN_DB_USER}:"
            f"{self.SYNAPSE_CODEGEN_DB_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.postgres_db_test}"
        )

    @property
    def database_server_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.SYNAPSE_CODEGEN_DB_USER}:"
            f"{self.SYNAPSE_CODEGEN_DB_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/postgres"
        )

    @property
    def checkpointer_database_url(self) -> str:
        """Same Postgres server as `database_url`, but for `AsyncPostgresSaver`.

        The LangGraph checkpointer uses `psycopg` (v3), not `asyncpg`.
        See `.agents/skills/graph/SKILL.md`.
        """
        return (
            f"postgresql://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Graph / LLM
    GOOGLE_API_KEY: str | None = None

    model_config = SettingsConfigDict(extra="allow", env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
