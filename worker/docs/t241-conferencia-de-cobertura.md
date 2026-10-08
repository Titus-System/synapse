# T-241: conferência de cobertura por elemento da regra

O worker confere, fora do container e antes do veredito, que o código gerado implementou todos os elementos que a regra exige. O contrato da conferência é o da T-240: `elementos_exigidos` no comando [`executar-codigo`](../../contracts/events/executar-codigo.schema.json), `elementos_implementados` no retorno de `aplicar_regra` e a seção "Conferência de cobertura" de [`contracts/harness/README.md`](../../contracts/harness/README.md).

## Onde está

| Arquivo | O quê |
| --- | --- |
| `app/mensageria/contracts.py` | `ExecutarCodigo.elementos_exigidos`: opcional, cada item no padrão de `elemento_ref`, sem repetição |
| `app/execucao/preparo.py` | `ExecucaoPreparada.elementos_exigidos`, fora do `payload`, como o orçamento |
| `app/sandbox/harness.py` | `conferir_declaracao`: lê e valida `elementos_implementados` dentro do container |
| `app/sandbox/envelope.py` | o envelope passa à versão 2, com `elementos_implementados` |
| `app/execucao/coleta.py` | confere a declaração do envelope e a leva em `DesfechoClassificado` |
| `app/execucao/veredito.py` | `conferir_cobertura` e o motivo `cobertura_incompleta` em `julgar` |
| `app/execucao/registro.py` | `elementos_ausentes` e `elementos_fora_da_regra` no diagnóstico |
| `app/mensageria/consumidor.py` | passa os elementos exigidos ao julgamento, registra o log e conta a falha |
| `app/core/metrics/global_metrics.py` | o contador `worker_cobertura_incompleta_total` |
| `scripts/casos_geracao.py` | o avaliador da T-243 confere a cobertura com os elementos exigidos de cada caso |

## A regra

A cobertura está completa quando valem as duas condições:

1. todo elemento de `elementos_exigidos` está em `elementos_implementados`;
2. todo elemento com contribuição na decomposição está em `elementos_exigidos`.

Juntas, elas garantem que todo elemento com contribuição está declarado. Os elementos com contribuição são as chaves de `decomposicao.elemento`, que o harness cria para cada `elemento_ref` de `contribuicoes`, mesmo quando as contribuições de um elemento somam zero.

| Situação | Desfecho |
| --- | --- |
| comando sem `elementos_exigidos` | a conferência não roda, e a execução é julgada como antes |
| todo exigido declarado, toda contribuição de um exigido | segue para o veredito, com o mesmo resultado de sem a conferência |
| elemento declarado sem contribuição (exclusão, condição de limiar, sem ocorrência no período) | aceito |
| elemento declarado a mais, sem contribuição | aceito |
| exigido não declarado, com ou sem contribuição | `erro_codigo`, `cobertura_incompleta`, o elemento em `elementos_ausentes` |
| contribuição de um elemento que o comando não exige, declarado ou não | `erro_codigo`, `cobertura_incompleta`, o elemento em `elementos_fora_da_regra` |
| código sem a chave `elementos_implementados`, num comando que exige elementos | `cobertura_incompleta`, com todos os exigidos em `elementos_ausentes` |
| chave presente que não é lista de identificadores de `elemento_ref` | `erro_codigo`, `excecao`, com `SaidaForaDoContratoError`: a saída está fora do contrato, e a conferência nem roda |

`elementos_ausentes` segue a ordem do comando, e `elementos_fora_da_regra` a da decomposição. A cobertura incompleta não grava resultado parcial nem veredito: a linha sai com `status = erro_codigo`, `veredito`, `totais` e `decomposicao` nulos, e o job termina em erro pelo caminho de qualquer `erro_codigo`.

## As decisões

