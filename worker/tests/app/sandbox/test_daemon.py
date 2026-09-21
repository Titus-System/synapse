from typing import Any
from unittest.mock import MagicMock

import pytest
from docker.errors import DockerException

from app.sandbox import daemon
from app.sandbox.daemon import DaemonIndisponivelError, verificar_acesso


@pytest.fixture
def cliente_docker(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Substitui o daemon real, que o teste não possui."""
    cliente = MagicMock()
    cliente.version.return_value = {"Version": "28.0.1"}
    cliente.containers.list.return_value = [MagicMock(), MagicMock()]
    monkeypatch.setattr(daemon.docker, "DockerClient", MagicMock(return_value=cliente))
    return cliente


async def test_lista_containers_para_provar_o_acesso(cliente_docker: MagicMock) -> None:
    await verificar_acesso()

    cliente_docker.containers.list.assert_called_once()


async def test_fecha_o_cliente_mesmo_quando_a_listagem_falha(cliente_docker: MagicMock) -> None:
    cliente_docker.containers.list.side_effect = DockerException("boom")

    with pytest.raises(DaemonIndisponivelError):
        await verificar_acesso()

    cliente_docker.close.assert_called_once()


async def test_falha_de_acesso_interrompe_a_subida(monkeypatch: pytest.MonkeyPatch) -> None:
    def recusar(*_args: Any, **_kwargs: Any) -> None:
        raise DockerException("Error while fetching server API version: Permission denied")

    monkeypatch.setattr(daemon.docker, "DockerClient", recusar)

    with pytest.raises(DaemonIndisponivelError) as erro:
        await verificar_acesso()

    assert "DOCKER_GID" in str(erro.value)
    assert "docs/instalacao.md" in str(erro.value)


async def test_permissao_negada_no_socket_interrompe_a_subida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Um erro de socket chega como OSError, fora da hierarquia do docker-py."""

    def recusar(*_args: Any, **_kwargs: Any) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(daemon.docker, "DockerClient", recusar)

    with pytest.raises(DaemonIndisponivelError):
        await verificar_acesso()
