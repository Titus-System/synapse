---
name: correction-loop
description: How the frontend implements the correction chatbot - the `correcao-regra` feature, rebuilding the conversation from `GET /jobs/{id}/rodadas` rather than from SSE events, choosing between chatbot, confirmation and progress from the last round, the input rules, showing conflicts in the HR user's terms instead of internal references, navigation from the job list, and what the browser must never record. Use when implementing T-222 or T-226, or when the chatbot shows the wrong round after a reload or a reconnection.
---

# Correction chatbot

Read the root [`correction-loop`](../../../../.agents/skills/correction-loop/SKILL.md) skill first, in particular the round states. Then read `src/features/README.md` for the feature layout. This skill covers what is specific to the chatbot.

## Where it lives

- **Feature**: `src/features/correcao-regra/`, in the fixed feature shape. Its own route, for example `/jobs/:id/correcao`.
- **Types**: `Rodada`, `EstadoRodada`, the correction request and `SubmissaoCriada` go in the feature's `types.ts`. Promote them to `src/types/api.ts` only when a second feature needs them. `Conflito` and `EventoEtapa.conflitos` are already in `src/types/api.ts`, because the SSE client is shared.
- **Service**: `services/correcao.api.ts` calls `http` from `@/services/http`. It exposes one call to list the rounds (`GET /jobs/{id}/rodadas`) and one to send a correction (`POST /submissoes` with `finalidade: 'correcao'` and `tipo: 'texto'`), and holds no state and no error handling.
- **Stream**: use `abrirAcompanhamentoJob` from `@/services/jobEvents` for SSE. It already handles reconnection, `job_id` filtering and terminal states. Don't open a second stream client.
- **Entry points**: the chatbot is reached from places that today treat `aguardando_confirmacao_parametros` as a generic "Aguardando confirmação": `features/simulate` (`useJobSimulacao.ts`, `progressoSimulacao.ts`), `features/historico-jobs` (`HistoricoJobsView.vue`) and `src/components/TheProcessHeader.vue`. Features cannot import each other, so these places reach the chatbot by route only.

## The server owns the conversation

Rebuild the conversation from `GET /jobs/{id}/rodadas`, never from the SSE events the page happened to receive. The page must look the same after a reload, a reconnection or a return from the job list.

Re-read the rounds:

- on mount;
- on every `estado` event;
- on an `etapa` event with `status` `aguardando_correcao`, or with `erro` on `extracao_parametros`;
- on every `onReconciliar`, which fires after a reconnection.

The conflicts carried by the `etapa` event may be shown while the first read is in flight, but the read wins.

Decide the screen from the last round, which is always the open one when one exists, together with the job status from `GET /jobs/{id}` or the latest `estado` event:

| Last round | Job status | Show |
| --- | --- | --- |
| `pendente` | `aguardando_confirmacao_parametros` | input enabled; if the round before it is `reextracao_falhou`, say the last correction could not be applied and invite a new try |
| `em_reextracao` | `aguardando_confirmacao_parametros` | input blocked, and a message that the correction is being interpreted |
| none open | `gerando_regra` or later processing | navigate to progress, `/jobs/:id` |
| none at all | `aguardando_confirmacao_parametros` | not the chatbot: a reprocessed job awaiting the parameter confirmation |
| any | `cancelado`, `arquivado` or `erro` | the history read-only, without the input |

Leaving the page writes nothing. The only server write is sending a correction.

## Sending a correction

- Disable sending while the text is empty after trimming, longer than 4000 characters or already being sent, and ignore a second click. The limit in the interface is a convenience. The api decides, so on `400` show its message.
- On `201`, put the `rodada` from the response (already `em_reextracao`) in place of the open round. No extra read is needed.
- On `409 estado_invalido`, re-read the rounds. Another tab or a late event already moved the round or the job.
- Never persist the text or an unsent draft: no `localStorage`, no `sessionStorage`, no Pinia persistence.

## Show the user's concepts, not the system's

The chatbot shows conflicts, corrections and outcomes in the HR user's terms. It never shows a job state name, an id, an `elemento_ref` such as `nucleo.percentual` or `elem.2`, an internal version number, the pipeline stage that produced a version, or words like job, veredito or liberado. Code can use states and ids freely; the screen does not present them.

- **`motivo`**: show it as received; it is already text for the user.
- **`elementos`**: show them as labels, without inventing meaning. `nucleo.<campo>` becomes the field's label (Percentual, Loja, Vigência...). `elem.N` becomes the description of the matching item in the analysed rule, found in `GET /jobs/{id}` (`regras`) by `regra_analisada_id` and then by `ref`. This is a lookup of data the api already returned, not interpretation of the rule.
- **Round states**: shown as plain-language outcomes, for example "a correção foi aplicada" or "não foi possível aplicar esta correção".
- **Resulting version**: shown as the outcome "a regra foi atualizada", without its number.

T-222 says the screen shows `elementos` as received, and T-226 shows the version number of the resulting rule. Both conflict with this rule. Follow this rule, and record the divergence in the task so it is settled against the Figma mockups (T-227, T-228) with the PO.

## No business logic

The screen never validates the rule, never reinterprets a conflict and never infers a round or job state from the conflicts. What it displays comes from the api; what it decides is only which screen to show, from the table above.

## Tests

- **Service and store**: test them with mocked responses that are valid against `contracts/http/openapi.yaml`. Use the `openapi.yaml` examples for `GET /jobs/{id}/rodadas` and `POST /submissoes` as fixtures, so the UI can be built before the api exists.
- **Screen decision**: cover every row of the decision table.
- **Reconnection and duplicates**: a reconnection re-reads the rounds without duplicating messages, and a repeated `etapa` event does not add another one.
- **Sending**: cover the double-click guard and the `400` and `409` paths.
- **Type alignment**: a test in the style of `src/types/api.contract.spec.ts` deserializes the contract examples into the new types.

## Observability

Follow the frontend `AGENTS.md`:

- **Operation names**: record failures with bounded names (`ler_rodadas`, `enviar_correcao`), the known error code and the `job_id`, and clear the `job_id` when navigating to another job.
- **Excluded content**: never include the correction text, a conflict `motivo`, a response body or a raw exception.
- **Transport**: the only transport today is the structured console log in `src/observability/`. It does not export anything, so report browser emission as verified and collection as not verified.
