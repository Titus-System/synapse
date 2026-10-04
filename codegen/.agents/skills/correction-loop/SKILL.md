---
name: correction-loop
description: How codegen takes part in the rule correction loop - one graph cycle per rule version opened by `parametros-confirmados`, ending a rule with conflicts by publishing them instead of failing, the separate re-extraction cycle opened by `correcao-submetida`, which exception maps to which broker decision, the router, broker and DTO changes the new messages need, and what never leaves the process. Use when implementing T-218 to T-221 or T-224, or when debugging a correction that never produced a proposal or a pause that never reached the api.
---

# Correction loop in codegen

Read the root [`correction-loop`](../../../../.agents/skills/correction-loop/SKILL.md) skill first: it has the joint state table and the idempotency key of every step. This skill covers how the graph, the router and the broker implement codegen's part. The [`graph`](../graph/SKILL.md) skill still governs node layout, edges, checkpoints and progress.

## Two kinds of cycle, neither waits for the user

| Cycle | Thread | Opened by | Starts at | Ends with |
| --- | --- | --- | --- | --- |
| Rule | `thread_do_ciclo(job_id, regra_id)`, i.e. `job_id:regra_id` | `regra-submetida` for the root version, `parametros-confirmados` for every later one | `load_rule`, then domain validation | conflicts: `etapa-alterada` with `aguardando_correcao`; none: code generation and the existing worker pause |
| Re-extraction | `thread_da_correcao(job_id, submissao_id)`, i.e. `job_id:correcao:submissao_id` | `correcao-submetida` | `reextract_rule` | `correcao-proposta`, or a permanent failure on `extracao_parametros` |

The loop adds no `interrupt()`. `await_execution` stays the only pause. Do not model a correction as resuming a paused rule cycle: the corrected rule is a new version, so it gets a new cycle on a new thread, and the durable loop state lives in the api.

Pick the entry edge from validated message fields, never from model output: a correction present starts at `reextract_rule`, no `regra_id` and no correction starts at `extract_rule`, anything else starts at `load_rule`. The routing function goes in `app/graph/core/engine.py`, like every other edge. Run `make graph` afterwards, because `tests/app/graph/test_diagram.py` fails while `docs/graph.md` is stale.

Thread housekeeping already covers the new thread shape. `ciclos_do_job` matches `job_id:%`, so the cleanup after `job-encerrado` also removes re-extraction threads. `_checkpoint_do_ciclo` splits at the first `:` for the legacy lookup, so a re-extraction thread never matches a legacy checkpoint. That is the intended outcome; keep it if you touch either function.

## Messages, broker and router

- **DTOs** (`app/contratos/mensagens.py`): `ParametrosConfirmados` gains optional `competencias` and `orcamento`; `EtapaAlterada` gains optional `regra_id` and `conflitos`; add `CorrecaoSubmetida` and `CorrecaoProposta`. `serializar` dumps with `exclude_unset=True`, so omit an absent field by not setting it. Never set it to `None`: the schemas reject explicit `null`, and `Producers._publicar` validates every payload against the schema before publishing.
- **Schemas**: the runtime validator reads `codegen/contracts/`, a copy made by `scripts/preparar_contratos.py`. Run `make contracts` after pulling a contract change, or validation fails with an unresolvable `$ref`.
- **Queues** (`app/mensageria/broker.py`): add `correcao-submetida` and `correcao-proposta` to `FILAS_SIMPLES`. The channel uses `on_return_raises=True` and producers publish with `mandatory=True`, so publishing to a queue nobody declared raises. Register consumers for `parametros-confirmados` and `correcao-submetida` in `iniciar_consumers`, and remove the comment there that explains why `parametros-confirmados` has none.
- **Router** (`app/mensageria/roteamento.py`): `GraphRouter.entregar` raises `NotImplementedError` for `ParametrosConfirmados` today. The new branches reuse `run_to_completion` with the right thread. Each needs its own initial state, next to `_estado_inicial`. The new `AgentState` fields go in `app/graph/core/state.py` under a comment naming the task that owns them, like the existing groups.
- **Closed jobs**: `_recusar_se_encerrado` only knows `RegraSubmetida` and `SimulacaoConcluida`. A `parametros-confirmados` or `correcao-submetida` that arrives after the api announced `job-encerrado` opens a new cycle, like `RegraSubmetida`, and must be refused the same way. Otherwise it recreates checkpoints after the cleanup and publishes to a job that no longer exists for the user.

## Which exception, which broker decision

`GraphRouter._processar` catches `FalhaDoJobError`, publishes `etapa-alterada` with the failure's `etapa` and `status = erro`, and re-raises. The `Consumer` then rejects without requeue. The same mechanism means two different things to the api:

