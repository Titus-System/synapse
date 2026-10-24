# Conferência de escopo

O worker confere, fora do container e antes do veredito, que o código gerado não mudou a comissão de quem a regra não alcança. A conferência só roda com o campo `alcance` no comando, e hoje o codegen não o envia: ela está pronta no worker e desligada na origem. O contrato da conferência é o campo `alcance` do comando [`executar-codigo`](../../contracts/events/executar-codigo.schema.json), a causa `fora_do_escopo` de [`resultado-diagnostico`](../../contracts/domain/resultado-diagnostico.schema.json) e a seção "Conferência de escopo" de [`contracts/harness/README.md`](../../contracts/harness/README.md).

## Onde está

| Arquivo | O quê |
| --- | --- |
| `app/mensageria/contracts.py` | `ExecutarCodigo.alcance`: opcional, e `null` é recusado como o orçamento nulo |
| `app/execucao/preparo.py` | `ExecucaoPreparada.alcance`, fora do `payload`, como o orçamento |
| `app/execucao/escopo.py` | `alcanca`, `conferir_escopo` e `ForaDoEscopo` |
| `app/execucao/veredito.py` | o motivo `fora_do_escopo` em `julgar`, depois da cobertura |
| `app/execucao/coleta.py` | `fora_do_escopo` no vocabulário de `Motivo` |
| `app/execucao/registro.py` | `linhas_fora_do_escopo` no diagnóstico |
| `app/mensageria/consumidor.py` | passa o alcance ao julgamento, registra o log e conta a falha |
| `app/core/metrics/global_metrics.py` | o contador `worker_fora_do_escopo_total` |

## A regra

Uma linha do detalhamento está no alcance quando a competência está na vigência, cada código da linha (`cod_loja`, `cod_marca`, `cod_cargo`) está no filtro da sua dimensão e nenhum deles está entre os excluídos. Um campo ausente do alcance não restringe a dimensão. Toda linha fora do alcance precisa ter `comissao_simulada` igual a `comissao_baseline`, com tolerância de um centavo.

| Situação | Desfecho |
| --- | --- |
| comando sem `alcance` | a conferência não roda, e a execução é julgada como antes |
| comando com `alcance: null` | DLQ, sem executar: lido como ausência, desligaria a conferência em silêncio |
| toda linha fora do alcance com a comissão do baseline | segue para o veredito, com o mesmo resultado de sem a conferência |
| diferença de até um centavo fora do alcance | aceita, como arredondamento do código que reapura a linha do baseline |
| linha fora do alcance com a comissão mudada | `erro_codigo`, `fora_do_escopo`, com o total e até cinco linhas no diagnóstico |
| baseline divergente, detalhamento incoerente ou cobertura incompleta | o motivo é o dessas conferências, que rodam antes |

O diagnóstico leva `linhas_fora_do_escopo.total`, quantas linhas mudaram, e `exemplos`, as cinco primeiras na ordem do detalhamento, com competência, matrícula, loja, marca, cargo e a diferença. O codegen as devolve ao modelo para corrigir o código. A linha gravada sai com `status = erro_codigo`, `veredito`, `totais` e `decomposicao` nulos, como qualquer `erro_codigo`.

## As decisões

1. **O alcance não atravessa o container.** Quem produz o número não alcança o critério que vai julgá-lo. O `payload` continua com os mesmos campos, e o alcance fica em `ExecucaoPreparada`.
2. **O codegen calcula, o worker só aplica.** A interpretação da representação da regra (o núcleo, as taxas por cargo, as exclusões) fica no codegen, em `AlcanceDaRegra`, a mesma classe que separa a parte fixa da comissão na sugestão de taxa. O worker recebe códigos prontos e não conhece a representação.
3. **A conferência roda depois da cobertura.** Quando o baseline diverge, o detalhamento é incoerente ou a cobertura está incompleta, o motivo é o dessas conferências: o número que saiu do container é conferido antes de qualquer outra coisa ser lida dele.
4. **Só um `sucesso` é conferido.** Uma asserção violada, uma exceção ou um timeout continuam com o motivo que tinham.

## Observabilidade

O log `execução julgada` de uma falha de escopo leva o `job_id`, `motivo = fora_do_escopo` e `quantidade_fora_do_escopo`. As matrículas e as diferenças vêm do detalhamento que o container devolveu e ficam só no diagnóstico da linha. O log `execução preparada` leva `com_alcance`, que diz se a conferência vai rodar.

`worker_fora_do_escopo_total` é um contador sem labels, exposto em `/metrics` desde a subida, com zero. Ele conta execuções no sandbox julgadas fora do escopo, com a mesma contagem de `worker_cobertura_incompleta_total`: a reentrega que encontra o resultado já gravado não executa nem julga de novo e não conta, e a execução repetida porque a gravação falhou conta de novo.

## Implantação

O `MensagemBase` ignora campo desconhecido, então um worker anterior a esta versão recebe o comando com `alcance` e executa sem a conferência. A imagem do sandbox não muda.

## Verificação

Na pasta `worker/`:

```bash
poetry run pytest tests/app/execucao/test_escopo.py tests/app/execucao/test_veredito.py tests/app/execucao/test_registro.py tests/app/mensageria/test_consumidor.py
sh verify.sh
```

`test_escopo.py` cobre cada dimensão, a vigência, a tolerância e o limite de exemplos. `test_consumidor.py` confere a linha, o diagnóstico contra o contrato, o payload sem o alcance, o log serializado contra o schema e sem matrícula, o contador no registry e em `/metrics`, e a DLQ do `alcance` nulo.
