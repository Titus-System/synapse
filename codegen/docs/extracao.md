# Extração de regra — T-203

O motor em `app/extracao/motor.py` recebe texto, competências e o modelo configurado, e retorna a representação da T-004, os diagnósticos de rebaixamento e a chamada original para auditoria. O repositório em `app/repositorio/extracoes.py` persiste esse resultado no PostgreSQL. Não há publicação nem ligação ao grafo nesta entrega; essas entradas pertencem à T-204 e o consumo pela API pertence à T-202.

## Modelo e representação

`get_model("extraction")` usa o mesmo provedor e modelo já configurados para geração: Gemini `gemini-3.1-flash-lite`, temperatura zero, limite de 8192 tokens, timeout de 60 segundos e duas tentativas de retry do cliente. O motor recebe a instância pelo argumento `modelo` para permitir testes determinísticos, sem outra configuração de LLM. Os metadados vêm de `get_model_metadata("extraction")`.

A chamada pede JSON nativo com `response_json_schema`, sem ferramentas. O rascunho fechado contém `nucleo` e `elementos`; cada elemento traz `construto_pretendido`, `descricao` e `trecho`. O modelo não fornece referências: o motor atribui `elem.1`, `elem.2`, etc. na ordem dos elementos, solicitada no prompt como a ordem do texto.

O núcleo aceita somente vigência, loja, marca, cargo e percentual. Campos não mencionados permanecem ausentes. Códigos são strings; números são lidos como `Decimal` e permanecem números JSON, inclusive no banco. Percentual negativo e intervalo invertido não são corrigidos nesta etapa. Texto sem regra pode resultar em núcleo vazio e nenhuma especificação.

O registro explícito de construtos tipados começa vazio. Não há importação de módulos a partir da resposta da LLM. Para habilitar um construto, seu módulo deve fornecer schema, instruções e conversor por `Construto`, registrado em `CONSTRUTOS_HABILITADOS`; o resultado ainda precisa passar pelo contrato compartilhado.

Cada elemento recuperável vira `generico` quando o construto não está habilitado ou faltam campos válidos. A ausência/invalidez tem prioridade no diagnóstico (`campo_obrigatorio_ausente`); os demais rebaixamentos usam `construto_nao_habilitado`. Se a descrição não é utilizável, um trecho não vazio encontrado literalmente na entrada preserva o elemento. Sem descrição nem trecho recuperável, a extração inteira falha. Referências e diagnósticos têm correspondência de um para um para os genéricos.

JSON inválido, chaves duplicadas, núcleo fora do schema, elemento irrecuperável ou resposta sem `finish_reason=STOP` são falha permanente em `extracao_parametros`. A exceção pública não retém o conteúdo bruto nem a exceção do parser. Falhas do provedor seguem para o chamador, responsável pela política de retry. A resposta original e o prompt só são persistidos junto de uma extração válida; a camada que tratar falhas da chamada deve respeitar a mesma proibição de conteúdo em telemetria.

A T-203 não comprova que a LLM preservou todos os números ou resolveu corretamente vocabulário e contexto temporal. A conferência determinística desses valores pertence à T-210. Construtos genéricos conservam a intenção textual para as etapas seguintes; não significam autorização para simulação parcial.

## Persistência e entrega por referência

A fonte canônica é [`modelo-dados.dbml`](../../docs/database/modelo-dados.dbml); a API aplica `020-cria-extracoes-regras.sql`.

| Tabela | Conteúdo |
| --- | --- |
| `prompts` | Texto exato enviado e metadados do modelo; nó `extracao_parametros` |
| `respostas_modelo` | Resposta textual original e consumo de tokens quando informado |
| `extracoes_regras` | `job_id`, `submissao_id`, `resposta_id`, representação completa e diagnósticos |

A LLM é chamada fora da transação. `gravar_extracao` grava os três artefatos atomicamente, com UUIDv5 estável por job/submissão e índice único nesse par. Uma reentrega retorna a extração existente, mesmo que receba outro resultado candidato. Na corrida entre escritores, a transação perdedora reverte também seu prompt e sua resposta e lê o vencedor. Falhas SQL são propagadas por uma exceção sanitizada, sem parâmetros do driver.

