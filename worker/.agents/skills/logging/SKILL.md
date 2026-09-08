---
name: logging
description: Conventions for structured logging in this service — getting a logger, choosing a level, putting variable data in `extra` instead of the message, logging exceptions, the correlation fields (`job_id`, `user_id`, `trace_id`, `span_id`), and where log output goes. Use whenever adding, reviewing, or debugging a log call.
---

# Logging

## Getting a logger

```python
from app.core.logger import get_logger

logger = get_logger("app.agents.planner")
```

The logger name **must start with `app.`**. Handlers are attached to the `app` root logger, so a logger named anything else (`"planner"`, `"agents.planner"`) will not be picked up and its output will never reach `logs/app.json`.

Convention: mirror the module path — `app/agents/planner.py` → `"app.agents.planner"`.

## Levels

| Method | Use for |
| --- | --- |
| `logger.debug()` | Detail useful while developing; noisy in production. |
| `logger.info()` | Normal lifecycle events worth keeping: job accepted, message published, agent finished. |
| `logger.warning()` | Something recoverable and unexpected: retry, fallback, degraded path. |
| `logger.error()` | An operation failed and was not recovered. |
| `logger.exception()` | Same as `error()`, but attaches the traceback. Use inside `except`. |

`LOG_LEVEL` in `.env` sets the minimum level written to file and console (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`). Errors always also go to `logs/error.json`, regardless of `LOG_LEVEL`.

`LOG_LEVEL` takes the stdlib names above, but the `level` **written into the log line** is the OpenTelemetry short name: `WARNING` is emitted as `WARN` and `CRITICAL` as `FATAL`. Query Loki for `WARN`, configure `LOG_LEVEL=WARNING`.

## Structured data goes in `extra`, not in the message

The message should be a short, **constant** string. Anything variable goes in `extra`, so it stays queryable in Loki.

```python
# Good — message is constant, values are queryable fields
logger.info("code execution finished", extra={"exit_code": 0, "duration_ms": 1432})

# Bad — values are baked into the string, unqueryable
logger.info(f"code execution finished with exit code 0 in 1432ms")
```

`extra` keys land under an `extra` object in the JSON:

```json
{"message": "code execution finished", "extra": {"exit_code": 0, "duration_ms": 1432}}
```

Values must be JSON-serializable. Pass `str(obj)` or a dict, not arbitrary objects.

## Logging exceptions

Use `logger.exception()` inside an `except` block — it attaches the formatted traceback to an `exception` field.

```python
try:
    result = await run_in_sandbox(code)
except SandboxTimeout:
    logger.exception("sandbox execution timed out", extra={"timeout_s": 30})
    raise
```

Do not put the traceback in the message yourself, and do not log-and-swallow: if you log an error, either re-raise or handle it deliberately.

## Correlation context

Four correlation fields are attached automatically when available. **Never pass them in `extra` manually** — they are populated by the logging layer.

| Field | Source | Meaning |
| --- | --- | --- |
| `trace_id` | active OpenTelemetry span | One flow through the whole system, across services. |
| `span_id` | active OpenTelemetry span | One unit of work inside that flow. |
| `job_id` | `job_id_ctx` | The business job, stable across retries. |
| `user_id` | `user_id_ctx` | The user the work belongs to. |

`trace_id` and `span_id` require an active OpenTelemetry span; outside an instrumented flow they are simply absent. Nothing to do in application code.

`job_id` and `user_id` are ours. Set them once at the entry point — where a RabbitMQ message is consumed or a request arrives — and every log line in that task inherits them:

```python
from app.core.logger import get_logger, job_id_ctx, user_id_ctx

logger = get_logger("app.worker.consumer")

async def handle_message(message):
    payload = json.loads(message.body)
    job_id_ctx.set(payload["job_id"])
    user_id_ctx.set(payload["user_id"])

    logger.info("job accepted")  # job_id and user_id are attached automatically
```

Prefer `token = job_id_ctx.set(...)` / `job_id_ctx.reset(token)` when the same task handles several jobs in sequence, so values do not leak between them.

## Where logs go

| Destination | Contents |
| --- | --- |
| `logs/app.json` | Everything at or above `LOG_LEVEL`. Rotates at 10 MB, 5 backups. |
| `logs/error.json` | `ERROR` and above only. Same rotation. |
| stdout | Human-readable colored text in `development`; the same JSON otherwise. |

Writing is asynchronous: records go through a queue and are written by a background thread, so logging never blocks the event loop. `stop_logger()` is called on shutdown in the lifespan to flush what is pending — do not call it elsewhere.

## References

- The envelope these fields land in, and why it is a cross-service contract: `.agents/skills/observability/SKILL.md`
- When to reach for a metric instead: `.agents/skills/metrics/SKILL.md`
- Implementation: [`app/core/logger.py`](app/core/logger.py)
