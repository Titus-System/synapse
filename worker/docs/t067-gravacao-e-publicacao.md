# T-067: gravar o resultado e publicar `simulacao-concluida`

Depois de o container devolver o resultado, a T-065 o classificar e a T-066 o julgar, o worker
**grava** a linha em `resultados_simulacao` e **só depois** publica `simulacao-concluida` numa
exchange fanout, da qual a `api` e o codegen consomem, cada um pela sua fila. É o ponto em que o
resultado entra no sistema: sem ele o job não sai de `simulando`.

Um evento que referencia uma linha inexistente é pior que um evento perdido; um evento perdido
não perde a linha, que é consultável e reconciliável depois.

## Onde está

| Arquivo | O quê |
| --- | --- |
| `app/repositorio/resultados.py` | `gravar_resultado` (INSERT) e `buscar_resultado` (SELECT), com o usuário do worker |
| `app/execucao/registro.py` | `linha_do_julgamento` e `evento_de`: do julgamento à linha e ao evento, funções puras |
| `app/mensageria/publicador.py` | `publicar_simulacao_concluida`: `mandatory`, com confirmação |
| `app/mensageria/broker.py` | declara a exchange `simulacao-concluida` (fanout, durável, sem `x-*`) |
| `app/mensageria/consumidor.py` | a ordem: consulta, executa, julga, grava, publica, `ack` |
| `app/mensageria/retry.py` | `ultima_tentativa`: quando um `erro_infra` vai para a DLQ |
| `docs/decisoes/dec-094.md` | o esgotamento de `erro_infra` (emenda da DEC-091) |

## A ordem

```
comando → código (SELECT) → o código é do job do comando? (senão DLQ)
        → já há resultado para (job, código)?
            sim → republica o evento da linha → ack                     (não executa de novo)
            não → container → classifica → julga
                → GRAVA (transação confirmada) → PUBLICA (confirmada) → ack
```

O `ack` vem por último. A gravação confirma a transação **antes** de a função devolver, então o
evento só existe depois de a linha ser consultável; um teste de ponta a ponta confere isso do lado
de fora, consultando o banco no instante em que o consumidor do codegen recebe o evento.

## O que é gravado e o que viaja

`resultados_simulacao` guarda o resultado inteiro; o evento leva a referência e os agregados que o
schema prevê (claim-check, ARCHITECTURE.md §6.1). O contrato **não foi alterado**.

| Coluna / campo | `sucesso` | `assercao_violada`, `erro_codigo`, `erro_infra` |
| --- | --- | --- |
| `status` | `sucesso` | a classe |
| `veredito` | `viavel` ou `inviavel` | nulo (nunca `indeterminado`) |
| `totais` | os do container **mais `orcamento`** | nulo |
| `assercoes` | as do resultado | as do desfecho (`[]` em `erro_infra`) |
| `decomposicao` | a do container, como veio | nulo |
| evento: `veredito`, `total_*`, `diferenca_*` | presentes | **ausentes** |

O `indeterminado` é o veredito interno da T-066 e **nunca** é gravado nem publicado: o schema e a
tabela o declaram nulo/ausente fora de `sucesso`, e a `api` lê `sucesso` + `indeterminado` como
número confiável ainda sem julgamento. `evento_de` monta o evento por validação do pydantic, então
uma linha com status ou veredito fora do vocabulário não vira evento.

### Desvios do texto da tarefa

- **O evento não leva o "desfecho das asserções".** O schema (contrato público, e critério de
  aceitação) não tem esse campo: as asserções ficam na linha. Acrescentá-lo exigiria alterar o
  contrato, com autorização e relatório de impacto.
- **O worker tem `SELECT` além de `INSERT`** em `resultados_simulacao` (migration 010). O requisito
  "apenas INSERT" vale para escrita: `UPDATE`, `DELETE` e qualquer outra tabela falham por
  permissão, e há teste para cada um.

## A exchange e a garantia de entrega

A exchange fanout `simulacao-concluida` é declarada pelo worker ao conectar, com os mesmos
parâmetros que a `api` e o codegen usam (durável, sem `x-*`); uma declaração divergente seria
rejeitada com 406 (DEC-089). O worker **não** declara nem liga as filas dos consumidores: cada um
declara a sua (`simulacao-concluida.api`, `simulacao-concluida.codegen`).

