---
name: observability
description: Convenções compartilhadas de logs, traces, métricas e correlação no Synapse. Use ao alterar o envelope JSON, atributos OpenTelemetry, nomes de métricas ou decidir o que deve ser emitido versus persistido.
---

# Observabilidade compartilhada

Use esta skill ao alterar o envelope de log, atributos de correlação, nomes de métricas ou decisões sobre o que deve ser emitido versus persistido.

## Roteamento

1. Leia o schema correspondente em `contracts/observability/`.
2. Leia apenas a seção de observabilidade da arquitetura, salvo se a mudança atravessar outra fronteira.
3. Leia a skill local de logging ou metrics do componente que será implementado.
4. Procure os consumidores do atributo antes de renomeá-lo.

## Logs

- O formato é JSON estruturado, um objeto por linha.
- Preserve os nomes canônicos: `service.name`, `job_id`, `no`, `competencia`, `trace_id` e `span_id`.
- `job_id` é obrigatório durante o processamento de um job; logs de inicialização podem não ter esse campo.
- `no` só é emitido pelo `codegen` quando o contexto pertence a um nó do LangGraph.
- Use os valores canônicos de `service.name`: `synapse-frontend`, `synapse-api`, `synapse-codegen` e `synapse-worker`.
- Trace e span seguem o formato W3C/OpenTelemetry quando tracing estiver disponível.
- Logs carregam contexto operacional e referências, nunca conteúdo de artefatos.
- Não registre prompts, respostas de modelos, código gerado, linhas de dataset, tokens, segredos ou dados pessoais desnecessários.

## Métricas

- Prefira métricas de saúde e desempenho que possam ser agregadas por serviço.
- Use labels de baixa cardinalidade e nunca use `job_id`, matrícula, prompt ou conteúdo livre como label.
- Preserve o nome e a unidade de uma métrica existente; uma renomeação exige compatibilidade ou decisão explícita.
- Não transforme uma métrica em log para evitar definir sua semântica.

## Validação

- Valide logs com o schema de observabilidade e teste pelo menos um log com e sem contexto de job quando aplicável.
- Confirme que a correlação funciona entre os serviços sem depender de tracing distribuído.
- Rode os testes e o gate do componente tocado.
- Rode `git diff --check` quando o schema for alterado.
