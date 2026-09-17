---
name: graph
description: How the LangGraph state graph is driven — resuming by id, astream vs invoke, the Postgres checkpointer, interrupt()/Command(resume=...) semantics and their re-execution caveat, and how progress is reported. Use whenever adding or changing a node, wiring the graph's entry point, or touching anything under app/graph/.
---

# Graph

This supersedes the RabbitMQ-based description of the graph in `docs/ARCHITECTURE.md` §3.3. That document is stale on transport and persistence; this skill is the current source of truth for how the graph itself is driven. The node-by-node responsibilities it lists (extraction, validation, confirmation, codegen, delegation, interpretation, decision, explanation) are still a reasonable reference for *what* a node does, not for *how* the graph is invoked or persisted.

## No RabbitMQ

The graph is no longer entered by consuming a queue message. The caller — another service in this system — provides a unique id and the user's prompt. That id **is** the LangGraph `thread_id`: there is no separate manual fetch of "previous state" before running the graph. LangGraph resolves it internally from the checkpointer.

```python
config = {"configurable": {"thread_id": job_id}}
```

If a checkpoint already exists under that id, invoking with it resumes; if not, invoking with the initial input starts fresh. Do not write a bespoke "load state, then decide whether to run from scratch" step — pass the id straight through.

**Open / not yet decided:** the concrete transport that hands `(id, prompt)` to the graph (HTTP route, internal call, etc.). Whatever it is, its only job is to obtain `(id, prompt)` and call the graph — it must not reimplement resume logic.

## `astream`, not `invoke`/`stream`

Always drive the graph with `ainvoke`/`astream`, never the sync `invoke`/`stream`. This service is async (FastAPI/asyncio); the sync variants block the event loop for the duration of the run, including any LLM calls inside it.

Prefer `astream` over `ainvoke` whenever the caller can consume incremental output — `ainvoke` is implemented as `astream` internally, collected down to only the final value, so it throws away the progress information `astream` gives you for free.

## Progress reporting via stream modes

Use `stream_mode=["updates", "custom"]` on `astream`, not a bespoke progress mechanism:

- `"updates"` yields `{node_name: output}` after each node finishes — coarse "which step just completed."
- `"custom"`, combined with `get_stream_writer()` called from inside a node, lets that node emit an arbitrary payload (e.g. `{"percent": 40, "detail": "..."}`) for finer-grained progress than one event per node.

Whatever consumes the `astream` loop is responsible for turning these chunks into whatever the frontend/other services need (e.g. persisting progress somewhere pollable, or forwarding over SSE) — LangGraph only gives you the events, not the delivery to the client.

## Checkpointer: Postgres, via `psycopg`, not `asyncpg`

Persistence uses `langgraph-checkpoint-postgres`'s `AsyncPostgresSaver`, added via Poetry (see `pyproject.toml`). This is a deliberate exception to the rest of the service's stack:

- It depends on `psycopg` 3 + `psycopg-pool`, **not** `asyncpg`. The rest of `codegen` (SQLAlchemy, when wired) uses `asyncpg`. Expect a second driver/pool living alongside the SQLAlchemy one — there is no way to make the checkpointer reuse an `asyncpg` connection.
- `AsyncPostgresSaver` can point at the same Postgres server/database as the rest of the system, but it does **not** support a custom schema or table names in the Python client (unlike the JS client). It creates four fixed, unqualified tables on `await checkpointer.setup()`: `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`. `setup()` must be called once (idempotent) before the graph is used with that checkpointer — this is the library's own migration mechanism, not something Liquibase/Alembic manages.
- Checkpointing itself is automatic on every superstep once the graph is compiled with `compile(checkpointer=...)`. No node needs to opt in, and there is no per-node "save now" tool to write — a node that wants state visible outside LangGraph's own tables (e.g. a plain column another service polls) is a separate, deliberate write, not a substitute for the checkpointer.

**Open / not yet decided:** how the checkpointer's connection is configured relative to `Settings` (a dedicated `.env` variable vs. reusing `POSTGRES_*` with a different driver prefix), and whether `setup()` runs at app startup or via a separate one-off command.

## `interrupt()` and `Command(resume=...)`

Both are called directly in application code — they are not framework-internal.

- `interrupt(value)` pauses the graph from inside a node: on first call it raises internally, the state is checkpointed, and `value` is surfaced to the caller as part of the interrupted `astream`/`ainvoke` result.
- Resuming means the caller invokes again with the **same `thread_id`** and `input=Command(resume=<value>)`.

**Re-execution caveat — read before adding an `interrupt()` call to a node:** on resume, the whole node function re-runs from its first line, not from the `interrupt()` call. `interrupt()` matches resume values **by the order in which `interrupt()` is called within the node**, not by identity — the first call in the node consumes the first resume value, and so on. Consequences:

- Anything a node does *before* its `interrupt()` call runs again on every resume. It must be idempotent or side-effect-free (no re-publishing an event, no duplicate row insert) unless duplication is genuinely harmless.
- Do not make whether `interrupt()` is called, or how many times, depend on data that can differ between the original run and the resumed run — that changes the call order and breaks the positional matching.

Use this for the pause points the graph actually needs: user confirmation of extracted parameters, and delegation to the worker awaiting its result.

## Naming

Everything under `app/graph/` — node names, module names, the values that appear in `stream_mode="updates"` output — is in English. (The older Portuguese node-naming convention in `docs/ARCHITECTURE.md` no longer applies.)

## References

- Superseded description of node responsibilities and the old RabbitMQ-driven entry point: `docs/ARCHITECTURE.md` §3.3 (transport and persistence sections are stale, the per-node responsibility list is not).
- Implementation: `app/graph/` (`state.py`, `builder.py`, `agent.py`, `nodes/`, `tools/`).
