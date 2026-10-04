# T-204: gravar o diagnóstico de um `erro_codigo`

Um resultado `erro_codigo` é gravado com o diagnóstico da falha na coluna `resultados_simulacao.diagnostico`, no mesmo INSERT da linha. O formato é o de `contracts/domain/resultado-diagnostico.schema.json`, e a coluna é criada pela migration `016` da `api`. O evento `simulacao-concluida` não muda: quem precisa do diagnóstico, como a `api` e o codegen, o lê da linha pelo `resultado_id`.

## Onde está

| Arquivo | O quê |
| --- | --- |
| `app/execucao/schema.py` | `Problema` (caminho e palavra-chave, sem valor) e `validar_diagnostico` |
| `app/execucao/registro.py` | `Diagnostico`, `diagnostico_do_julgamento` e a coluna nova em `LinhaDoResultado` |
| `app/repositorio/resultados.py` | `diagnostico` no INSERT de `gravar_resultado` |
| `app/mensageria/consumidor.py` | passa o diagnóstico à gravação, registra `com_diagnostico` e trata o diagnóstico fora do contrato |

## O que é gravado

| Desfecho | `diagnostico` |
| --- | --- |
| `erro_codigo` por exceção da regra | `causa: excecao` e a `falha` do envelope, como o sandbox a escreveu |
| `erro_codigo` por timeout, memória, saída truncada, sem envelope, envelope inválido ou de outra execução, código de saída divergente | só a `causa` |
| `erro_codigo` por resultado fora do schema | `causa` e `problemas`: caminho e palavra-chave de cada erro, sem o valor rejeitado |
| `erro_codigo` por baseline divergente | só a `causa`, que vem do julgamento e não da coleta |
| `sucesso`, `assercao_violada`, `erro_infra` | nulo |

A `causa` é o `motivo` da classificação. Nenhuma falha é inventada para uma causa sem exceção capturada, e o schema recusa um diagnóstico que tente.

Os problemas de schema passaram a ser estruturados desde `validar_resultado`, como `{caminho, palavra_chave}`, para o diagnóstico não precisar decompor texto. O log `execução julgada` continua os registrando como `<caminho>: <palavra-chave>`.

## Validação e falhas

`linha_do_julgamento` valida o diagnóstico contra o contrato antes de devolver a linha. Um diagnóstico que não valida é erro do worker, nunca da regra: levanta `DiagnosticoForaDoContratoError`, o consumidor registra `diagnóstico fora do contrato; encaminhando para DLQ` com os problemas (caminhos do próprio diagnóstico, sem conteúdo) e envia o comando à DLQ sem gravar nem publicar. Repetir daria o mesmo resultado, e gravar sem o diagnóstico perderia o que ele existe para guardar.

Como o diagnóstico está no mesmo INSERT, valem as garantias da T-067. A transação confirma antes da publicação, então nenhum evento referencia um diagnóstico que não foi gravado. Uma falha transitória ao gravar repete o comando sem publicar. Uma reentrega encontra a linha, republica o evento e não executa a regra nem grava outra linha, e o diagnóstico continua o que era.

## O que vai para o log

A mensagem e o traceback da regra vão só para a linha. O log `resultado gravado` ganhou `com_diagnostico`, que diz se a linha foi gravada com diagnóstico sem mostrar o conteúdo. O evento continua com `job_id`, `resultado_id` e `status`.

Esta tarefa não acrescenta métricas. O worker ainda não emite métricas de domínio em nenhuma etapa da execução (`job_runs`, `job_failures` e `job_duration` estão declaradas em `app/core/metrics/global_metrics.py`, mas nenhum caminho as usa), e instrumentar a execução é trabalho próprio, que cobre execução, falha e duração e não só o diagnóstico.

## Implantação

A migration `016` da `api` tem de estar aplicada antes desta versão do worker. O INSERT novo menciona `diagnostico` e falharia contra um banco sem a coluna; o INSERT da versão anterior não a menciona e continua funcionando depois da migration.

## Verificação

Na pasta `worker/`, com `postgres` e `rabbitmq` do compose de pé e a migration `016` aplicada:

```bash
poetry run pytest tests/app/execucao/test_registro.py tests/app/execucao/test_schema.py tests/app/mensageria/test_consumidor.py
poetry run pytest -m "postgres or rabbitmq" tests/app/repositorio/test_resultados.py tests/app/mensageria/test_consumidor_execucao_integration.py
sh verify.sh
make e2e
```
