import os
import socket
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "agents"
    SERVICE_DESCRIPTION: str = "Servidor rodando os agentes de IA"
    SERVICE_PUBLIC_URL: str = "http://localhost:8000"
    VERSION: str = "0.1.0"

    @property
    def project_identifier(self) -> str:
        return self.SERVICE_NAME.lower().replace(" ", "-")

    ENVIRONMENT: str = "development"

    # Observabilidade
    LOG_LEVEL: str = "INFO"

    @property
    def hostname(self) -> str:
        """Instância onde o processo roda — vai no campo "host" do log.

        Em k8s/Docker o runtime injeta HOSTNAME (nome do pod/container);
        fora deles cai no hostname da máquina.
        """
        return os.getenv("HOSTNAME") or socket.gethostname()

    # Postgres settings
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "agents_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    @property
    def postgres_db_test(self) -> str:
        return f"{self.POSTGRES_DB}_test"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def test_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.postgres_db_test}"
        )

    @property
    def database_server_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/postgres"
        )

    model_config = SettingsConfigDict(extra="allow", env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
