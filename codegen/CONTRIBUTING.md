# Contributing

This service is one component of a distributed system (Spring Boot API, this agents server, and the execution worker), all communicating asynchronously over RabbitMQ. Telemetry lands in Grafana, backed by Loki (logs), Prometheus (metrics), and Tempo (traces), collected by Alloy.

Conventions live as skills under [`.agents/skills/`](.agents/skills/), one directory per topic, so that agents and people read the same source. This file is the index — the rules themselves are in the skills, not here.

## Getting started

```bash
make install                    # poetry install
poetry run pre-commit install   # hooks: Ruff, mypy, Bandit
make dev                        # uvicorn with --reload
make pre-commit                 # lint + format + typecheck + tests
```

## Conventions

| Topic | Where | Covers |
| --- | --- | --- |
| Telemetry overview | [`.agents/skills/observability`](.agents/skills/observability/SKILL.md) | The log envelope as a cross-service contract, and which signal (log, metric, trace) answers which question. |
| Logging | [`.agents/skills/logging`](.agents/skills/logging/SKILL.md) | Logger naming, levels, `extra` vs. the message, exceptions, correlation context, where output lands. |
| Metrics | [`.agents/skills/metrics`](.agents/skills/metrics/SKILL.md) | Declaring and using metrics, Counter/Gauge/Histogram, label cardinality, naming, exposure. |
| Testing | [`.agents/skills/testing`](.agents/skills/testing/SKILL.md) | Asserting required behavior rather than observed behavior, proving a test can fail, layout, fixtures, and shared state. |
| Commits and comments | [`.agents/skills/commit-and-comments`](.agents/skills/commit-and-comments/SKILL.md) | Conventional Commits in pt-BR, the `Review` trailer, and when a code comment earns its place. |
| Code quality | [`AGENTS.md`](AGENTS.md) | Ruff, mypy strict, Bandit, and the checks that must pass before pushing. |

Changing a convention means changing its skill. Anything documented in two places will drift.
