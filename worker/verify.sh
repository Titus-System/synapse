#!/usr/bin/env sh

set -eu

diretorio_do_script="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$diretorio_do_script"

poetry run ruff check app/ scripts/ tests/
poetry run ruff format --check app/ scripts/ tests/
poetry run mypy app/ scripts/ tests/scripts/ tests/contracts/
poetry run pytest -m "not docker and not postgres and not rabbitmq"

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
elif [ "${CI:-}" = "true" ] || [ "${EXIGIR_DOCKER:-}" = "1" ]; then
    # Os testes marcados 'docker' são os que provam o isolamento do sandbox (T-033,
    # T-064). Pulá-los aqui deixaria o gate de segurança verde sem ter verificado nada.
    echo "ERRO: o daemon Docker não está disponível e os testes de isolamento do sandbox não podem ser pulados em CI." >&2
    exit 1
else
    echo "AVISO: testes marcados com 'docker' foram pulados porque o daemon Docker não está disponível."
fi

# Os dois checks abaixo carregam .env.test (como tests/conftest.py) para checar o
# mesmo alvo que os testes marcados vão usar.
if poetry run python - <<'PY'
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env.test", override=True)

from app.config import get_settings  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


async def checar() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect():
            pass
    finally:
        await engine.dispose()


try:
    asyncio.run(checar())
except Exception:
    sys.exit(1)
PY
then
    echo "Postgres disponível: executando testes marcados com 'postgres'."
    poetry run pytest -m postgres
else
    echo "AVISO: testes marcados com 'postgres' foram pulados porque o Postgres não está acessível."
fi

if poetry run python - <<'PY'
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env.test", override=True)

from aio_pika import connect_robust  # noqa: E402

from app.config import get_settings  # noqa: E402


async def checar() -> None:
    conexao = await connect_robust(get_settings().rabbitmq_url, timeout=5)
    await conexao.close()


try:
    asyncio.run(checar())
except Exception:
    sys.exit(1)
PY
then
    echo "RabbitMQ disponível: executando testes marcados com 'rabbitmq'."
    poetry run pytest -m rabbitmq
else
    echo "AVISO: testes marcados com 'rabbitmq' foram pulados porque o RabbitMQ não está acessível."
fi
