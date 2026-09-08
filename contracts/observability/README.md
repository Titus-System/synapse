# Contrato de Observabilidade

Todos os serviços emitem logs estruturados como JSON, com um objeto por linha. O envelope comum está em [log.schema.json](log.schema.json).

## Campos

Campos obrigatórios em todo log:

- `timestamp`: data/hora UTC em ISO 8601.
- `level`: nível no vocabulário OpenTelemetry (`TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL`).
- `message`: mensagem legível, sem conteúdo de artefato.
- `service.name`: um dos valores canônicos `synapse-frontend`, `synapse-api`, `synapse-codegen` ou `synapse-worker`.

Durante o processamento de um job, `job_id` é obrigatório em toda linha. `competencia` é emitido quando o log trata de uma competência específica. `no` é reservado ao `codegen` para identificar o nó do LangGraph.

`trace_id` e `span_id`, quando houver span ativo, seguem o formato W3C/OpenTelemetry: 32 e 16 caracteres hexadecimais minúsculos, respectivamente. A correlação por `job_id` continua obrigatória mesmo sem tracing distribuído.

Os campos `service.name`, `service.version` e `host.name` usam os nomes das convenções OpenTelemetry. Os campos de correlação de negócio usam `job_id`, `no` e `competencia` exatamente assim nos quatro serviços.

## Conteúdo proibido

Logs nunca carregam prompt, resposta de modelo, código gerado, linhas de bases, dataset ou outro artefato. O campo `extra` aceita somente contexto operacional escalar, como duração, código de saída ou contagem. Artefatos são persistidos nas tabelas próprias e referenciados por ID quando necessário.

## Compatibilidade

Os arquivos existentes podem conter campos históricos como `service`, `version` e `host` durante a transição dos bootstraps. Novos loggers devem emitir os nomes canônicos deste contrato; a implementação da migração pertence às tarefas T-008 a T-011.