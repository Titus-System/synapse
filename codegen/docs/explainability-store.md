# Armazenamento de artefatos e explicabilidade

O registro auditável usa o modelo de domínio do Synapse, definido em [modelo-dados.dbml](../../docs/database/modelo-dados.dbml) e explicado em [modelo-dados.md](../../docs/database/modelo-dados.md). A proposta anterior de `agent_run` e `agent_step` não foi implementada e não é o modelo vigente. Migrations de domínio pertencem à API, via Liquibase.

## Estrutura existente

- `prompts`: texto enviado e metadados do modelo e seus parâmetros.
- `respostas_modelo`: resposta original e consumo de tokens, quando informado pelo provedor.
- `codigos_gerados`: código vinculado ao prompt e à versão exata da regra.
- `regras`: versões imutáveis, relacionadas ao job e à versão de origem.
- `simulacoes` e `resultados_simulacao`: vínculo entre regra, código executado e resultado persistido pelo worker.
- `trilhas_auditoria`: registros persistidos pela API a partir de `no-concluido`, com referências aos artefatos e identidade do evento.

O codegen grava os artefatos que produz. A API é dona do estado, das transições e da trilha; os serviços se coordenam exclusivamente por RabbitMQ. Eventos transportam referências; prompts, respostas e código permanecem no PostgreSQL.

## Idempotência e retomada

O `evento_id` da trilha é UUIDv5 derivado de job, nó e referência do artefato. Republicar o mesmo evento lógico conserva sua identidade.

O checkpoint usa `job_id:regra_id` e pertence à infraestrutura de retomada do codegen. Não substitui o armazenamento auditável. Ele é removido depois do encerramento do job, e o registro `jobs_grafo_encerrados` preserva a deduplicação dos ciclos concluídos (DEC-095).

## Telemetria e explicação

Logs, métricas e traces apoiam operação, mas não substituem o registro de negócio. Prompts, respostas, código e linhas de dados não devem aparecer nos logs ou rótulos de métricas. `job_id` relaciona o contexto operacional ao domínio; identificadores de trace não são chaves de negócio.

O grafo ativo ainda não contém a explicação completa da US05. A narrativa deve citar números já apurados e ser conferida antes de exibição. Falha de explicação é distinta de falha de geração, cobertura ou asserção: não deve transformar uma apuração inválida em resultado utilizável.

## Evolução da Sprint 2

Rodadas do chatbot serão armazenadas em tabela própria, com conflitos em `jsonb`, referências às submissões e às versões e encadeamento entre rodadas. Essa estrutura ainda não existe no banco.

Rastreabilidade por colaborador, loja e competência requer a evolução dos resultados. As quebras atuais são diferenças agregadas; a granularidade dos detalhes e dos dataframes precisa ser fechada conforme o pedido do cliente.

Ver [Fluxo e decisões da Sprint 2](../../docs/FLUXO-SPRINT-2.md). Esse planejamento não cria novas tabelas apenas por documentá-las.
