#!/usr/bin/env sh

set -eu

diretorio_do_script="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$diretorio_do_script"

poetry run ruff check app/ scripts/ tests/
poetry run ruff format --check app/ scripts/ tests/
poetry run mypy app/ scripts/ tests/scripts/ tests/contracts/
poetry run pytest -m "not docker"

if poetry run python - <<'PY'
import sys

import docker
from docker.errors import DockerException

from app.config import get_settings

cliente = None
try:
    cliente = docker.DockerClient(base_url=get_settings().DOCKER_HOST)
    cliente.ping()
except (DockerException, OSError):
    sys.exit(1)
finally:
    if cliente is not None:
        cliente.close()
PY
then
    echo "Docker daemon disponível: executando testes marcados com 'docker'."
    poetry run pytest -m docker
else
    echo "AVISO: testes marcados com 'docker' foram pulados porque o daemon Docker não está disponível."
fi
