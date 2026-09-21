---
name: consumidores
description: Como consumir uma fila do RabbitMQ nesta api - o RabbitListenerConfig com o MessageConverter de Jackson, por que o consumidor nunca lança, quando deduplicar por evento_id e quando não, e por que um payload malformado é rejeitado sem requeue. Use ao escrever um `@RabbitListener` novo, ou ao investigar por que uma mensagem some ou volta em loop.
---

# Consumidores

`EtapaAlteradaConsumidor` (T-044) é o primeiro `@RabbitListener` do repositório e fixa o
padrão para os que virão (`simulacao-concluida`, T-045; `no-concluido`, T-046).

## O `MessageConverter`

`RabbitListenerContainerFactory` do Boot nasce serializando com Java puro. `RabbitListenerConfig`
troca o converter por `JacksonJsonMessageConverter` - o mesmo Jackson 3 que `Outbox` já publica
e `ExemplosDeContratoTests` já lê -, passando primeiro pelo `SimpleRabbitListenerContainerFactoryConfigurer`
do Boot para preservar `spring.rabbitmq.listener.simple.*` (concorrência, prefetch, modo de
ack). Sem isto, todo consumidor novo precisaria repetir a troca.

`FAIL_ON_UNKNOWN_PROPERTIES` vem **desligado** por default no Jackson 3: um campo novo
publicado por `codegen` ou `worker` não quebra o consumidor - é o que a evolução aditiva dos
eventos exige.

## O consumidor nunca lança

Uma exceção dentro de um método `@RabbitListener` derruba a mensagem de volta para a fila
(`default-requeue-rejected: true`, que segue ligado - ver adiante) e ela volta para o mesmo
consumidor, na mesma forma, para sempre. Toda entrada que a validação de negócio rejeitaria -
campo obrigatório ausente, vocabulário fechado violado - é tratada como descarte:

```java
if (etapa == null || !StringUtils.hasText(status)) {
    log.atWarn().addKeyValue("etapa", evento.etapa()).log("evento descartado");
    return;
}
```

Sempre com `log.warn`, nunca silencioso, e sempre depois de abrir o escopo de correlação
(`CorrelationContext.abrir`) para que `job_id` apareça no log.

## Payload malformado é outro caminho, e já é coberto

JSON que não corresponde a nenhum record é `MessageConversionException`, e o
`ConditionalRejectingErrorHandler` do Spring AMQP trata isso como **fatal**: a mensagem é
rejeitada sem requeue, não some silenciosamente nem volta em loop. Não é preciso capturar
nada para este caso - é o comportamento default do container.

## Deduplicação: exceção, não regra

`api/AGENTS.md` exige consumidor idempotente porque uma redelivery não pode duplicar efeito
financeiro nem criar um segundo job. `EtapaAlteradaConsumidor` é a exceção deliberada: o
evento é puramente informativo (repassa progresso ao SSE, nunca escreve estado), e
`etapa-alterada` nem carrega `message_id` - o codegen só o define para `no-concluido`
(`producers.py`). Reemitir a mesma etapa duas vezes ao mesmo cliente é inofensivo.

Um consumidor que **escreve** estado precisa deduplicar antes de gravar, de uma de duas
formas:

- **Por `evento_id`**, quando a mensagem carrega um - `no-concluido` prevê isso com um
  índice único em `trilhas_auditoria.evento_id`.
- **Pela própria máquina de estados**, quando não há `evento_id` - `simulacao-concluida`
  (`SimulacaoConcluidaConsumidor`, T-045) é o caso: uma redelivery ou um evento fora de
  ordem encontram o job já fora do estado de origem esperado, `transicionar` lança
  `TransicaoDeStatusInvalidaException` e a transação inteira desfaz. Isso só deduplica
  porque o job nunca tem aresta de volta a um estado por onde já passou - não é um recurso
  geral, é uma propriedade do grafo (`JobStatus`) que só se aplica quando o evento em
  questão é o único a produzir aquela transição.

Nos dois casos, capture só a exceção de negócio (`TransicaoDeStatusInvalidaException`, uma
constraint única violada). Uma falha de banco não é isso - ela deve propagar e virar
redelivery de verdade, que é a garantia que a seção seguinte documenta.

## Por que `default-requeue-rejected` continua `true`

É o que sustenta a garantia de `no-concluido` na arquitetura (§3.2): "banco indisponível
significa redelivery, não registro perdido". Desligar essa opção global para proteger um
consumidor protegeria errado todos os outros. A proteção certa é local: o próprio
consumidor nunca lançar (acima).

## Referências

- Configuração do container: [`RabbitListenerConfig`](../../../src/main/java/synapse/api/core/messaging/RabbitListenerConfig.java)
- Primeiro consumidor: [`EtapaAlteradaConsumidor`](../../../src/main/java/synapse/api/job/EtapaAlteradaConsumidor.java)
- Publicação: [`outbox`](../outbox/SKILL.md)
- Catálogo de mensagens: `docs/ARCHITECTURE.md` §6.3
