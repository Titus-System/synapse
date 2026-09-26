"""Verificação do acesso ao daemon do Docker."""

import asyncio

import docker
from docker.errors import DockerException

from app.config import get_settings
from app.core.logger import get_logger

logger = get_logger("app.sandbox.daemon")


class DaemonIndisponivelError(RuntimeError):
    """O daemon do Docker não respondeu."""


def _listar_containers() -> tuple[str, int]:
    settings = get_settings()

    # DockerClient já consulta a versão do servidor ao ser construído, então uma
    # falha de acesso ao socket aparece aqui e não só na primeira execução.
    cliente = docker.DockerClient(base_url=settings.DOCKER_HOST)
    try:
        versao = str(cliente.version()["Version"])
        return versao, len(cliente.containers.list())
    finally:
        cliente.close()


async def verificar_acesso() -> None:
    """Prova que o worker alcança o daemon, ou impede o processo de subir."""
    settings = get_settings()

    try:
        versao, containers = await asyncio.to_thread(_listar_containers)
    except (DockerException, OSError) as erro:
        mensagem = (
            f"sem acesso ao daemon do Docker em {settings.DOCKER_HOST}: o worker não tem "
            "como executar código gerado. Confirme que o socket está montado no container "
            "e que DOCKER_GID em deploy/.env é o GID do grupo docker do host "
            "(getent group docker | cut -d: -f3). Ver docs/instalacao.md."
        )
        logger.exception(mensagem)
        raise DaemonIndisponivelError(mensagem) from erro

    logger.info(
        "acesso ao daemon do Docker verificado",
        extra={
            "docker_host": settings.DOCKER_HOST,
            "docker_version": versao,
            "containers_em_execucao": containers,
        },
    )
