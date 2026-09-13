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
	poetry run uvicorn app.main:criar_aplicacao --factory --log-config logging.json

dev:
	poetry run uvicorn app.main:criar_aplicacao --factory --reload --log-config logging.json

lint:
	poetry run ruff check app/
	poetry run bandit -r app/

format:
	poetry run ruff format app/

typecheck:
	poetry run mypy app/


test:
	poetry run pytest

test-e2e:
	poetry run pytest tests/app/e2e/

seed:
	poetry run python app/seed/run_seed.py

migrate:
	poetry run alembic upgrade head

makemigration:
	poetry run alembic revision --autogenerate -m "$(m)"

pre-commit:
	poetry run ruff check --fix app/
	poetry run ruff format app/
	poetry run mypy app/
	poetry run pytest
