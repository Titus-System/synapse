# Validação da T-275

A API mantém o job em processamento quando uma alternativa não cabe. Uma proposta seguinte cria outra versão, registra `tentativa` e republica `regra-submetida` com orçamento e meta do job na mesma transação. Só a alternativa viável produz o resultado para decisão do usuário; `sem_alternativa` encerra a iteração sem alternativa. As versões e simulações intermediárias permanecem na auditoria.

A implementação retomada também foi corrigida para preservar a causa de uma falha na decisão ou sugestão: esse evento termina em `erro`, em vez de ser apresentado como esgotamento das tentativas. Descartes de propostas inválidas preservam a correlação por `job_id`.

## Correções após revisão

A confirmação de parâmetros recusa jobs em `gerando_regra` ou `simulando`, sob a mesma trava de banco usada pela transição. A volta de `simulando` para `gerando_regra` continua disponível para a próxima proposta automática. A regressão cobre HTTP 409 e a ausência de novas versões, transições e eventos de outbox.

O consumidor verifica se o resultado é intermediário antes de emitir qualquer estado SSE. Isso impede um anúncio atrasado de `simulando` depois do fim da iteração. Um teste intercala o consumo real de `sem_alternativa` entre o commit do resultado e a continuação do primeiro consumidor; outro confere a ausência de SSE, os logs e a métrica tanto a partir de `gerando_regra` quanto de `simulando`.

A validação completa das correções passou em `develop`, no commit de integração `f17079e` (PR #325), após recompilação limpa.

## Cobertura

- PostgreSQL: propostas e resultados nas duas ordens, deduplicação de propostas, resultados antigos e `sem_alternativa`, tentativa associada à versão, encadeamento por `regra_origem_id` e rollback conjunto de versão, estado e outbox.
- RabbitMQ e aplicação completa: três alternativas inviáveis sem resultado intermediário no SSE; encerramento antes e depois da notificação do último resultado; sucesso nas tentativas 1, 2 e 3; erro de execução e asserção violada; preservação da causa e idempotência da falha na sugestão.
- Contratos: propostas e eventos publicados pelo teste, cada `regra-submetida` recebido do outbox e os eventos SSE validados contra os schemas existentes. Nenhum contrato compartilhado foi alterado.
- Observabilidade: logs serializados validados contra `contracts/observability/log.schema.json`, com correlação e sem representação ou valores financeiros; contadores conferidos no `MeterRegistry` e no scrape HTTP de `/metrics`, incluindo sucesso, descarte, resultado intermediário, fim sem alternativa e falha.
- Migration 025: coluna opcional `regras.tentativa`, compatibilidade de registros anteriores e inserts sem o campo, faixa válida e rollback.

## Comandos e resultados

Executados em `api/`, com Java 21 e Docker disponível:

- `make test`: execução inicial interrompida para validar os ajustes antes do gate completo; não é contabilizada como aprovação do gate.
- `make fmt`: formatação aplicada.
- `JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ./mvnw -Dtest=IteracaoDaTaxaNovaFimAFimTests,SugestaoAdaptacaoPersistenciaTests,SugestaoAdaptacaoConsumidorTests test`: **64 testes, sem falhas nem skips**. O cenário adicional de falha na sugestão foi incluído depois desta execução e passou no gate completo.
- `make check`: **BUILD SUCCESS — 1073 testes, 0 falhas, 0 erros e 3 skips**, incluindo os 8 cenários de `IteracaoDaTaxaNovaFimAFimTests`. Formato, Error Prone e NullAway aprovados.
- `make check` após as correções: a primeira execução terminou com 13 erros `NoClassDefFoundError` em auxiliares de testes de logging e transcrição.
- `make clean && make check`: **BUILD SUCCESS — 1077 testes, 0 falhas, 0 erros e 3 skips**, incluindo os 9 cenários de `IteracaoDaTaxaNovaFimAFimTests` e as regressões das duas correções. A recompilação limpa eliminou os erros de classes ausentes sem mudanças nesses testes. Formato, Error Prone e NullAway aprovados.
- `git diff --check`: sem erros na revisão final.

Os três skips foram `TranscricaoRealTests` (variável `TRANSCRIPTION_REAL_TEST` ausente), `SubmissaoDeRegraFimAFimTests` (condição `ambienteCompleto` falsa) e `JobComErroFimAFimTests.falhaDeInfraestruturaNaExecucaoEncerraOJobDepoisDeGerarOCodigo` (condição `ambienteDeExecucao` falsa). Nenhum cenário da T-275 foi ignorado.

## Limites e publicação

O teste da T-275 usa PostgreSQL e RabbitMQ reais em Testcontainers. Ele ocupa o lugar do codegen e do worker para persistir os artefatos e publicar os eventos, permitindo controlar a ordem das filas; não comprova sozinho a integração com os processos reais desses dois serviços. Não foi feita validação visual do frontend, que pertence à T-276, nem conferida a coleta externa por Prometheus/Grafana.

Na retomada da validação, a implementação e as duas correções já estavam integradas em `develop` pelo PR #325 (`f17079e`). O gate local acima foi executado nesse estado; o resultado da CI não foi consultado nesta retomada. Este relatório foi atualizado localmente, sem criar commit ou push.
