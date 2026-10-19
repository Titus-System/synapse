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

Business artifacts are stored in the existing PostgreSQL domain model: prompts, model responses, generated code, rules and simulation results. The API persists the audit trail from `no-concluido`; codegen writes only the artifacts it produces. Telemetry correlation is not a substitute for these references, and no generic `agent_run`/`agent_step` schema is implemented. Full US05 explanation remains an evolution requirement.

Prompts and completions routinely carry user data. They belong in that store, under its redaction and retention policy — never in `extra` on a log line, and never as a metric label.

The persisted job, rule version, simulation and artifact references define the audit path. Checkpoints are recovery infrastructure, not the audit record.

## The log envelope

```json
{
  "timestamp": "2026-10-02T12:00:00Z",
  "level": "INFO",
  "message": "Execution result received",
  "service.name": "synapse-codegen",
  "environment": "development",
  "service.version": "0.1.0",
  "host.name": "codegen-01",
  "job_id": "3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021",
  "no": "await_execution",
  "trace_id": "99816320ef13842d20d2ae5b108e6d37",
  "span_id": "22cd8c4626502cca",
  "extra": {"execution_status": "sucesso"}
}
```

The canonical envelope is `contracts/observability/log.schema.json`. `service.name` is `synapse-codegen`; `job_id` is required during job processing, and `no` identifies a codegen node. Optional settings fields use `service.version` and `host.name`. Do not rename these to `service`, `version` or `host`.

Correlation fields are omitted entirely when empty, rather than emitted as `null`.

`level` carries the OpenTelemetry short names — `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL` — because it is a Loki label and polyglot services would otherwise split the same level across two label values. The spec keeps `SeverityText` as the source's own wording and normalizes on the numeric `SeverityNumber` instead; this envelope has no numeric field, so it normalizes the text. Logback already emits these names, so the JVM side translates nothing; the Python side maps `WARNING`→`WARN` and `CRITICAL`→`FATAL` in `severity_text()`.

## References

- Writing log calls: `.agents/skills/logging/SKILL.md`
- Declaring and using metrics: `.agents/skills/metrics/SKILL.md`
- Existing artifact storage: [`docs/explainability-store.md`](../../../docs/explainability-store.md).
- Canonical log envelope: [`contracts/observability/log.schema.json`](../../../../contracts/observability/log.schema.json).
- Log formatters must follow the shared schema. Changes to that schema require authorization and validation of the affected producers and consumers.
