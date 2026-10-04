---
name: graph
description: How the LangGraph state graph is driven and organized — the core/nodes/prompts/tools module layout, where edges and routing live, the shared tool-execution node's return-routing rule, resuming by id, astream vs invoke, the Postgres checkpointer, interrupt()/Command(resume=...) semantics and their re-execution caveat, and how progress is reported. Use whenever adding or changing a node, a tool, a prompt, an edge, or the graph's entry point.
---

# Graph

The implemented graph is driven by RabbitMQ consumers through `GraphRouter` and `app/graph/entrypoint.py`. Read `docs/ARCHITECTURE.md` §3.3 for current responsibilities and `docs/FLUXO-SPRINT-2.md` for approved work that is not yet implemented. This skill describes local graph conventions; it does not override the repository's transport or ownership rules.

## Module layout

Organized by technical layer, not by feature-per-folder — the nodes are stages of one pipeline, tightly coupled through shared state and centrally-owned edges, not independent bounded contexts. Feature identity is preserved as filenames within each layer instead:

Everything lives inside `app/graph/`, not at the top level of `app/` — this is the graph subsystem, sitting alongside `app/main.py`, `app/config.py`, `app/core/` (the pre-existing, graph-unrelated `logger.py`/`metrics/`).

```
app/graph/
  entrypoint.py      # public run/resume entry points -> astream — the one file meant to be
                     # imported from outside app/graph/
  core/
    engine.py        # StateGraph assembly: every edge and conditional-edge/routing function lives here
    state.py          # the one shared state schema every node reads/writes
    checkpointer.py    # AsyncPostgresSaver wiring
    llm/               # named model registry — see below
    tool_dispatch.py    # allowlist validation + the shared tool-execution node — see below
  nodes/
    load_rule.py
    code_generation.py
    ...                # one file per node; a node graduates to its own folder only once
                        # it accumulates enough of its own helpers to need one
  prompts/
    code_generation.py
    ...                # one file per node that has a prompt; centralized rather than
                        # colocated with its node, since prompts are a first-class audit
                        # surface (AGENTS.md Security) and centralizing costs nothing —
                        # each prompt is already 1:1 with the node that uses it
  tools/
    <tool_name>.py      # one file per tool (or tight group). Tools are a shared resource,
                        # not a node's property — more than one node may call the same tool
```

Note the naming collision with the pre-existing `app/core/` (logger, metrics): that one is service-wide infrastructure unrelated to the graph. `app/graph/core/` is the graph's own engine layer. Don't merge them and don't move logger/metrics into `app/graph/core/`.

`entrypoint.py` sits at `app/graph/`, not inside `core/` — it's the one function anything outside the graph subsystem is allowed to import (`GraphRouter`, through the application wiring). Everything in `core/` is internal to the graph and should never be imported from outside `app/graph/`; keeping the entrypoint one level up from `core/` makes that boundary visible in the import path itself, the same way `app/main.py` sits outside `app/core/` at the service level.

**Rule: all edges and routing live in `app/graph/core/engine.py`, never inside a node's own file.** A node's position in the pipeline — what precedes it, what follows it, which branch a routing decision sends it down — is graph-topology knowledge, not something the node itself should encode. This keeps the full shape of the graph readable in one place and keeps a node's own file limited to its actual logic: building its input from state, calling its model/tools, parsing the result back into a state update.

`app/graph/core/llm/` holds a **registry** of named models, not a single client — the system may use more than one LLM. A node asks the registry for the model it needs by name (e.g. `get_model("extraction")`); provider/config details for every model stay in one place.

## The shared tool-execution node

**Nothing in the graph uses tools today**, so `app/graph/core/tool_dispatch.py` and the `tools` node do not exist. `code_generation` binds no tools. The graph does have conditional routing after `decision` to `suggest_adaptation` or `END`. The rule below is a convention for future tool use, not an implemented node.

There is exactly **one** tool-execution node for the whole graph, not one per tool-using node. Executing a requested tool call ("look up the name and args, run the matching function, return the result") is generic — it doesn't vary by which node asked for it, so splitting it per node would just re-duplicate the thing centralizing `app/graph/tools/` was meant to avoid. It lives in `app/graph/core/` (alongside `tool_dispatch.py`, since dispatch-and-validate and execute-and-return are one unit), not in `nodes/` — it has no feature name of its own; it's infrastructure every tool-using node shares.

Before running anything, it validates the requested tool name and arguments against the **calling node's** declared allowlist (`app/graph/core/tool_dispatch.py`) — this is the one auditable chokepoint for the "the model's own output never decides, by itself, which tool executes" rule in `AGENTS.md`.

**Rule for the conditional edge out of the tool node:** the edge leaving the tool-execution node must route back to whichever node issued the tool call, not to a fixed next step. Concretely:

