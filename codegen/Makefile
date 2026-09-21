install: contracts
	poetry install

.PHONY: contracts
contracts:
	poetry run python scripts/preparar_contratos.py

# Alternativa sem poetry (pip + venv):
#   python -m venv venv && source venv/bin/activate
#   make install-pip      (runtime)  |  make install-pip-dev (runtime + ferramentas)
install-pip:
	python scripts/preparar_contratos.py
	python -m pip install -r requirements.txt

install-pip-dev:
	python scripts/preparar_contratos.py
	python -m pip install -r requirements-dev.txt

# Regera os requirements*.txt a partir do poetry.lock (rode após alterar deps).
requirements:
	poetry export --only main --without-hashes --output requirements.txt
	poetry export --with dev --without-hashes --output requirements-dev.txt

run: contracts
	poetry run uvicorn app.main:criar_aplicacao --factory --log-config logging.json

dev: contracts
	poetry run uvicorn app.main:criar_aplicacao --factory --reload --log-config logging.json

lint:
	poetry run ruff check app/
	poetry run bandit -r app/

format:
	poetry run ruff format app/

typecheck:
	poetry run mypy app/


test: contracts
	poetry run pytest

test-cov:
	poetry run pytest --cov=app --cov-report=term-missing

graph:
	poetry run python -m app.graph.diagram

test-e2e:
	poetry run pytest tests/app/e2e/

test-rabbitmq: contracts
	RUN_RABBITMQ_INTEGRATION=1 poetry run pytest -p no:cacheprovider -m rabbitmq

seed:
	poetry run python app/seed/run_seed.py

migrate:
	poetry run alembic upgrade head

makemigration:
	poetry run alembic revision --autogenerate -m "$(m)"

pre-commit: contracts
	poetry run ruff check --fix app/
	poetry run ruff format app/
	poetry run mypy app/
	poetry run pytest
