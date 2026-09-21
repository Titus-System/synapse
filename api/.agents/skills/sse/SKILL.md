---
name: sse
description: Como emitir progresso para o stream SSE do job - o mapa job_id → emissores em EmissoresSse, EventoSse.ultimo para fechar o stream, o id sequencial, o heartbeat, o descarte silencioso sem cliente conectado e a restrição de instância única. Use ao consumir uma fila do RabbitMQ que precisa repassar algo ao navegador, ou ao mexer no stream em si.
---

# SSE

`GET /jobs/{id}/events` (T-043) entrega o **transporte**: quem decide o que emitir é a
fatia de negócio, hoje `synapse.api.job`.

## Emitir um evento

```java
emissores.emitir(jobId, EventoSse.de("etapa", new EventoEtapaDto(jobId, "geracao_codigo", "iniciada")));
```

- `EventoSse.de(nome, dados)` para um evento comum; `EventoSse.ultimo(nome, dados)` quando,
  depois dele, o stream daquele job deve fechar - hoje só o evento `estado` com status
  terminal usa isto.
- **Emita depois do commit** da transação que produziu o fato. Emitir antes arrisca o
  cliente receber um evento cujo fato ainda não está gravado; um cliente que se inscreve
  entre o commit e a emissão só vê o mesmo estado duas vezes (na fotografia e no evento),
  o que é inofensivo.
- **Job sem cliente conectado é descartado sem erro.** O progresso é efêmero por
  natureza - não existe fila nem replay. Quem chega tarde consulta `GET /jobs/{id}`.
- `EmissoresSse` não conhece `JobStatus` nem nome de evento de negócio: é núcleo de
  infraestrutura (`synapse.api.core.sse`), reaproveitado por toda fatia que precise
  falar com o navegador.

## Ordem entre eventos de um mesmo fato

Quando um único fato produz mais de um evento - a simulação concluída anuncia `resultado`
e, na sequência, `estado` (`SimulacaoConcluidaConsumidor`, T-045) -, **emita nessa ordem, no
mesmo método, antes de qualquer um deles poder fechar o stream**. Um evento `estado`
terminal (`JobStatus.terminal()`) faz `emitir` remover e completar todo emissor daquele job
(ver `EmissoresSse.emitir`); emitir `estado` primeiro descartaria o `resultado` que viria
depois - o cliente já teria se desconectado. Não há reordenação nem buffer no lado do
transporte: quem produz os eventos é quem garante a ordem.

## `id` sequencial e heartbeat

Cada `emitir` e cada fotografia de `inscrever` recebem um `id` de uma sequência única do
processo, crescente, nunca reiniciada enquanto a `api` roda. Serve para o cliente
deduplicar; não sobrevive a um reinício, e a reconexão não tenta retomar a partir dele -
ela recebe a fotografia de novo.

Um heartbeat (comentário SSE, sem `event:` nem `data:`) sai em `app.sse.heartbeat`
(default 15 s) para todo emissor conectado, e serve dois propósitos: manter a conexão
viva através de proxy, e permitir à `api` detectar o cliente que saiu (o envio falha e o
emissor é removido).

## Restrições

- **Instância única.** O mapa `job_id → emissores` vive em memória do processo. Com mais
  de uma instância da `api`, um cliente inscrito numa não veria o evento emitido pela
  outra - fora do escopo até existir coordenação entre instâncias.
- **Emitir bloqueia até o envio completar**, um emissor de cada vez. Um cliente lento
  atrasa quem chama `emitir` (hoje, o consumidor RabbitMQ de T-044/T-045). Aceitável para
  o volume do MVP; se isso doer, a saída é emitir numa thread separada da que consome a
  fila, não sem essa fila.
- **Sem autenticação nesta rota ainda** (ver `AGENTS.md` da raiz, decisão de escopo):
  `GET /jobs/{id}/events` não confere posse. Um filtro futuro (T-091) cobre isto; até lá
  não implemente checagem aqui.

## Referências

- Transporte: [`EmissoresSse`](../../../src/main/java/synapse/api/core/sse/EmissoresSse.java),
  [`EventoSse`](../../../src/main/java/synapse/api/core/sse/EventoSse.java)
- Contrato do stream: `contracts/http/openapi.yaml`, operação `acompanharJob`
- Configuração: [`configuration`](../configuration/SKILL.md) (`app.sse.*`)
