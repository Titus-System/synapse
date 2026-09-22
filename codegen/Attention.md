# Attention

Decisions made while implementing T-094 (`TASK1.md`) and T-096 (`TASK2.md`) that need a
human's eyes before they're taken as settled. Delete an item once it's been resolved and
folded into the right permanent doc (`AGENTS.md`, a skill, `docs/mensageria.md`, an ADR).

## The graph is never called directly from a message handler

`Consumer.receber` (`app/mensageria/consumers.py`) never imports LangGraph or calls the
graph itself. It only calls `RoteadorGrafo.entregar`. The concrete `GraphRouter`
(`app/mensageria/roteamento.py`) is the one place that turns a `RegraSubmetida` into the
graph's initial state and calls `app/graph/entrypoint.py::run_to_completion` - a function
dedicated to that call, distinct from ad-hoc graph invocation, so the message-handling
layer stays free of graph-topology concerns.

## `GraphRouter` is built before its dependencies exist

`GraphRouter.sessoes`/`GraphRouter.producers` start as `None` and are filled in by
`ciclo_de_vida` (`app/main.py`) once the database engine and the broker connection are
ready. This mirrors how `aplicacao.state.producers` is already assigned post-hoc. If
`GraphRouter` grows a dependency that must be present before construction, this pattern
needs revisiting.

## Regra inexistente ou inválida: `reject`, never `nack`

`load_rule` fails with `RegraInvalidaError` (`app/repositorio/regras.py`) when the rule
row is missing or fails `RepresentacaoRegra`'s contract. This is a permanent condition -
redelivering the message will not make a missing/invalid rule appear - so
`Consumer.receber` rejects it without requeue, the same way it already does for
`JobDesconhecidoError`. Documented in `docs/mensageria.md`.

## `code_generation`'s model, verified against the real API

`app/graph/core/llm/registry.py` registers `code_generation` as `gemini-3.1-flash-lite`,
`temperature=0`, `max_output_tokens=8192`, `timeout=60`, `max_retries=2`. This was not
always the case - two real bugs surfaced only by actually running the graph end to end
against a local Postgres/RabbitMQ and the real Gemini API (see PR description):

1. **The first model id, `gemini-3.1-pro`, doesn't exist.** `models.list()` against the
   real API has no such model. The "pro"-tier models that do exist
   (`gemini-3.1-pro-preview`, `gemini-2.5-pro`) return `RESOURCE_EXHAUSTED` (quota 0) on
   this project's free-tier key. `gemini-3.1-flash-lite` (the same model the removed
   `calculator` node used) has real quota and the same 1,048,576-token input window,
   comfortably above this prompt's real size (~80k chars / ~23k tokens for the fixture
   used to verify).
2. **`AIMessage.content` was assumed to always be `str`.** Against the real API,
   `langchain_google_genai` returns it as a list of content-part dicts
   (`[{"type": "text", "text": "...", "extras": {...}}]`), even for a plain reply. The
   original `isinstance(content, str)` check silently treated every real response as
   empty, so `code_generation` failed on every real call. Combined with the RabbitMQ
   redelivery-with-no-backoff behavior noted below, this produced a tight failure/requeue
   loop that made repeated real, billable calls before it was caught - see
   `_text_content` in `app/graph/nodes/code_generation.py` and its regression test.

`modelo-llm.schema.json` requires `versao` (non-empty string), but Gemini's response
carries no reliable per-call snapshot to read it from. The registry hardcodes `"stable"`
as a placeholder - replace it once there's an actual policy for tracking Gemini
snapshots.

The opt-in `llm`-marked test (`test_code_generation_calls_the_real_provider_and_...`) is
gated on `Settings.GOOGLE_API_KEY` being set, per TASK2's own spec - not on a separate
opt-in flag like the `rabbitmq` marker uses (`RUN_RABBITMQ_INTEGRATION=1`). In any
environment whose `.env` already has a real key (this one does, locally), a plain
`pytest`/`make test`/`make pre-commit` run makes one real network call. Worth revisiting
if that surprises anyone.

## RabbitMQ `consumer_timeout` vs. the LLM client timeout

The `regra-submetida` message stays unacked for the whole graph run, including the
`code_generation` model call. Its client-side timeout (60s, see above) must stay below
RabbitMQ's `consumer_timeout` for that queue, or the broker will redeliver a message
that is still being processed. This is infra/deploy configuration (`deploy/`), out of
this PR's scope - flagging it so it isn't lost. It is not hypothetical: with no
`consumer_timeout` override in `deploy/`, a `nack(requeue=True)` from any transient node
failure (see the real bug above) redelivers immediately, with no backoff - confirmed by
running it locally: a failing message was reprocessed roughly every 0.6s, calling the
real provider every time, until stopped.

## `code_generation` is the last node for now

`app/graph/core/engine.py` wires `START -> load_rule -> code_generation -> END`.
`persist_response` (T-097) does not exist yet; whoever implements it adds the
`code_generation -> persist_response` edge and removes the direct edge to `END`.

## Tool infrastructure was removed, not just the `calculator` node

`app/graph/core/tool_dispatch.py`, `app/graph/tools/arithmetic.py`, the `calculator`
node and its prompt were deleted along with their tests: `code_generation` sends the
prompt as a single message with no `bind_tools` call, so nothing in the graph uses
tools right now. If a future node needs one, the shared tool-execution node described
in `.agents/skills/graph/SKILL.md` ("There is exactly one tool-execution node for the
whole graph") should be reintroduced then, not kept around empty in the meantime.

## Naming: English for new code, existing Portuguese interface names kept as-is

New modules/functions/comments in this change are in English. Names that are part of an
interface this PR does not own alone were kept exactly as specified, to avoid silently
breaking a contract other work depends on:

- `AgentState` field names (`job_id`, `regra_id`, `origem`, `competencias`, `orcamento`,
  `representacao_regra`, `prompt_enviado`, `resposta_bruta`, `modelo`, `consumo_tokens`,
  and the T-097 fields already reserved in the TypedDict) - the exact names agreed across
  T-094/T-096/T-097 in `TASK1.md`/`TASK2.md`.
- `config["configurable"]["sessoes"]`/`["producers"]` - same reason.
- `RoteadorGrafo.entregar`, `RegraSubmetida`, and the rest of the pre-existing
  `app/contratos/`, `app/mensageria/` and domain vocabulary - established project
  convention (see `AGENTS.md`), not something this task owns.

## Production wiring: verified `regra-submetida` -> `load_rule` -> `code_generation`, not further

`app.main:criar_aplicacao_padrao` (used by `run.py`, `entrypoint.sh`, `make run`/`dev`)
builds a real `GraphRouter` and starts the `regra-submetida` consumer. This was run for
real, locally: `deploy/docker-compose.yml`'s `postgres`+`rabbitmq`+`api` (for real
Liquibase migrations), a real `usuarios`/`jobs`/`regras` row, codegen pointed at that
stack, and a real `regra-submetida` message published to the queue. Confirmed: the
consumer picks it up, `load_rule` reads and validates the real row, `code_generation`
calls the real Gemini API and gets back a single ` ```python ` block, the graph run
completes, and the message is acked (queue back to 0/0) - the two bugs above were found
and fixed this way. The full `POST /jobs` -> `executar-codigo` ->
`resultados_simulacao` path named in TASK1's "Validação final" still needs T-097/T-098
in `develop` - not exercised here.
