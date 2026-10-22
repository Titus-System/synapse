# Sugestão de adaptação ao orçamento

Após uma simulação bem-sucedida cujo veredito é `inviavel`, o codegen pode ajustar
apenas o percentual uniforme do núcleo, preservando os demais campos. Regras com
especificações ou `taxas_por_cargo` exigem revisão manual: reduzir só uma taxa não
representaria a proposta inteira. Ausência de alternativa não prova que inexiste solução.

A busca determinística usa `Decimal` e resultados persistidos pelo worker:

- Estimativa: `percentual × (orçamento − baseline) / (simulado − baseline)`, quando
  `0 ≤ baseline < orçamento < simulado`.
- Sondagem: quando o orçamento não supera o baseline e é positivo, tenta uma taxa
  proporcional ao orçamento e ao total simulado.
- Refinamento: com pelo menos duas taxas distintas já simuladas, usa a relação observada
  entre taxas e comissões para escolher outra candidata. O limite é de três propostas.

As taxas são truncadas em quatro casas, precisam ser positivas, menores que a taxa de
origem e coerentes com a representação. Não há chamada de LLM para escolher a taxa nem
produzir os totais. Cada candidata precisa de uma simulação no worker para confirmar sua
viabilidade. Meta e orçamento permanecem os parâmetros do job; a validação completa é
executada antes de gerar e delegar cada regra.

1. O codegen publica `sugestao-adaptacao-proposta`, referenciando job, versão e resultado
   de origem, com a tentativa e o método utilizados.
2. A API trava o job, confere procedência, resultado e tentativa e rejeita mudanças além
   do percentual permitido ou propostas duplicadas.
3. A versão com origem `sugestao_adaptacao` e o evento `regra-submetida` são gravados na
   mesma transação pelo outbox, preservando competências, orçamento e meta.
4. O codegen executa o ciclo dessa versão e o worker simula a candidata no sandbox.
5. Uma candidata ainda inviável pode originar a tentativa seguinte, até o limite de três.
   Esgotamento, regra não suportada ou ausência de candidata encerram a busca automática.

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

Há até três propostas automáticas para o recorte suportado, sem garantia de encontrar toda
solução possível. Regras com parcelas fixas ou especificações complexas ficam fora da
estimativa. O valor final e a viabilidade sempre vêm do worker.

## Verificação

- `api`: `make check` — persistência, procedência, duplicatas, ordem dos eventos e dois resultados.
- `codegen`: `make pre-commit` e `make test-rabbitmq` — cálculo, decisão e retomada após falha.
- `frontend`: `make check` — vínculo por versão, atualização SSE, aceitação e desfechos da alternativa.
- `worker`: `sh verify.sh` — contratos e execução isolada do consumidor existente.
