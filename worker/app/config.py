import os
import socket
from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "synapse-worker"
    SERVICE_DESCRIPTION: str = "Executor isolado do código gerado para simulação de regras"
    SERVICE_PUBLIC_URL: str = "http://localhost:8000"
    VERSION: str = "0.1.0"

    @property
    def project_identifier(self) -> str:
        return self.SERVICE_NAME.lower().replace(" ", "-")

    ENVIRONMENT: str = "development"

    # Observabilidade
    LOG_LEVEL: str = "INFO"

    # No container o stdout é o transporte de log, então o padrão é a linha que o
    # coletor entende; "text" existe para o terminal do desenvolvedor.
    LOG_FORMAT: Literal["json", "text"] = "json"

    @property
    def hostname(self) -> str:
        """Instância onde o processo roda — vai no campo "host" do log.

        Em k8s/Docker o runtime injeta HOSTNAME (nome do pod/container);
        fora deles cai no hostname da máquina.
        """
        return os.getenv("HOSTNAME") or socket.gethostname()

    # Postgres settings
    SYNAPSE_WORKER_DB_USER: str = "synapse_worker"
    SYNAPSE_WORKER_DB_PASSWORD: str = "synapse_worker"
    POSTGRES_DB: str = "synapse_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    @property
    def postgres_db_test(self) -> str:
        return f"{self.POSTGRES_DB}_test"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.SYNAPSE_WORKER_DB_USER}:"
            f"{self.SYNAPSE_WORKER_DB_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def test_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.SYNAPSE_WORKER_DB_USER}:"
            f"{self.SYNAPSE_WORKER_DB_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.postgres_db_test}"
        )

    @property
    def database_server_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.SYNAPSE_WORKER_DB_USER}:"
            f"{self.SYNAPSE_WORKER_DB_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/postgres"
        )

    # RabbitMQ
    RABBITMQ_HOST: str = "localhost"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = "guest"
    RABBITMQ_PASSWORD: str = "guest"
    RABBITMQ_VHOST: str = "/"

    # Nome do comando no catálogo de mensagens;
    # o codegen publica com este mesmo nome
    RABBITMQ_FILA_EXECUCAO: str = "executar-codigo"

    # Uma execução por vez: o sandbox é pesado e roda uma instância só.
    RABBITMQ_PREFETCH: int = 1

    @property
    def rabbitmq_url(self) -> str:
        usuario = quote(self.RABBITMQ_USER, safe="")
        senha = quote(self.RABBITMQ_PASSWORD, safe="")
        vhost = quote(self.RABBITMQ_VHOST, safe="")
        return f"amqp://{usuario}:{senha}@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/{vhost}"

    # Docker
    DOCKER_HOST: str = "unix:///var/run/docker.sock"

    model_config = SettingsConfigDict(extra="allow", env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
