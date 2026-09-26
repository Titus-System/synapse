---
name: observability
description: How this service's telemetry fits together — the distributed system it belongs to, the log envelope as a cross-service contract, and which signal (log, metric, trace) answers which question. Use when deciding whether something should be logged or measured, when adding/renaming/removing a top-level field of the log envelope, or when tracing a failure across services.
---

# Observability

This service is one component of a distributed system (Spring Boot API, this agents server, and the execution worker), all communicating asynchronously over RabbitMQ. Telemetry lands in Grafana, backed by Loki (logs), Prometheus (metrics), and Tempo (traces), collected by Alloy.

Because the components are polyglot, **the log envelope is a contract**, not a local convention. Adding, renaming, or removing a top-level field means updating the other services too. Custom data belongs under `extra`, which is free-form.

## Which signal do I use?

| You want to know | Signal |
| --- | --- |
| What happened in this specific job, and why it failed | **Log** — filter by `job_id` |
| How long each step of one request took | **Trace** — filter by `trace_id` |
| Whether failures are rising across all jobs | **Metric** |

The three connect: an alert fires on a metric, you filter logs for the affected window, and a log line's `trace_id` takes you to the exact trace in Tempo.

Metrics answer aggregate questions ("what is the error rate?", "what is p95 latency?"). Per-event detail belongs in logs, not there. High-cardinality values — `job_id`, `user_id`, error messages — are exactly what a log line is built for and exactly what will take down a Prometheus server as a label.

## Telemetry is not the record

All three signals are sampled, expiring and lossy by design: Prometheus keeps aggregates rather than events, traces are sampled, Loki and Tempo age data out, and both the log queue in `app/core/logger.py` and the OTLP exporter drop under backpressure. That is the correct trade for operating a system, and it is what disqualifies all three as a system of record.

So the dependency runs one way. **Telemetry may depend on business identity; business logic may never depend on telemetry.** Putting `job_id` on a span is right. Branching on a `trace_id`, joining on it, or using it as an idempotency key is not — it makes correctness a function of the sampling configuration, and the value is absent whenever the tracer is not wired up.

Anything the product owes an answer for is domain data, written to Postgres by the code that did the work. For the agents that is the explainability record: which model ran, with which prompt and parameters, which tools it called, what each returned, and what was produced. It is never sampled — an answer that cannot be explained is not shippable — and its retention is set by the obligation, not by Tempo's config. `trace_id` and `span_id` are nullable breadcrumb columns on those rows: while the trace exists they take you to the waterfall, and once it ages out the explanation is still there.

Prompts and completions routinely carry user data. They belong in that store, under its redaction and retention policy — never in `extra` on a log line, and never as a metric label.

A span tree is the right *shape* for an agent's reasoning; the mistake is letting the tracing backend be the one that keeps it. Own the tree you depend on.

## The log envelope

```json
{
  "timestamp": "2026-09-05T22:27:40.761838+00:00",
  "level": "INFO",
  "message": "code execution finished",
  "service": "agents",
  "environment": "development",
  "version": "0.1.0",
  "host": "hal",
  "logger": "app.worker.consumer",
  "module": "consumer",
  "function": "handle_message",
  "line": 42,
  "trace_id": "99816320ef13842d20d2ae5b108e6d37",
  "span_id": "22cd8c4626502cca",
  "job_id": "job-42",
  "user_id": "user-7",
  "extra": {"exit_code": 0}
}
```

`service`, `environment`, `version`, and `host` come from settings and are stamped on every line. `host` resolves from the `HOSTNAME` env var that Docker/Kubernetes injects, falling back to the machine hostname.

Correlation fields are omitted entirely when empty, rather than emitted as `null`.

`level` carries the OpenTelemetry short names — `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL` — because it is a Loki label and polyglot services would otherwise split the same level across two label values. The spec keeps `SeverityText` as the source's own wording and normalizes on the numeric `SeverityNumber` instead; this envelope has no numeric field, so it normalizes the text. Logback already emits these names, so the JVM side translates nothing; the Python side maps `WARNING`→`WARN` and `CRITICAL`→`FATAL` in `severity_text()`.

## References

- Writing log calls: `.agents/skills/logging/SKILL.md`
- Declaring and using metrics: `.agents/skills/metrics/SKILL.md`
- Schema sketch for the explainability record: [`docs/explainability-store.md`](docs/explainability-store.md)
- The envelope is produced by `JsonFormatter` in [`app/core/logger.py`](app/core/logger.py), and on the JVM side by `JsonLogFormatter` in the `api` repo (`src/main/java/synapse/api/core/logging/`). Both have tests pinning the field set — change one and the other's suite is the reminder.
