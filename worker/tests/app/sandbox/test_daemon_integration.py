import pytest

from app.sandbox.daemon import verificar_acesso


@pytest.mark.docker
async def test_worker_acessa_daemon_docker_real() -> None:
    await verificar_acesso()
