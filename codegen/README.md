# agents

FastAPI service that runs the AI agents. It is one component of a distributed system — a Spring Boot API, this server, and an execution worker — communicating asynchronously over RabbitMQ, with telemetry landing in Grafana (Loki, Prometheus, Tempo) through a Grafana Alloy collector.

## Stack

| | |
| --- | --- |
| Runtime | Python 3.12 |
| Web | FastAPI, Uvicorn |
| Settings | Pydantic Settings, read from `.env` |
| Database | PostgreSQL via SQLAlchemy 2 (async, asyncpg) and Alembic |
| Telemetry | Structured JSON logging, `prometheus-client`, OpenTelemetry SDK |
| Packaging | Poetry, with `requirements*.txt` exported for pip |
| Quality | Ruff, mypy (strict), Bandit, pytest |
| Container | Docker multi-stage build, Compose with Grafana Alloy |

The database and OpenTelemetry packages are installed and configured, but no models, migrations or spans exist yet: the service starts and serves without a database, and traces are not emitted until instrumentation is wired.

## Requirements

Python 3.12 and [Poetry](https://python-poetry.org/). Docker and Compose only if you want to run the container and the collector.

## Running locally

```bash
cp .env.example .env
make install
make dev
```

The service listens on http://localhost:8000, with interactive docs at http://localhost:8000/docs.

`make dev` runs Uvicorn with `--reload`; `make run` is the same without it. Neither needs Postgres or the Grafana stack to be reachable.

If you would rather not use Poetry, `make install-pip` installs the runtime dependencies into an active virtualenv from `requirements.txt`, and `make install-pip-dev` adds the tooling. Both files are generated from `poetry.lock` by `make requirements`, so change dependencies through Poetry and re-export.

## Running with Docker

```bash
docker compose up --build
```

This starts two containers: the app on port 8000, and Grafana Alloy on port 12345 (its own UI). Alloy tails the containers' stdout through the mounted Docker socket, scrapes `/metrics` every 15 seconds, and accepts OTLP on 4317/4318.

`LOKI_URL`, `PROMETHEUS_URL` and `TEMPO_URL` must be set in `.env` — Compose refuses to start without them rather than falling back to an endpoint that cannot work. They point at wherever your Grafana stack runs, which is not this host.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Service name, status and environment |
| GET | `/health` | Liveness — returns `"ok"` |
| GET | `/ready` | Readiness |
| GET | `/metrics` | Full Prometheus registry, in text format |
| GET | `/metrics/{prefix}` | Only the registered metrics whose name starts with `prefix` |
| GET | `/docs` | Swagger UI |

## Configuration

Every variable is optional and falls back to the default below; see `.env.example` for the full annotated file.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SERVICE_NAME` | `agents` | Stamped on every log line and used as the API title |
| `SERVICE_DESCRIPTION` | `Servidor rodando os agentes de IA` | OpenAPI description |
| `SERVICE_PUBLIC_URL` | `http://localhost:8000` | Public address of the service |
| `VERSION` | `0.1.0` | Stamped on every log line |
| `ENVIRONMENT` | `development` | Also selects the console log format: human-readable in `development`, JSON otherwise |
| `LOG_LEVEL` | `INFO` | Minimum level written to file and console |
| `HOSTNAME` | machine hostname | Injected by Docker or Kubernetes; lands in the log's `host` field |
| `POSTGRES_HOST` | `localhost` | Database host — `POSTGRES_PORT`, `USER`, `PASSWORD` and `DB` follow the same pattern |
| `UVICORN_RELOAD` | `false` | `true` enables `--reload` inside the container |
| `LOKI_URL`, `PROMETHEUS_URL`, `TEMPO_URL` | none | Telemetry destinations, required by Compose |

## Tests

```bash
make test
```

`tests/` mirrors `app/`, so `app/core/logger.py` is covered by `tests/app/core/test_logger.py`. Fixtures live in `tests/conftest.py`: `settings`, `api` (the FastAPI app) and `client` (an `AsyncClient` speaking to the app in-process, no socket). The environment is loaded from `.env.test` before anything under `app` is imported.

## Code quality

```bash
poetry run pre-commit install
```

The hook runs `make pre-commit` — Ruff, mypy and pytest — and blocks the commit if any of them fails. See `AGENTS.md` for the tooling rules.

## Layout

```
app/
  main.py              create_app, routers, exception handlers
  config.py            Settings
  core/logger.py       structured JSON logging
  core/metrics/        Prometheus registry and shared metrics
tests/                 mirrors app/
alloy/config.alloy     collector pipelines: logs, metrics, traces
docs/                  design sketches that are not yet code
.agents/skills/        the conventions this repo is written to
```

## Conventions

Every convention lives as a skill in `.agents/skills/` — observability, logging, metrics, testing, and commit and comment style. `AGENTS.md` indexes them and `CONTRIBUTING.md` is the human entry point. Read the skill that covers what you are about to touch, and when a rule changes, change it there.
