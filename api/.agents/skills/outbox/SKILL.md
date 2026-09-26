---
name: outbox
description: Como publicar um evento no RabbitMQ sem perder o job se a api cair entre gravar e publicar — Outbox.registrar dentro da transação de negócio, o poller PublicadorOutbox, o intervalo como latência aceita, entrega pelo menos uma vez e por que SKIP LOCKED basta contra concorrência. Use ao publicar um evento novo pela api, ou ao mexer no outbox em si.
---

# Outbox

Se a api gravasse o job e só depois publicasse no RabbitMQ, uma queda entre os dois passos
deixaria o job no banco sem que ninguém o processasse. O outbox fecha essa janela: a linha
do evento entra em `outbox_events` **na mesma transação** que grava o job ou o estado que a
originou, e um poller `@Scheduled` publica o que está pendente e marca como enviado.

## Registrar um evento

```java
@Transactional
JobCriadoDto criar(CriarJobRequisicao requisicao) {
    UUID jobId = inserirJob(...);
    outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, new RegraSubmetidaDto(...));
    return ...;
}
```

`Outbox.registrar` é `@Transactional(propagation = MANDATORY)`: chamar fora de uma
transação lança `IllegalTransactionStateException` em vez de gravar o evento sozinho, o que
permitiria confirmar um sem o outro.

**Nunca** publique num listener `AFTER_COMMIT`, num `@Async` sem propagação de transação,
ou em qualquer caminho que possa confirmar job e evento em momentos diferentes — é
exatamente o que o outbox existe para evitar (`AGENTS.md`, seção Segurança).

`EventoOutbox` é o vocabulário fechado dos eventos que a api publica; um evento novo exige
um valor novo ali, ligado à fila declarada em `RabbitTopologyConfig`.

## O payload

O DTO do evento mora na fatia que o publica (`RegraSubmetidaDto` em `synapse.api.job`,
package-private), nunca em `core` — é regra de negócio de quem grava o job, não
infraestrutura. Componentes em snake_case, sem naming strategy: `Outbox.registrar`
serializa com um `JsonMapper` puro, então o nome do componente é o nome no fio.

**Sempre um DTO apartado do de resposta HTTP**, mesmo quando os campos coincidem hoje. São
dois contratos distintos — fila de saída × HTTP de entrada/saída — e é a separação que
impede um campo novo de um vazar sozinho para o outro (mesma razão de `EventoEtapaDto`
existir apartado de `EtapaAlteradaDto`).

Campo opcional do schema do evento (`submissao_id`, `regra_id`, conforme a origem) é
`@Nullable` no DTO e leva `@JsonInclude(Include.NON_NULL)` na classe: o schema recusa
`null` explícito (`type: "string"` não aceita `null`), então ausência tem que virar
ausência no JSON, nunca `"campo": null`.

A conformidade contra `contracts/events/<evento>.schema.json` — inclusive os `if/then`
condicionais — é verificada em teste, com `com.networknt:json-schema-validator`
(`ContratoDeEvento`, em `synapse.api.job`), nunca por asserção campo a campo: é a única
forma de pegar uma condição do schema que uma lista de campos não capturaria.

## O poller

`PublicadorOutbox.publicarPendentes()`, agendado por `OutboxConfig` a cada
`app.outbox.poll-interval` (default 1 s, `OUTBOX_POLL_INTERVAL`). **É a latência aceita
pela decisão**: entre o commit que grava o evento e sua publicação passa, na pior hipótese,
um intervalo inteiro. `app.outbox.enabled` (default `true`, `OUTBOX_ENABLED`) desliga o
agendamento sem afetar `registrar`; os eventos continuam sendo gravados e ficam pendentes
até o poller voltar.

O agendamento é `fixedDelay`, não `fixedRate`: o intervalo conta a partir do **fim** de um
ciclo, para que um ciclo lento nunca se sobreponha ao seguinte.

## Um ciclo

1. Lê até 50 eventos pendentes com `SELECT ... FOR UPDATE SKIP LOCKED`, ordenados por
   `criado_em, id`.
2. Publica cada um, na ordem, com confirmação do broker (`publisher-confirm-type:
   correlated`, `publisher-returns: true`, `template.mandatory: true` — ver
   `application.yaml`). Sucesso exige `ack` **e** nenhuma devolução: uma mensagem sem fila
   de destino volta ao produtor em vez de sumir em silêncio.
3. **A primeira falha encerra o ciclo.** Um evento que falha grava só a tentativa e
   permanece pendente; eventos seguintes do mesmo ciclo não são tentados, para que um
   evento posterior nunca publique antes de um anterior do mesmo job.
4. Sucesso marca `publicado_em` com uma condição `WHERE publicado_em IS NULL`, que é o que
   torna a marcação idempotente mesmo se dois ciclos disputassem a mesma linha.

**`SKIP LOCKED` já resolve a concorrência entre ciclos.** A instância é única (ver
Restrições), mas um ciclo lento e o disparo seguinte do `@Scheduled`, ou uma retentativa
manual, podem coexistir; a linha travada pelo primeiro é simplesmente pulada pelo segundo,
nunca publicada duas vezes.

## Entrega pelo menos uma vez

Se a api cair entre o `ack` do broker e o commit do `UPDATE ... publicado_em`, o evento sai
de novo no ciclo seguinte. Por isso toda mensagem carrega `message_id = outbox_events.id`,
estável entre tentativas — é o que permite ao consumidor deduplicar. `correlation_id` é o
`job_id`, e `type` é o nome do evento (igual ao nome da fila, DEC-089).

## O que nunca vai para o log

O payload do evento. Uma falha de publicação loga `evento_id`, `tipo_mensagem` e
`tentativas`, com `job_id` vindo do `CorrelationContext` — nunca o corpo da mensagem
(skill `logging`).

## Restrições

- **Instância única**, como o heartbeat SSE: não há coordenação entre instâncias da api
  nesta fase. Com mais de uma, cada uma agendaria o próprio poller e `SKIP LOCKED`
  continuaria correto — nenhuma publicaria a linha que a outra já travou — mas não é o
  cenário testado nem o que a arquitetura assume hoje.
- `spring.task.scheduling.pool.size: 2`: o scheduler padrão tem uma thread só, e o
  heartbeat SSE bloqueia enviando a um cliente lento, o que atrasaria o outbox se
  dividissem a mesma thread.

## Referências

- Componente: [`Outbox`](../../../src/main/java/synapse/api/core/outbox/Outbox.java),
  [`PublicadorOutbox`](../../../src/main/java/synapse/api/core/outbox/PublicadorOutbox.java),
  [`OutboxConfig`](../../../src/main/java/synapse/api/core/outbox/OutboxConfig.java)
- Configuração: [`configuration`](../configuration/SKILL.md) (`app.outbox.*`)
- Tabela: `014-cria-outbox-events.sql`, skill [`migrations`](../migrations/SKILL.md)
- Decisão: `docs/ARCHITECTURE.md` §3.2, `docs/adrs/ADR-001.md`
