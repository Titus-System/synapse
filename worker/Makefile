install:
	poetry install

# Alternativa sem poetry (pip + venv):
#   python -m venv venv && source venv/bin/activate
#   make install-pip      (runtime)  |  make install-pip-dev (runtime + ferramentas)
install-pip:
	pip install -r requirements.txt

install-pip-dev:
	pip install -r requirements-dev.txt

# Regera os requirements*.txt a partir do poetry.lock (rode após alterar deps).
requirements:
	poetry export --only main --without-hashes --output requirements.txt
	poetry export --with dev --without-hashes --output requirements-dev.txt

run:
	poetry run uvicorn app.main:create_app --factory

dev:
	poetry run uvicorn app.main:create_app --factory --reload

lint:
	poetry run ruff check app/ scripts/ tests/
	poetry run bandit -r app/

format:
	poetry run ruff format app/ scripts/ tests/

typecheck:
	poetry run mypy app/ scripts/ tests/scripts/

test:
	poetry run pytest

pre-commit:
	poetry run ruff check --fix app/ scripts/ tests/
	poetry run ruff format app/ scripts/ tests/
	poetry run mypy app/ scripts/ tests/scripts/
	poetry run pytest
