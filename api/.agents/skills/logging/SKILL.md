---
name: logging
description: Convenções de log desta API — obter um logger, escolher o nível, pôr dado variável em `extra` e não na mensagem, logar exceção, os campos de correlação (`job_id`, `user_id`, `trace_id`, `span_id`) e para onde a saída vai. Use ao escrever, revisar ou depurar qualquer chamada de log.
---

# Logging

## Obter um logger

```java
private static final Logger log = LoggerFactory.getLogger(JobService.class);
```

SLF4J direto, sem wrapper e sem registro. Passe a classe, não uma string: o nome do logger sai do nome qualificado dela.

## Níveis

| Método | Para |
| --- | --- |
| `log.debug()` | Detalhe útil no desenvolvimento; ruído em produção. |
| `log.info()` | Evento de ciclo de vida que vale guardar: job aceito, mensagem publicada. |
| `log.warn()` | Algo recuperável e inesperado: retentativa, fallback, caminho degradado. |
| `log.error()` | Uma operação falhou e não foi recuperada. |

O envelope carrega os *short names* do OpenTelemetry, que já são o vocabulário nativo do Logback — `TRACE`/`DEBUG`/`INFO`/`WARN`/`ERROR`/`FATAL`. Nada é traduzido deste lado.

`LOG_LEVEL` define o mínimo emitido. `ERROR` e acima sempre vão também para `logs/error.json`, independente dele.

## Dado variável vai em `extra`, não na mensagem

A mensagem é uma string **constante**. O que varia entra pela API fluente do SLF4J e cai sob `extra` no JSON, onde continua consultável no Loki.

```java
// Bom
log.atInfo().addKeyValue("exit_code", 0).addKeyValue("duration_ms", 1432).log("code execution finished");

// Ruim — os valores viram parte da string e ninguém consulta
log.info("code execution finished with exit code 0 in 1432ms");
```

## Exceções

```java
catch (SandboxTimeout ex) {
    log.atError().addKeyValue("timeout_s", 30).setCause(ex).log("sandbox execution timed out");
    throw ex;
}
```

A stack trace vai para o campo `exception`. Não a concatene na mensagem, e não logue-e-engula: se você logou um erro, ou relance ou trate deliberadamente.

## Correlação

Quatro campos são anexados sozinhos quando existem. **Nunca os passe manualmente em `addKeyValue`.**

| Campo | Vem de |
| --- | --- |
| `trace_id`, `span_id` | span ativo do OpenTelemetry, via MDC preenchido pelo Micrometer Tracing |
| `job_id`, `user_id` | `CorrelationContext`, definido por você no ponto de entrada |

```java
try (var scope = CorrelationContext.open(payload.jobId(), payload.userId())) {
    log.info("job accepted");   // job_id e user_id anexados automaticamente
}
```

O `try-with-resources` importa: o escopo restaura os valores anteriores ao fechar, para que uma thread que processa vários jobs em sequência não vaze o id de um para o próximo.

**Diferença que morde:** o MDC é `ThreadLocal`, e não um contexto de task. Ele **não** atravessa `@Async`, `CompletableFuture` nem pool próprio sem propagação explícita. Em requisição HTTP o `CorrelationFilter` limpa os campos no fim, porque o Tomcat reaproveita threads e um escopo não fechado contaminaria a requisição seguinte.

## Para onde vai

| Destino | Conteúdo |
| --- | --- |
| `logs/app.json` | Tudo a partir de `LOG_LEVEL`. Rotaciona em 10 MB, 5 arquivos. |
| `logs/error.json` | Só `ERROR` e acima. Mesma rotação. |
| stdout | Texto colorido em `development`; o mesmo JSON fora dele. |

A escrita é assíncrona, uma fila por destino. Na saturação o Logback descarta `TRACE`/`DEBUG`/`INFO` e preserva `WARN`/`ERROR`, em vez de bloquear a aplicação.

## O envelope é contrato entre serviços

Os campos de topo são compartilhados com os outros serviços do sistema: mudar, renomear ou remover um exige mudar os outros junto. A especificação está em `agents/.agents/skills/observability/SKILL.md`. Dado livre vai em `extra`, que é a parte sem contrato.

`module`, `function` e `line` custam *caller data* — uma captura de stack por linha de log, paga na thread de logging. É decisão consciente, e depende do `includeCallerData` no `logback-spring.xml`: sem ele os três campos somem sem nenhum erro.

## Referências

- O envelope: [`JsonLogFormatter`](../../../src/main/java/synapse/api/core/logging/JsonLogFormatter.java)
- Correlação: [`CorrelationContext`](../../../src/main/java/synapse/api/core/logging/CorrelationContext.java)
- Destinos e filas: [`logback-spring.xml`](../../../src/main/resources/logback-spring.xml)
