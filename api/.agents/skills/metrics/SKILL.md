---
name: metrics
description: Convenções de métricas Prometheus nesta API — o que o Actuator já publica e não deve ser redeclarado, como declarar métrica de domínio em AppMetrics, a regra de cardinalidade das tags, nomenclatura e o endpoint de scrape. Use ao acrescentar uma métrica, ao adicionar uma tag, ou ao decidir se algo deve ser métrica.
---

# Métricas

Métrica responde pergunta agregada: qual a taxa de erro, qual o p95 de latência. Detalhe por evento pertence ao log.

## O que já existe e não se redeclara

O Micrometer publica sozinho, sem nenhuma linha de código nossa:

| Família | Cobre |
| --- | --- |
| `http_server_requests_seconds` | contagem e latência por `method`, `uri`, `status`, `outcome`, `exception` |
| `jvm_*` | memória, threads, GC, classes |
| `process_*`, `system_*` | CPU, uptime, descritores de arquivo |

Declarar um contador próprio de requisições ou de uso de memória cria **duas fontes divergentes para a mesma pergunta**. A `uri` já vem no formato de rota (`/jobs/{id}`), não a URL concreta.

## Declarar métrica de domínio

Em `AppMetrics`, como campo ou método — nunca dentro do fluxo de negócio:

```java
public Counter sandboxTimeouts(String image) {
    return Counter.builder("sandbox.timeouts")
        .description("Sandbox executions killed for exceeding the time limit")
        .tag("image", image)
        .register(this.registry);
}
```

`Counter.builder(...).register(...)` é idempotente por nome e tags: chamar duas vezes devolve o mesmo colector.

Para job, prefira `recordJob`, que contabiliza execução, duração e falha de uma vez — inclusive quando o bloco lança.

## Escolher o tipo

| Tipo | Para | Nunca |
| --- | --- | --- |
| `Counter` | Valores que só sobem: requisições servidas, jobs falhados. | Valores que podem diminuir. |
| `Gauge` | Valores que sobem e descem: profundidade de fila, workers ativos. | Coisas das quais você quer taxa. |
| `Timer` | Distribuições das quais você quer percentil: durações. | Valor isolado de baixo volume. |

Para contador, peça a taxa ao Prometheus (`rate(job_runs_total[5m])`) em vez de calculá-la você.

## Cardinalidade — a regra que importa

**Nunca use valor ilimitado como tag.** Cada combinação distinta vira uma série temporal nova, e cardinalidade alta degrada e derruba o Prometheus.

Banidos como tag: `job_id`, `user_id`, `trace_id`, `span_id`, e-mail, URL crua, timestamp, mensagem de erro.

```java
metrics.jobRuns(jobId).increment();          // NUNCA — ilimitado
metrics.jobRuns("generate_code").increment(); // conjunto limitado
```

Esse dado não se perde: ele pertence à **linha de log**, que é construída para alta cardinalidade. É a divisão de trabalho entre os dois sinais — a métrica diz *que* a taxa de erro subiu, o log diz *quais* jobs falharam e por quê.

## Nomenclatura

Nomeie em `dot.case`; o registro do Prometheus converte. `job.runs` vira `job_runs_total`, `job.duration` vira `job_duration_seconds`.

- Prefixe pelo subsistema: `sandbox.`, `job.`.
- A unidade vai no nome, em unidade base: segundos, não milissegundos.
- Descreva o que é medido, não como é guardado: `job.duration`, não `job.duration.histogram`.

## Exposição

`GET /metrics`, e não `/actuator/prometheus`. A base path do Actuator foi movida para a raiz e o endpoint `prometheus` foi remapeado para `metrics`, para o scrape ficar igual ao dos outros serviços.

**Não exponha o endpoint `metrics` nativo do Actuator** em `management.endpoints.web.exposure.include`: ele colidiria com esse remapeamento e quebra a subida.

Métrica nova não exige trabalho de endpoint nenhum.

## Referências

- Métricas de domínio: [`AppMetrics`](../../../src/main/java/synapse/api/core/metrics/AppMetrics.java)
- Caminhos e exposição: [`application.yaml`](../../../src/main/resources/application.yaml)
- Por que um valor vai no log em vez de virar tag: [`logging`](../logging/SKILL.md)