Um fanout sem nenhuma fila ligada **descarta a mensagem em silêncio**, e é o que ocorreria se o
worker publicasse antes de a `api` e o codegen subirem. Por isso a publicação é `mandatory` e espera a
confirmação: sem rota, o broker devolve a mensagem e o worker sabe que o evento não chegou a
ninguém. Quem liga a fila depois **não** recebe o que passou (a exchange não retém): a linha é a
fonte de verdade, e o evento, o aviso.

Com a `api` (ou o codegen) desligada, a fila dela existe e acumula: o outro consumidor recebe
normalmente, e ao voltar ela encontra o evento esperando. Testado nos dois sentidos, e também com
uma fila que nunca foi declarada.

## Falhas: para onde cada uma vai

| Falha | Destino |
| --- | --- |
| banco fora ao consultar ou gravar (conexão, timeout, conexão invalidada) | retry da DEC-091 (`synapse_retry_count`) |
| violação de integridade ao gravar (FK) | DLQ: não é transitória |
| publicação sem rota, recusada, sem confirmação, canal caído | retry: a linha já está gravada, e a próxima tentativa a encontra e só republica |
| `job_id` do comando diferente do do código gerado | DLQ, sem consultar nem executar: o par é incoerente, e a tabela é INSERT-only |
| container não sobe (`SandboxInfraError`) | retry; na última tentativa, grava e publica `erro_infra` antes da DLQ |

### Reentrega sem duplicar

A tabela não tem chave única em `(job_id, codigo_gerado_id)` e o worker não pode apagar linha. Um
comando que volta depois de a publicação falhar (ou de uma queda antes do `ack`) encontraria o
resultado já gravado; por isso a consulta vem **antes** de subir o container. Se há linha, o
worker não executa de novo (60 s de container) nem grava outra: republica o evento e dá `ack`. A
consulta ignora `erro_infra`, para um comando reenviado da DLQ executar de novo.

Se o evento se perde (nenhuma fila ligada), as três tentativas encontram a mesma linha, o comando
vai à DLQ e **a linha é uma só e continua consultável**. Religada a fila, o operador reenvia o
comando e o evento sai, sem executar o container nem gravar outra linha. Há um teste de ponta a
ponta para esse cenário.

### Esgotamento de `erro_infra` (DEC-094)

A DEC-091 mandava o comando esgotado para a DLQ sem publicar nada, o que deixaria o job em
`simulando` para sempre. Agora, na última tentativa, o worker grava a linha `erro_infra`, publica o
evento e só então envia à DLQ; a linha é gravada uma vez, e não a cada tentativa. Se o banco ou o
broker também estiverem fora, a falha é registrada e a DLQ segue. Só vale para `SandboxInfraError`:
com o banco fora não há onde gravar.

## O que a T-067 não resolve

- **O erro da regra não tem onde viajar.** `resultados_simulacao` não tem coluna para o
  `tipo/mensagem/traceback` de um `erro_codigo`, e o evento também não. O codegen precisaria deles
  para regenerar o código com o erro em mãos. É uma lacuna do modelo (migration da `api`), não
  desta tarefa: o `stdout`, o `stderr` e a mensagem da regra seguem só na memória do worker, e nunca
  chegam a log.
- **A reconciliação de resultado órfão** (linha sem evento entregue) é operação, não código desta
  sprint. A DLQ guarda o comando, e reenviá-lo republica o evento.
- **A integração com a `api` e o codegen reais não é exercitada aqui.** Os dois consumidores
  existem e declaram a exchange do mesmo jeito, mas os testes desta tarefa fazem o papel deles
  (declaram a fila, ligam e leem), e nenhum sobe a `api` ou o codegen.

## Verificação

Na pasta `worker/`, com `postgres` e `rabbitmq` do compose de pé:

```bash
poetry run pytest tests/app/execucao/test_registro.py tests/app/mensageria     # unitários e integração
poetry run pytest tests/app/repositorio/test_resultados.py                     # Postgres, usuário do worker
sh verify.sh
```