- The identity of the calling node must be recoverable from state at the point the tool node runs — e.g. carried as a field on state, or derivable from which node's output produced the pending tool call. Decide this representation once, in `app/graph/core/state.py`; don't let each node invent its own way of marking "return here."
- The conditional edge function that reads this and picks the destination is a `app/graph/core/engine.py` routing function, same as every other edge — it does not belong to the tool node itself and does not belong to any individual node file.
- A node that expects to loop (call a tool, see the result, possibly call another tool) reaches this same conditional edge again after the tool node returns to it — don't special-case "second call" vs "first call" in the routing function; the destination logic is just "go back to whoever is recorded as the caller," repeatable any number of times.

## The graph diagram

`docs/graph.md` holds a Mermaid diagram of the compiled graph, generated by `app/graph/diagram.py`. After changing a node or an edge in `app/graph/core/engine.py`, run `make graph`. `tests/app/graph/test_diagram.py` fails while the file is stale, so `make pre-commit` refuses a commit that changes the graph without it. The diagram is Mermaid text, never PNG: it diffs in review, and the PNG renderer sends the graph's structure to an external service.

## RabbitMQ entry and cycle identity

RabbitMQ consumers enter the graph through `GraphRouter`. `regra-submetida` starts or continues a cycle; `simulacao-concluida.codegen` resumes execution. Do not add internal HTTP calls.

The current cycle id comes from `thread_do_ciclo(job_id, regra_id)` and is `job_id:regra_id`. A suggested rule has its own thread. Legacy lookup by job is allowed only for a checkpoint of the same rule.

```python
config = {"configurable": {"thread_id": thread_do_ciclo(job_id, regra_id)}}
```

The entrypoint inspects checkpoints to distinguish a fresh cycle, an early result, a paused cycle and an already finished cycle. Existing cycles continue without a new initial input. Resume uses `Command(resume=...)`; do not bypass these guards or erase the checkpoint-based duplicate protection.

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

- It depends on `psycopg` 3 + `psycopg-pool`, **not** `asyncpg`. The rest of `codegen` uses SQLAlchemy with `asyncpg`. Expect a second driver/pool living alongside the SQLAlchemy one — there is no way to make the checkpointer reuse an `asyncpg` connection.
- `AsyncPostgresSaver` can point at the same Postgres server/database as the rest of the system, but it does **not** support a custom schema or table names in the Python client (unlike the JS client). It creates four fixed, unqualified tables on `await checkpointer.setup()`: `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`. `setup()` must be called once (idempotent) before the graph is used with that checkpointer — this is the library's own migration mechanism, not something Liquibase/Alembic manages.
- Checkpointing itself is automatic on every superstep once the graph is compiled with `compile(checkpointer=...)`. No node needs to opt in, and there is no per-node "save now" tool to write — a node that wants state visible outside LangGraph's own tables (e.g. a plain column another service polls) is a separate, deliberate write, not a substitute for the checkpointer.

`Settings` supplies the database connection configuration. The lifespan in `app/main.py` opens the psycopg pool and runs `setup()` at startup before consumers start. Domain migrations remain owned by the API through Liquibase.

## `interrupt()` and `Command(resume=...)`

Both are called directly in application code — they are not framework-internal.

- `interrupt(value)` pauses the graph from inside a node: on first call it raises internally, the state is checkpointed, and `value` is surfaced to the caller as part of the interrupted `astream`/`ainvoke` result.
- Resuming means the caller invokes again with the **same `thread_id`** and `input=Command(resume=<value>)`.

**Re-execution caveat — read before adding an `interrupt()` call to a node:** on resume, the whole node function re-runs from its first line, not from the `interrupt()` call. `interrupt()` matches resume values **by the order in which `interrupt()` is called within the node**, not by identity — the first call in the node consumes the first resume value, and so on. Consequences:

- Anything a node does *before* its `interrupt()` call runs again on every resume. It must be idempotent or side-effect-free (no re-publishing an event, no duplicate row insert) unless duplication is genuinely harmless.
- Do not make whether `interrupt()` is called, or how many times, depend on data that can differ between the original run and the resumed run — that changes the call order and breaks the positional matching.

The implemented pause waits for the worker's result. Sprint 2 adds conditional correction rounds only when validation finds problems; it does not require manual confirmation for every valid rule. Checkpoints are deleted only after the `api` announces `job-encerrado`, through `app/graph/entrypoint.py::ciclos_do_job`/`apagar_ciclos`, never by a node. `jobs_grafo_encerrados` keeps the terminal-cycle deduplication after the deletion, and a cycle still waiting for its result is kept until the result is processed - see `app/mensageria/limpeza.py` and DEC-095.

## Naming

Node names, tool names, module/file names, the values that appear in `stream_mode="updates"` output — all English. (The older Portuguese node-naming convention in `docs/ARCHITECTURE.md` no longer applies.)

## References

- Current responsibilities and RabbitMQ entry point: `docs/ARCHITECTURE.md` §3.3.
- Approved Sprint 2 evolution: `docs/FLUXO-SPRINT-2.md`.
- Implementation: `app/graph/core/`, `app/graph/nodes/`, `app/graph/prompts/`, `app/graph/tools/`.