O codegen tem `SELECT` e `INSERT` na nova tabela; a API tem somente `SELECT`; o worker não tem acesso. A criação da versão de `regras`, transições, auditoria e outbox continuam sob responsabilidade da API.

O contrato de `regra-extraida` exige somente estas referências de negócio:

```json
{
  "job_id": "3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021",
  "submissao_id": "13ed2c69-2903-4e35-a715-59ecf061f3e1",
  "extracao_id": "8a267bec-3e5e-5ed9-b151-710d03f573b8"
}
```

`representacao` é expressamente proibida nesse evento. A mudança quebra o payload anterior por decisão aprovada de cumprir o ADR-001; ainda não havia produtor ou consumidor implementado. Campos futuros do envelope continuam permitidos, conforme a evolução de eventos.

Na T-204, o chamador deve consultar `buscar_extracao` antes da LLM, persistir antes de publicar, aguardar confirmação do broker e só então confirmar a mensagem de entrada. Uma falha entre commit e publicação é recuperada por reentrega e republicação da mesma referência. O codegen não passa a escrever no outbox da API. Na T-202, o consumidor deve verificar `extracao_id`/`job_id`/`submissao_id`, criar a versão raiz e registrar `regra-submetida` em uma transação própria, com idempotência.

## Validação e observabilidade

Os testes unitários usam um modelo roteirizado. Os testes de persistência sobem PostgreSQL descartável, aplicam o DDL das migrations da API e conectam com o usuário do codegen; não alteram o banco do compose. A suíte da API valida aplicação/rollback pelo Liquibase e permissões dos três serviços.

```sh
make pre-commit
make lint
RUN_POSTGRES_INTEGRATION=1 poetry run pytest tests/app/repositorio/test_extracoes_postgres.py
```

Motor e repositório não emitem logs nem métricas próprios. O nó `extract_rule` emite início, conclusão e falha com `job_id` e `no = extracao_parametros`, sem conteúdo da regra, do prompt ou da resposta. Nos desfechos, `extra.extracao_reutilizada` indica se a tentativa encontrou um artefato já persistido e dispensou a chamada ao modelo; `false` também cobre falhas anteriores à consulta. A conclusão inclui as contagens por construto e por motivo de rebaixamento. A falha inclui a `operacao` que estava em execução: validação da entrada, consulta, carregamento do modelo, extração, gravação ou publicação de cada um dos três eventos.

O `motivo` de falha é definido pelo tipo da exceção: `timeout`, `conexao`, a classe de falha permanente/cancelamento, ou `falha_na_operacao` para erros sem classificação específica. Mensagens e cadeias de exceções não são inspecionadas nem emitidas. A `classe` e os labels das métricas permanecem os mesmos.

Com `job_name = extract_rule`, `job_runs_total` conta execuções do nó, inclusive tentativas que reutilizam o artefato; `job_failures_total` conta as que falham. `job_duration_seconds` mede toda a execução do nó, incluindo banco, retries do provedor e publicações, tanto em sucesso quanto em falha. Os buckets preservam os limites anteriores até 10 segundos e acrescentam 15, 30, 45, 60, 90, 120, 180, 240 e 300 segundos antes de `+Inf`, para distinguir chamadas longas e retries. Os contadores de elementos e rebaixamentos avançam apenas quando o nó conclui. Uma reentrega descartada pelo checkpoint não executa o nó e não incrementa essas medidas.

Os testes de `tests/app/graph/test_extracao.py` exercitam consumer, roteador e grafo com modelo, banco e produtores falsos; conferem logs serializados e deltas no registry servido por `/metrics`, incluindo recuperação de publicação e durações controladas por relógio falso. Isso verifica a emissão e a exposição local, mas não comprova coleta externa por Prometheus, Alloy ou Grafana.