1. **A declaração atravessa o container, e o critério não.** O harness lê `elementos_implementados` do retorno de `aplicar_regra`, confere que é uma lista de identificadores e a escreve no envelope, só ao lado de um resultado de sucesso. `elementos_exigidos` fica em `ExecucaoPreparada`, fora do `payload`, como o orçamento: quem declara não alcança o critério que vai julgar a declaração.
2. **O worker não confia na declaração que chega.** `coleta.py` reprova como `envelope_invalido` uma declaração que não seja lista de identificadores de `elemento_ref`, ou que apareça em `assercao_violada` ou `erro_codigo`. Os identificadores chegam ao diagnóstico, e texto livre não pode chegar lá.
3. **O envelope passou à versão 2.** Uma imagem do sandbox construída antes desta mudança escreve o envelope da versão 1, sem a declaração, e toda execução dela sai `envelope_invalido`. A imagem e o worker são implantados juntos.
4. **A conferência roda depois da conferência do baseline.** Quando as duas falham, o motivo é `baseline_divergente`: a integridade do número que saiu do container é conferida antes de qualquer outra coisa ser lida dele.
5. **Só um `sucesso` é conferido.** Uma asserção violada, uma exceção ou um timeout continuam com o motivo que tinham.

## Observabilidade

O log `execução julgada` de uma cobertura incompleta leva o `job_id`, `motivo = cobertura_incompleta`, `elementos_ausentes` e `quantidade_fora_da_regra`. As ausentes vêm do comando. As fora da regra vêm do código gerado: o padrão de `elemento_ref` restringe os caracteres, mas não o tamanho nem a quantidade, por isso o log leva só quantas são, e a lista fica no diagnóstico da linha. O log `execução preparada` passou a levar `elementos_exigidos`, nulo quando a conferência não vai rodar.

`worker_cobertura_incompleta_total` é um contador sem labels, carregado pela composição da aplicação (`app/main.py`) e exposto em `/metrics` desde a subida, com zero. Ele conta execuções no sandbox julgadas com cobertura incompleta, e não jobs: a reentrega que encontra o resultado já gravado não executa nem julga de novo e não conta, e a execução repetida porque a gravação falhou é outra execução e conta de novo. Os demais fluxos do worker continuam sem métrica de domínio.

## O avaliador de geração

`executar_caso` passa a `julgar` os elementos exigidos de cada caso, montados pela regra da T-240 (`Caso.elementos_exigidos`). Um código que não declara um elemento do caso termina em `falhou_sem_esperar`, com `erro_codigo/cobertura_incompleta`, e o relatório aponta os elementos: `elementos não declarados` e `elementos fora da regra` no texto, `elementos_ausentes` e `elementos_fora_da_regra` no JSON.

## Implantação

O codegen já envia `elementos_exigidos` (T-242). Antes desta versão o worker ignorava o campo. A imagem do sandbox precisa ser reconstruída junto com o worker (`make build-sandbox-image`), por causa da versão 2 do envelope.

## Verificação

Na pasta `worker/`:

```bash
poetry run pytest tests/app/execucao/test_veredito.py tests/app/execucao/test_registro.py tests/app/execucao/test_coleta.py tests/app/sandbox/test_harness.py tests/app/sandbox/test_executor.py tests/app/mensageria/test_consumidor.py tests/scripts/test_casos_geracao.py
poetry run pytest -m docker tests/app/execucao/test_cobertura_integration.py tests/scripts/test_avaliar_geracao_integration.py
poetry run pytest -m e2e tests/e2e/test_desfechos.py -k cobertura
sh verify.sh
```

`test_cobertura_integration.py` percorre, contra a imagem real, cada critério: do comando lido do JSON ao julgamento e à linha que seria gravada. `test_consumidor.py` confere a linha, o diagnóstico, o evento, o log serializado contra o schema e o contador no registry e em `/metrics`. O e2e faz o mesmo com o processo real, lendo o log JSON e o `/metrics` pela porta HTTP.
