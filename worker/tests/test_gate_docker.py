"""Quando um teste de Docker pulado é falha (T-064).

Os testes marcados `docker` são os que provam o isolamento do sandbox. Se forem pulados
em silêncio na CI, o gate do componente fica verde sem que nenhuma restrição tenha sido
verificada; aqui está a decisão que impede isso, conferida fora do pytest que a aplica.
"""

import pytest

from tests.conftest import exige_docker


@pytest.mark.parametrize(
    ("ambiente", "esperado"),
    [
        ({}, False),
        ({"CI": "true"}, True),
        ({"CI": "false"}, False),
        ({"EXIGIR_DOCKER": "1"}, True),
        ({"EXIGIR_DOCKER": "0"}, False),
        ({"CI": "true", "EXIGIR_DOCKER": "0"}, True),
    ],
)
def test_quando_um_pulo_de_teste_docker_vira_falha(
    ambiente: dict[str, str], esperado: bool
) -> None:
    assert exige_docker(ambiente) is esperado


def test_o_desenvolvedor_sem_daemon_continua_podendo_pular() -> None:
    """A máquina de desenvolvimento não é o portão final; a CI é."""
    assert exige_docker({"ENVIRONMENT": "development"}) is False
