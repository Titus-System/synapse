# Sugestão de adaptação ao orçamento

Após uma simulação bem-sucedida cujo veredito é `inviavel`, o codegen tenta reduzir apenas
o percentual do núcleo de regras simples, sem especificações. Os demais campos permanecem
iguais. A estimativa usa Decimal e os totais persistidos pelo worker:
`percentual × (orçamento − baseline) / (simulado − baseline)`, truncado em quatro casas.
Ela só se aplica quando `0 ≤ baseline < orçamento < simulado` e passa pela validação
determinística de coerência. Não há chamada adicional de LLM para escolher percentuais
ou produzir totais. A taxa é uma candidata conservadora; o worker confirma sua viabilidade.

Regras com especificações ou fora desse intervalo mantêm o resultado original e o caminho
de revisão manual. Não produzir proposta não significa que inexiste solução.

1. O codegen publica `sugestao-adaptacao-proposta`, referenciando job, regra original e resultado.
2. A API trava o job, confere que o resultado pertence à última versão e registra no máximo
   uma versão com origem `sugestao_adaptacao`. Propostas com outras alterações são descartadas.
3. A versão e o evento `regra-submetida` são gravados na mesma transação pelo outbox.
   O evento preserva origem, competências e orçamento do job e aponta a versão nova.
4. O codegen executa um ciclo com checkpoint próprio para essa versão e delega ao worker.
5. O worker simula a alternativa no sandbox. Se ela continuar inviável, não há terceira
   tentativa automática.

A proposta pode chegar à API antes do evento do resultado, pois são filas independentes.
Nesse caso a API aplica o desfecho persistido e reabre o processamento na mesma transação.
Após o commit, anuncia a transição para simulação quando necessária, o resultado original,
a inviabilidade e a abertura do novo ciclo, nessa ordem. A chegada posterior do evento do
worker não repete os anúncios nem altera o estado do novo ciclo.

Checkpoints existentes sob `job_id` continuam atendendo a mesma regra, inclusive em
reentregas da submissão. A alternativa recebe seu próprio checkpoint por versão.

## Consulta e interface

`GET /jobs/{id}` mantém `simulacao` como a execução mais recente e acrescenta `simulacoes`,
em ordem de criação. Cada simulação informa `regra_id`. Os campos novos são opcionais no
OpenAPI para compatibilidade aditiva; o frontend continua aceitando respostas anteriores.
Sem o vínculo, ele não atribui um resultado à sugestão por suposição.

A tela mantém regra e resultado originais e anuncia a execução da alternativa. Os campos
da candidata e seus totais aparecem depois da simulação. Uma alternativa viável pode ser
aceita e seguir à finalização, usando a versão corrente, sem solicitar outra simulação.
Recusar cancela o job pelo endpoint existente. Se a alternativa não couber, for indeterminada
ou falhar, a tela explicita esse desfecho e oferece iniciar uma nova regra.

Há uma tentativa automática para o recorte suportado, sem garantia de encontrar toda
solução possível. Regras com parcelas fixas ou especificações complexas ficam fora da
estimativa. O valor final e a viabilidade sempre vêm do worker.

## Verificação

- `api`: `make check` — persistência, procedência, duplicatas, ordem dos eventos e dois resultados.
- `codegen`: `make pre-commit` e `make test-rabbitmq` — cálculo, decisão e retomada após falha.
- `frontend`: `make check` — vínculo por versão, atualização SSE, aceitação e desfechos da alternativa.
- `worker`: `sh verify.sh` — contratos e execução isolada do consumidor existente.
