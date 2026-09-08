---
name: metrics
description: Conventions for Prometheus metrics in this service — using existing metrics, declaring new ones in `global_metrics.py`, choosing between Counter/Gauge/Histogram, the label-cardinality rule, naming, and how the registry is exposed. Use whenever adding a metric, adding a label to one, or deciding whether something should be a metric at all.
---

# Metrics

Metrics answer aggregate questions ("what is the error rate?", "what is p95 latency?"). Per-event detail belongs in logs, not here.

## Using existing metrics

Shared metrics are declared once in [`app/core/metrics/global_metrics.py`](app/core/metrics/global_metrics.py). Import and use them:

```python
from app.core.metrics.global_metrics import job_runs, job_duration

job_runs.labels(job_name="generate_code").inc()
job_duration.labels(job_name="generate_code").observe(elapsed_seconds)
```

For histograms, prefer the context manager — it records the duration even when the block raises:

```python
with job_duration.labels(job_name="generate_code").time():
    await run_agent(payload)
```

Metrics with no labels are used directly:

```python
from app.core.metrics.global_metrics import system_cpu_usage

system_cpu_usage.set(cpu_percent)
```

## Declaring a new metric

Register it in `global_metrics.py` at import time, never inside a function (re-registering the same name raises).

```python
from .prometheus import prometheus

sandbox_timeouts = prometheus.register_counter(
    "sandbox_timeouts_total",
    "Sandbox executions killed for exceeding the time limit",
    ["image"],
)
```

`register_*` is idempotent by name: calling it twice returns the same collector.

## Choosing a type

| Type | Use for | Never |
| --- | --- | --- |
| `Counter` | Values that only go up: requests served, jobs failed, messages consumed. | Values that can decrease. |
| `Gauge` | Values that go up and down: queue depth, memory in use, active workers. | Things you want rates from. |
| `Histogram` | Distributions you want percentiles from: durations, payload sizes. | Low-volume one-off values. |

For a counter, ask Prometheus for the rate (`rate(job_runs_total[5m])`) rather than tracking the rate yourself.

## Label cardinality — the one rule that matters

**Never use an unbounded value as a label.** Each distinct label combination creates a separate time series in Prometheus; high-cardinality labels will degrade and eventually take down the server.

```python
# NEVER do this
job_runs.labels(job_name=job_id).inc()           # unbounded
request_count.labels(endpoint=f"/jobs/{job_id}").inc()  # unbounded
```

```python
# Do this — bounded set of values, and the templated route
job_runs.labels(job_name="generate_code").inc()
request_count.labels(method="GET", endpoint="/jobs/{id}", status="200").inc()
```

Banned as labels: `job_id`, `user_id`, `trace_id`, `span_id`, email addresses, raw URLs, timestamps, error messages.

That information is not lost — it belongs in the **log line**, which is built for high cardinality. This is the division of labor between the two signals: metrics tell you *that* the error rate rose, logs tell you *which* jobs failed and why.

## Naming

Follow the Prometheus conventions, since Grafana and alerting rules assume them:

- `snake_case`, prefixed by the subsystem: `sandbox_`, `job_`, `system_`.
- Counters end in `_total`.
- The unit goes in the name: `_seconds`, `_bytes`. Use base units — seconds, not milliseconds.
- Describe what is measured, not how it is stored: `job_duration_seconds`, not `job_duration_histogram`.

## Exposing metrics

`prometheus.get_all()` returns the full registry in Prometheus text format, and `prometheus.get_all_by_prefix(prefix)` returns a filtered subset. Both are served by the metrics router in [`app/main.py`](app/main.py), at `GET /metrics` and `GET /metrics/{prefix}` — the router is excluded from the OpenAPI schema, so a new metric needs no endpoint work of its own.

## References

- Why a value belongs in a log line instead of a label: `.agents/skills/logging/SKILL.md`
- Which signal answers which question: `.agents/skills/observability/SKILL.md`
- Implementation: [`app/core/metrics/prometheus.py`](app/core/metrics/prometheus.py)
