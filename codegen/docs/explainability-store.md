# Explainability store

A sketch, not an implementation — no tables exist yet. Once the SQLAlchemy models and the Alembic migration are written, they are the source of truth and this file should shrink to whatever they cannot express.

The rule this serves is in [`.agents/skills/observability/SKILL.md`](../.agents/skills/observability/SKILL.md): telemetry is sampled and expires, so the record of what an agent did belongs in Postgres, written by the code that did the work.

## Shape

Two tables. `agent_run` is one attempt at producing an outcome for a job; `agent_step` is one unit of work inside that attempt, and steps form a tree — the same shape as a trace, kept somewhere that does not sample or expire.

```sql
create table agent_run (
    id             uuid        primary key,
    job_id         text        not null,
    user_id        text,
    attempt        integer     not null,
    agent_name     text        not null,
    agent_version  text        not null,
    status         text        not null check (status in ('running', 'succeeded', 'failed')),
    input          jsonb       not null,
    output         jsonb,
    error          text,
    started_at     timestamptz not null,
    finished_at    timestamptz,
    trace_id       text,
    schema_version integer     not null,

    unique (job_id, attempt)
);

create index on agent_run (job_id);
create index on agent_run (user_id, started_at desc);
create index on agent_run (trace_id) where trace_id is not null;
```

```sql
create table agent_step (
    id             uuid        primary key,
    run_id         uuid        not null references agent_run (id) on delete cascade,
    parent_step_id uuid        references agent_step (id) on delete cascade,
    seq            integer     not null,
    kind           text        not null check (kind in ('llm_call', 'tool_call', 'retrieval', 'decision')),
    name           text        not null,
    status         text        not null check (status in ('running', 'succeeded', 'failed')),
    model          text,
    model_params   jsonb,
    input          jsonb,
    output         jsonb,
    payload_uri    text,
    tokens_in      integer,
    tokens_out     integer,
    error          text,
    started_at     timestamptz not null,
    finished_at    timestamptz,
    span_id        text,

    unique (run_id, seq)
);

create index on agent_step (run_id, seq);
create index on agent_step (parent_step_id);
```

## Why the columns are what they are

`id` is minted here, not borrowed from telemetry. Everything the domain joins on must be a value this service guarantees exists.

`job_id` is the business job and is stable across retries; `attempt` distinguishes the runs under it. One job has many runs, which is precisely why a trace id could never identify a job.

`agent_version` and `model` are provenance. "Why did it answer that" is unanswerable without knowing which agent build and which model produced it, and both change under you.

`schema_version` exists because this is an audit artifact: rows written years apart must be interpretable, and the shape will change.

`trace_id` and `span_id` are nullable breadcrumbs. Nullable is the honest type — the trace may never have been sampled, and the tracer may not have been wired up when the row was written. Nothing reads them to make a decision; they exist so a person can pivot to Tempo while the trace is still there.

`payload_uri` is the escape hatch for large prompts and completions: keep the row small, put the blob in object storage, and store the pointer. Inline `jsonb` is fine while payloads stay small.

`parent_step_id` plus `seq` reconstruct the tree and the order within a level. A retrieval nested under an LLM call is a child, not a sibling.

## Write path

Insert the `agent_run` row when the attempt starts, with `status = 'running'`. A process that dies mid-run then leaves evidence that it ran, which is the case you most need explained.

Append `agent_step` rows as steps complete, and close the run with its status, output and `finished_at`.

Commit the explanation before acking the RabbitMQ message. A message acked without its record is an outcome nobody can account for.

Never sample it, and never make it best-effort. If the explanation cannot be written, the run failed — shipping an answer that cannot be explained defeats the requirement the store exists for.

## Retention and PII

Retention is set by the obligation the store serves, not by Loki's or Tempo's config, and deletion is an explicit purge that someone decided on — not a TTL that silently ages rows out.

Prompts, completions and retrieved documents routinely contain user data. This store is where they live, redacted at write time per policy. They never go into `extra` on a log line and never become a metric label.

## Pivoting between the two systems

From a log line: `job_id` finds every attempt and its full explanation; `trace_id` opens the trace while it still exists.

From a run: `trace_id` and `span_id` open the waterfall for latency and infrastructure detail that this store deliberately does not keep.
