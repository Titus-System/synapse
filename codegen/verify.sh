#!/usr/bin/env sh

set -eu

diretorio_do_script="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$diretorio_do_script"

poetry run ruff check app tests
poetry run ruff format --check app tests
poetry run mypy app
poetry run pytest
