# agents

FastAPI service that runs the AI agents. It is one component of a distributed system — a Spring Boot API, this server, and an execution worker — with telemetry landing in Grafana (Loki, Prometheus, Tempo) through a Grafana Alloy collector.

The service's own business logic runs as a LangGraph state graph. Another service hands it a unique id and the user's prompt; that id is used as the graph's `thread_id`, so a previous run resumes automatically if a checkpoint exists for it, and starts fresh otherwise (see `.agents/skills/graph/SKILL.md`). The transport that delivers `(id, prompt)` to the service is not decided yet — it is no longer RabbitMQ.

## Stack

| | |
| --- | --- |
| Runtime | Python 3.12 |
| Web | FastAPI, Uvicorn |
| Agents | LangGraph (`astream`, `AsyncPostgresSaver` checkpointer) |
| Settings | Pydantic Settings, read from `.env` |
| Database | PostgreSQL via SQLAlchemy 2 (async, asyncpg) and Alembic; LangGraph's checkpointer talks to the same Postgres server through a separate `psycopg` 3 connection, since that library does not support `asyncpg` |
| Telemetry | Structured JSON logging, `prometheus-client`, OpenTelemetry SDK |
| Packaging | Poetry, with `requirements*.txt` exported for pip |
| Quality | Ruff, mypy (strict), Bandit, pytest |
| Container | Docker multi-stage build, Compose with Grafana Alloy |

The database and OpenTelemetry packages are installed and configured, but no models, migrations or spans exist yet: the service starts and serves without a database, and traces are not emitted until instrumentation is wired. LangGraph's own checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) are created by `AsyncPostgresSaver.setup()`, not by Alembic.

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

`make requirements` needs the `poetry-plugin-export` plugin, which Poetry 2.0+ no longer bundles. One-time setup per machine, not per project — this installs into Poetry's own environment, not the project's:

```bash
poetry self add poetry-plugin-export
```

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
make test        # run the suite
make test-cov    # run it with a per-file coverage report
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
  graph/               the graph subsystem — see .agents/skills/graph/SKILL.md
    entrypoint.py       public run(id, prompt) -> astream — the only file meant to be
                        imported from outside app/graph/
    core/
      engine.py           StateGraph assembly — every edge and routing function
      state.py             the one shared state schema every node reads/writes
      checkpointer.py       AsyncPostgresSaver wiring
      llm/                    named model registry
      tool_dispatch.py         allowlist validation + the shared tool-execution node
    nodes/               one file per graph node (a node graduates to its own folder
                         only once it needs helpers of its own)
    prompts/             one file per node that has a prompt, centralized rather than
                         colocated with its node
    tools/               one file per tool (or tight group) — shared across nodes
tests/                 mirrors app/
alloy/config.alloy     collector pipelines: logs, metrics, traces
docs/                  design sketches that are not yet code
```

Note `app/core/` (logger, metrics — service-wide) and `app/graph/core/` (the graph's own engine layer) are different, same-named folders at different nesting levels — don't confuse them.

## Conventions

Every convention lives as a skill in `.agents/skills/` — the graph, observability, logging, metrics, testing, and commit and comment style. `AGENTS.md` indexes them and `CONTRIBUTING.md` is the human entry point. Read the skill that covers what you are about to touch, and when a rule changes, change it there.