| Situation | Raise | What happens |
| --- | --- | --- |
| Rule with conflicts | nothing: publish the pause and return | ack; the rule cycle is finished |
| `parametros-confirmados` without `competencias` | an exception the consumer maps to reject without requeue, logged with cause `contexto_ausente`, and **not** a `FalhaDoJobError` | reject; no `etapa-alterada` |
| Re-extraction cannot produce a proposal (unusable model output, text unavailable, rule missing) | a `FalhaDoJobError` subclass with `etapa = "extracao_parametros"` | the router publishes `erro` on `extracao_parametros`; the job is waiting for a correction, so the api reopens the round instead of failing the job |
| Database, broker or provider unavailable | a plain exception | nack with requeue |

Two consequences:

- A `FalhaDoJobError` raised for a message that should only be discarded moves a healthy job to `erro`. Reserve it for failures that really end the cycle.
- A re-extraction failure reported on any other `etapa` is invisible to the api: its handler only acts on `extracao_parametros` with a round in `em_reextracao`, so the round stays blocked forever. The contract also asks for `regra_id` on that event, equal to the `regra_origem_id` of the correction. The router has the message at hand, so add it there when the message is a `CorrecaoSubmetida`, rather than carrying it inside the exception.

## The pause (T-219)

It depends on domain validation being wired into the main graph (T-211). The node that blocks a rule with conflicts stops raising and publishes instead:

- Event order: `etapa-alterada` (`validacao_dominio`, `iniciada`), `no-concluido` (`validacao_dominio`), then `etapa-alterada` (`confirmacao`, `aguardando_correcao`, `regra_id`, `conflitos`) as the last thing the node does. No `geracao_codigo` event follows.
- `validacao_dominio.verificar` returns `Conflito(elementos, motivo)`. Map each one to `{"elementos": [...], "motivo": "..."}` in the order `verificar` produced them.
- `regra_id` is the state's `regra_id`, the version this cycle analysed.
- If the node runs again after a crash, it publishes the pause again. The api opens one round per `regra_id`, so the repeat is harmless.

## The re-extraction (T-220, T-221, T-224)

- **Inputs**: the analysed rule through `buscar_regra(sessoes, job_id, regra_origem_id)`, which validates it and refuses a rule from another job; the correction text from the `submissoes` row (`transcricao`, by `submissao_id`); and, for the history, `rodadas_correcao` followed through `rodada_anterior_id`. All three reads are `SELECT`-only.
- **Conflicts being answered**: recompute them with `verificar` on the analysed rule. They are system data, not user input.
- **Prompt**: keep fixed instructions apart from data, as `montar_prompt_geracao` in `app/prompts/geracao_codigo.py` does. The current and previous correction texts go in the compartment declared untrusted; the rule and the conflicts go in as system data. Bind no tools.
- **Output**: a closed schema of operations over the current rule's `ref`s. Downgrade unknown or invalid operations and log them; only a globally unusable output is a failure. Reassign `ref`s sequentially, then check the result against `RepresentacaoRegra` before publishing.
- **State**: the graph state holds references and control fields only. The correction text and the representation are not stored there: the checkpointer persists state, and this text must not get a second copy.
- **Order inside the node**:
  1. `etapa-alterada` (`extracao_parametros`, `iniciada`).
  2. The reads.
  3. The model call.
  4. `gravar_prompt_e_resposta`, with derived ids and `ON CONFLICT DO NOTHING`.
  5. `correcao-proposta`.
  6. `no-concluido`, with `evento_id` from `id_do_evento_de_trilha`.

  A retry after a crash between steps 5 and 6 publishes the proposal again, and the api treats the repeat as a duplicate.
- **No numbers from the model**: every value in an operation must be quoted from the user's text. Checking that grounding is deterministic code (T-224), never another model call.

## Tests

Follow the [`testing`](../testing/SKILL.md) skill. Drive behaviour through the real entry points:

- **Router**: deliver real DTOs to `GraphRouter.entregar`, in the style of `tests/app/test_roteamento.py`, with fake producers. Assert the exact sequence of published messages, and that each payload is valid against the contract.
- **Consumer**: in the style of `tests/app/test_mensageria.py`, assert ack, reject or requeue for each row of the table above, including `contexto_ausente` and the closed-job refusal.
- **Redelivery**: the same message twice yields one proposal or one pause, and no second prompt, response or trail row.
- **Contract examples**: add the examples codegen consumes (`parametros-confirmados.json`, `correcao-submetida.json`) to `tests/app/contratos/test_exemplos.py`.
- **Broker**: `make test-rabbitmq` covers queue declaration and consumers against a real RabbitMQ.

## Observability

Follow the [`logging`](../logging/SKILL.md) and [`metrics`](../metrics/SKILL.md) skills:

- **Counters**: each new consumer and node gets a counter with a closed `resultado` label, as its task specifies. Declare it in `app/core/metrics/global_metrics.py` and prove that the samples change in the registry served at `/metrics`.
- **Correlation**: `Consumer` sets `job_id_ctx`. Nodes set `no_ctx` and reset it in `finally`.
- **Log content**: logs carry counts, `elemento_ref`s and ids. They never carry a conflict `motivo`, correction text, prompt, model response or representation. A `FalhaDoJobError` message is never logged; the consumer logs only its `etapa`.
