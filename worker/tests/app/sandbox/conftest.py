"""Fixture compartilhada pelos testes que precisam da imagem do sandbox construída."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ_MONOREPO = Path(__file__).resolve().parents[4]
DOCKERFILE = "worker/sandbox/Dockerfile"
TAG_PADRAO = "synapse-sandbox:test"


@pytest.fixture(scope="session")
def imagem() -> str:
    """Constrói a imagem uma vez por sessão, ou reusa a de ``SANDBOX_IMAGE_TESTE``."""
    if not shutil.which("docker"):
        pytest.skip("docker não está no PATH")
    pronta = os.environ.get("SANDBOX_IMAGE_TESTE")
    if pronta:
        return pronta
    build = subprocess.run(
        ["docker", "build", "-f", DOCKERFILE, "-t", TAG_PADRAO, "."],
        cwd=RAIZ_MONOREPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    # Falha, não skip: um Dockerfile que não constrói é defeito nosso, e ignorar os testes
    # deixaria o gate verde sem testar a imagem. Só a ausência do CLI é fato do ambiente.
    if build.returncode != 0:
        pytest.fail(f"a imagem do sandbox não constrói:\n{build.stderr[-2000:]}", pytrace=False)
    return TAG_PADRAO
