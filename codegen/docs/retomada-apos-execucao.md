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

Os artefatos e eventos de auditoria têm identificadores determinísticos. O worker deduplica por job, código, meta e propósito, preservando a independência entre a simulação original e as execuções candidatas.

## Até três taxas novas por job

Todo `status=sucesso` com `veredito=inviavel` encaminha para `suggest_adaptation`, qualquer que seja a estrutura da regra e inclusive quando a regra simulada já é uma alternativa. O sucesso sem veredito, de um job sem orçamento, termina o fluxo sem sugestão, porque não há orçamento em que a regra precise caber. Com veredito, o `decision` conta as versões `sugestao_adaptacao` do job até a versão simulada e grava a conta no estado (`tentativas_de_taxa`), de onde a sugestão a lê.

Cada taxa nova é uma tentativa com geração e simulação próprias, porque as taxas são constantes do código gerado, e vai na proposta com o número dela no job em `tentativa`, de 1 a 3. A proposta reduz na mesma proporção todas as taxas da regra: o percentual do núcleo, cada taxa de `taxas_por_cargo` e o valor dos efeitos `acrescimo_pct` e `substituicao_pct` de `faixa_valor` e `janela_datas`. Valores em reais, limiares, exclusões, escopo, vigência e o texto dos elementos genéricos ficam como estavam. A primeira taxa positiva, nessa ordem, é a referência: ela é estimada como se fosse a única taxa da regra, e cada outra taxa é multiplicada pela razão entre a referência nova e a atual, truncada em quatro casas decimais em direção a zero. Taxa zero continua zero, e uma taxa que zeraria ou não diminuiria em módulo impede a proposta. A estimativa parte das taxas de referência já simuladas na cadeia que liga a regra simulada à original por `regra_origem_id`, porque cada proposta reduz todas as taxas da versão de origem na mesma proporção; só contam as simulações de sucesso do job, nunca a execução candidata da busca da meta. Com uma taxa só na cadeia, a referência nova é `referência × (orçamento − baseline) / (simulado − baseline)`, truncada em quatro casas decimais, quando `0 ≤ baseline < orçamento < simulado`; ela é conservadora quando já havia comissão nas linhas afetadas, e otimista quando a regra tem uma parte que não acompanha as taxas, como um bônus em reais, caso em que o refinamento corrige a tentativa seguinte. Quando o orçamento não fica acima do baseline, essa fórmula não estima, porque supõe que a regra só soma às comissões de hoje; a primeira taxa é então uma sondagem, `referência × orçamento / simulado`, truncada da mesma forma. Como a regra substitui a taxa no seu escopo, a comissão é uma parte fixa entre zero e o baseline mais a taxa vezes as vendas no escopo, e a sondagem fica no máximo uma casa abaixo da taxa que cabe; simulada, ela dá o segundo ponto da reta (T-283). Com duas ou mais, é onde cruza o orçamento a reta que passa pelas duas de menor comissão, também truncada. Assim, uma regra que não veio de sugestão começa pela estimativa dos totais mesmo que o job já tenha tentado taxas para outra regra, e as tentativas dela contam no mesmo limite. Cada taxa proposta fica abaixo da taxa correspondente da regra simulada, e o veredito só existe após nova execução no worker.

A iteração termina sem alternativa quando a terceira taxa simulada não cabe, quando não há como estimar a taxa seguinte, quando a proposta nasceria incoerente ou quando a regra não tem taxa positiva a reduzir. Nesses casos a sugestão publica `etapa-alterada` com `etapa = sugestao_adaptacao` e `status = sem_alternativa`, e nenhuma proposta. Ausência de proposta significa ausência de estimativa suportada, não impossibilidade matemática de caber no orçamento. Um orçamento abaixo das comissões que a regra não altera, como as de lojas, marcas e cargos fora dela, também termina assim: nenhuma redução de taxa o alcança, e a reta do refinamento só o cruza abaixo de zero. Uma alternativa viável encerra a iteração sem nova proposta.

A conta das tentativas para na versão simulada, então a reentrega de um resultado depois de a API gravar a proposta seguinte não vira mais uma tentativa. Se a sugestão caiu depois de publicar a proposta, a reentrega a refaz com a mesma conta e as mesmas taxas e repete a mesma proposta.

`codegen_sugestao_adaptacao_tentativas_total{tentativa, desfecho}` conta cada tentativa no seu desfecho. O veredito da simulação da alternativa (`viavel`, `inviavel` ou `indeterminado`) é contado pela decisão, e o motivo de não haver taxa a propor (`sem_margem`, `incoerente` ou `nao_suportada`), pela sugestão. A proposta publicada ainda não é desfecho, e o fim pelo limite não é outra tentativa: a terceira já foi contada como `inviavel`. O log `adaptation proposal published` diz em `metodo` como a taxa foi obtida (`estimativa`, `sondagem` ou `refinamento`) e em `taxas_ajustadas` quantas taxas a proposta reduziu, sem as taxas nem os totais. A contagem é feita depois das publicações do nó, e a reentrega de um resultado já processado não passa pelos nós.

O evento `sugestao-adaptacao-proposta` entrega a candidata à API, que valida sua procedência, cria a versão e publica `regra-submetida` com orçamento, meta de venda e competências do job. A confirmação direta e as versões corrigidas entram por `parametros-confirmados`, também com o contexto no evento: o codegen não consulta `jobs`. O limite de tentativas é do codegen: a API registra o número da tentativa com a versão que a proposta cria e encerra a iteração pelo `sem_alternativa`.

O fluxo completo e sua apresentação estão em [`docs/SUGESTAO-ADAPTACAO.md`](../../docs/SUGESTAO-ADAPTACAO.md).

## Evolução da Sprint 2

O loop de correções por texto ou voz ainda precisa ser integrado. A pausa por inconsistência será condicional; uma regra processável seguirá automaticamente para geração. `parametros-confirmados` abre um ciclo por `job_id:regra_id`, em `load_rule`, usando `run_to_completion` e o mesmo guard de checkpoint de `regra-submetida`. Não retoma uma espera por confirmação nem acrescenta `interrupt()`.

Sem `competencias`, o consumer rejeita a mensagem sem requeue, com causa `contexto_ausente`, sem abrir grafo nem publicar `etapa-alterada`. Orçamento e meta ausentes não são falha: o comando sai sem eles. A integração da T-217 deve garantir o envio do contexto; publicações anteriores sem competências são drenadas e descartadas.

Os checkpoints de um job são removidos depois do `job-encerrado` da `api`, e o registro `jobs_grafo_encerrados` assume a deduplicação: depois da limpeza, uma reentrega de submissão, confirmação ou resultado é confirmada sem efeito. Uma confirmação também é recusada quando o encerramento está registrado e a limpeza ainda está pendente. Um ciclo pausado à espera do resultado não é removido antes de o resultado ser processado. Ver [mensageria](mensageria.md#encerramento-do-job-e-limpeza-dos-checkpoints) e a [DEC-095](../../docs/decisoes/dec-095.md).

## Busca da meta maior

Com `BUSCA_META_ENABLED=true`, o resultado viável com margem pode seguir para `search_sales_target`, qualquer que seja a estrutura da regra. O nó alterna com `dispatch_execution` e `await_execution`, mantendo o mesmo código e a versão, mas identificando cada execução por propósito e meta. A reentrega de uma candidata anterior não satisfaz a espera da seguinte. A busca termina publicando `meta-venda-sugerida` e uma conclusão própria de `decisao`. O algoritmo, limites, ativação e semântica das medidas estão em [busca-meta.md](busca-meta.md).
