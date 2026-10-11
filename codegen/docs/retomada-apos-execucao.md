# Retomada do grafo após a execução no worker

O consumer de `simulacao-concluida.codegen` entrega o resultado ao checkpoint que solicitou sua execução. Cada versão tem seu próprio `thread_id = job_id:regra_id`; a regra é resolvida pelo vínculo `resultados_simulacao.codigo_gerado_id → codigos_gerados.regra_id`. Se não houver checkpoint versionado, o entrypoint consulta o identificador antigo `job_id` e só o reutiliza quando o estado contém o mesmo job e a mesma regra. A compatibilidade vale tanto para resultados quanto para reentregas da submissão, sem copiar checkpoints, repetir geração ou confundir a candidata com o ciclo original. Um checkpoint versionado existente tem prioridade.

```text
load_rule → code_generation → persist_response → extract_code → dispatch_execution
→ await_execution ⏸ → decision → suggest_adaptation → fim
                             ↘ fim
```

`dispatch_execution` publica o comando com código, competências e `proposito = simulacao`, e com o orçamento e a meta de venda quando o job os tem (T-272). Sem orçamento, o worker simula sem a verificação de orçamento e o resultado de sucesso volta sem veredito; com a meta, simula sobre as vendas escaladas até ela. O nó `await_execution` só interrompe: efeitos anteriores ao `interrupt()` seriam repetidos quando o grafo fosse retomado. A retomada leva referências e status, nunca números gerados por modelo. O worker calcula os totais sobre os dados históricos, escalados até a meta quando houver.

## Reentregas e falhas

- Sem checkpoint: o resultado é desconhecido; a mensagem é rejeitada.
- Checkpoint anterior à pausa: reentregar, pois o resultado pode chegar antes da persistência do `interrupt()`.
- Na pausa: entregar `Command(resume=...)`.
- Resultado já registrado e nós posteriores pendentes: continuar com entrada `None`. Isso recupera falhas transitórias na publicação da sugestão sem repetir a geração nem perder o resultado recebido.
- Grafo concluído: confirmar a reentrega sem iniciar outro ciclo.

Os artefatos e eventos de auditoria têm identificadores determinísticos. O worker deduplica pelo par job/código, preservando a independência entre a simulação original e a alternativa.

## Até três taxas novas por job

Só `status=sucesso` com `veredito=inviavel` de uma regra sem especificações encaminha para `suggest_adaptation`, inclusive quando a regra simulada já é uma alternativa. O sucesso sem veredito, de um job sem orçamento, termina o fluxo sem sugestão, porque não há orçamento em que a regra precise caber. Com veredito, o `decision` conta as versões `sugestao_adaptacao` do job até a versão simulada e grava a conta no estado (`tentativas_de_taxa`), de onde a sugestão a lê.

Cada taxa nova é uma tentativa com geração e simulação próprias, porque o percentual é uma constante do código gerado, e vai na proposta com o número dela no job em `tentativa`, de 1 a 3. A proposta altera exclusivamente o percentual do núcleo. A estimativa parte das taxas já simuladas na cadeia que liga a regra simulada à original por `regra_origem_id`, porque cada proposta muda só o percentual da versão de origem; só contam as simulações de sucesso do job, nunca a execução candidata da busca da meta. Com uma taxa só na cadeia, a taxa nova é `percentual × (orçamento − baseline) / (simulado − baseline)`, truncada em quatro casas decimais, quando `0 ≤ baseline < orçamento < simulado`; ela é conservadora quando já havia comissão nas linhas afetadas. Com duas ou mais, é onde cruza o orçamento a reta que passa pelas duas de menor comissão, também truncada. Assim, uma regra que não veio de sugestão começa pela estimativa dos totais mesmo que o job já tenha tentado taxas para outra regra, e as tentativas dela contam no mesmo limite. A taxa proposta fica sempre abaixo da taxa da regra simulada, e o veredito só existe após nova execução no worker.

A iteração termina sem alternativa quando a terceira taxa simulada não cabe, quando não há como estimar a taxa seguinte ou quando a proposta nasceria incoerente. Nesses casos a sugestão publica `etapa-alterada` com `etapa = sugestao_adaptacao` e `status = sem_alternativa`, e nenhuma proposta. Ausência de proposta significa ausência de estimativa suportada, não impossibilidade matemática de caber no orçamento. Uma alternativa viável encerra a iteração sem nova proposta.

A conta das tentativas para na versão simulada, então a reentrega de um resultado depois de a API gravar a proposta seguinte não vira mais uma tentativa. Se a sugestão caiu depois de publicar a proposta, a reentrega a refaz com a mesma conta e as mesmas taxas e repete a mesma proposta.

`codegen_sugestao_adaptacao_tentativas_total{tentativa, desfecho}` conta cada tentativa no seu desfecho. O veredito da simulação da alternativa (`viavel`, `inviavel` ou `indeterminado`) é contado pela decisão, e o motivo de não haver taxa a propor (`sem_margem`, `incoerente` ou `nao_suportada`), pela sugestão. A proposta publicada ainda não é desfecho, e o fim pelo limite não é outra tentativa: a terceira já foi contada como `inviavel`. A contagem é feita depois das publicações do nó, e a reentrega de um resultado já processado não passa pelos nós.

O evento `sugestao-adaptacao-proposta` entrega a candidata à API, que valida sua procedência, cria a versão e publica `regra-submetida` com orçamento, meta de venda e competências do job. A confirmação direta e as versões corrigidas entram por `parametros-confirmados`, também com o contexto no evento: o codegen não consulta `jobs`. O limite de tentativas é do codegen: a API registra o número da tentativa com a versão que a proposta cria e encerra a iteração pelo `sem_alternativa`.

O fluxo completo e sua apresentação estão em [`docs/SUGESTAO-ADAPTACAO.md`](../../docs/SUGESTAO-ADAPTACAO.md).

## Evolução da Sprint 2

O loop de correções por texto ou voz ainda precisa ser integrado. A pausa por inconsistência será condicional; uma regra processável seguirá automaticamente para geração. `parametros-confirmados` abre um ciclo por `job_id:regra_id`, em `load_rule`, usando `run_to_completion` e o mesmo guard de checkpoint de `regra-submetida`. Não retoma uma espera por confirmação nem acrescenta `interrupt()`.

Sem `competencias`, o consumer rejeita a mensagem sem requeue, com causa `contexto_ausente`, sem abrir grafo nem publicar `etapa-alterada`. Orçamento e meta ausentes não são falha: o comando sai sem eles. A integração da T-217 deve garantir o envio do contexto; publicações anteriores sem competências são drenadas e descartadas.

Os checkpoints de um job são removidos depois do `job-encerrado` da `api`, e o registro `jobs_grafo_encerrados` assume a deduplicação: depois da limpeza, uma reentrega de submissão, confirmação ou resultado é confirmada sem efeito. Uma confirmação também é recusada quando o encerramento está registrado e a limpeza ainda está pendente. Um ciclo pausado à espera do resultado não é removido antes de o resultado ser processado. Ver [mensageria](mensageria.md#encerramento-do-job-e-limpeza-dos-checkpoints) e a [DEC-095](../../docs/decisoes/dec-095.md).
