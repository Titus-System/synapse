# Sugestão de adaptação ao orçamento

Após uma simulação bem-sucedida cujo veredito é `inviavel`, o codegen propõe uma versão alternativa da regra, qualquer que seja a sua estrutura. A alternativa reduz na mesma proporção todas as taxas: o percentual uniforme do núcleo, cada taxa de `taxas_por_cargo` e o valor dos efeitos `acrescimo_pct` e `substituicao_pct` de `faixa_valor` e `janela_datas`. Valores em reais (bônus, efeitos em reais), limiares, exclusões, escopo, vigência e o texto dos elementos genéricos ficam como estavam. Ausência de alternativa não prova que inexiste solução.

A busca determinística usa `Decimal` e resultados persistidos pelo worker. A primeira taxa positiva, na ordem acima, é a referência: ela é estimada como se fosse a única taxa da regra, e as demais são multiplicadas pela razão entre a referência nova e a atual.

- Estimativa: `referência × (orçamento − parte fixa) / (simulado − parte fixa)`, quando `0 ≤ parte fixa < orçamento < simulado`. A parte fixa é a comissão das linhas do detalhamento que a regra não alcança, sem contribuição de elemento algum: fora da vigência, dos filtros de loja, marca e cargo, excluídas, ou do cargo sem taxa própria quando não há taxa uniforme. Como ela nunca passa da verdadeira, a estimativa nunca fica abaixo da taxa que cabe.
- Sondagem: sem o detalhamento, num resultado gravado antes dele, a parte fixa é zero e a referência é proporcional ao orçamento e ao total simulado.
- Refinamento: com pelo menos duas referências distintas já simuladas, usa a reta observada entre referência e comissão para escolher outra candidata. O limite é de três propostas.

As taxas são truncadas em quatro casas, em direção a zero. Taxa zero continua zero; as demais precisam manter o sinal e diminuir em módulo, e a regra proposta precisa ser coerente. Não há chamada de LLM para escolher as taxas nem produzir os totais. Cada candidata precisa de uma simulação no worker para confirmar sua viabilidade. Meta e orçamento permanecem os parâmetros do job; a validação completa é executada antes de gerar e delegar cada regra.

Quando a regra tem dentro do escopo uma parte que não acompanha as taxas, como um bônus em reais, a primeira estimativa tende a não caber, e o refinamento corrige a tentativa seguinte. Quando o orçamento não passa das comissões que a regra não altera, como as de lojas, marcas e cargos fora dela, nenhuma redução o alcança. A primeira alternativa ainda é simulada, proporcional ao orçamento, para o usuário ver a regra reduzida e o motivo de ela não caber, e a busca termina sem alternativa na tentativa seguinte.

1. O codegen publica `sugestao-adaptacao-proposta`, referenciando job, versão e resultado de origem, com a tentativa e o método utilizados.
2. A API trava o job, confere procedência, resultado e tentativa e rejeita mudanças além da redução das taxas ou propostas duplicadas.
3. A versão com origem `sugestao_adaptacao` e o evento `regra-submetida` são gravados na mesma transação pelo outbox, preservando competências, orçamento e meta.
4. O codegen executa o ciclo dessa versão e o worker simula a candidata no sandbox.
5. Uma candidata ainda inviável pode originar a tentativa seguinte, até o limite de três. Esgotamento, regra sem taxa positiva ou ausência de candidata encerram a busca automática.

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

Há até três propostas automáticas, sem garantia de encontrar toda solução possível. A tela informa que as taxas da alternativa foram reduzidas na mesma proporção e que as demais condições foram mantidas. Quando a decomposição absoluta por loja comprova que as comissões das lojas fora do escopo já ultrapassam o orçamento, a API informa os dois valores no campo existente `motivo`, na consulta e no evento de estado. A tela destaca essa explicação: reduzir as taxas do escopo não altera essas comissões e não basta para atingir o orçamento. Sem essa evidência, mantém a explicação neutra. O valor final e a viabilidade sempre vêm do worker.

## Sugestão de meta de vendas maior

Uma simulação viável com orçamento pode originar a busca de uma meta maior, mantendo a
regra. O frontend apresenta o progresso por `busca_meta_em_curso` e os desfechos de
`meta_sugerida`, já disponibilizados pela API. Os eventos `buscando_meta`, `meta_sugerida`,
`sem_solucao` e `busca_meta_encerrada` da etapa `sugestao_adaptacao` disparam uma nova
consulta do job, inclusive quando seu status principal não muda.

Quando há uma meta encontrada, a tela mostra meta, comissão simulada e orçamento como
recebidos, sem calcular aumentos ou novos valores financeiros. A meta atual pode ser
mantida. A opção “Usar meta sugerida” envia a ação existente `aceitar_meta` e só atualiza
a simulação após a resposta confirmada da API, aproveitando o resultado já executado.
O relatório é invalidado quando a meta da execução muda. Falha da ação fica no cartão
da sugestão, preservando a simulação aprovada; resposta de um job anterior não pode
alterar o job que está aberto. A requisição de aceitação registra início, resultado,
duração e job, sem token, payload ou totais financeiros nos logs.

O aceite também permanece no histórico do job finalizado. A consulta entrega o campo
opcional `simulacao.meta_sugerida_aceita_em` (e o mesmo campo em `simulacoes`) a partir
de `sugestoes_meta_venda.aceita_em`, somente quando job, versão e resultado vinculado
correspondem à sugestão aceita. A tela mostra “Meta de vendas sugerida aceita” com a
data no resumo e na execução selecionada. O valor continua vindo de
`simulacao.meta_venda`; a aceitação não cria outra versão da lógica da regra. Sem
registro de aceite, o campo fica ausente e a tela não atribui uma origem à meta.

## Verificação

- `api`: `make check` — persistência, procedência, duplicatas, ordem dos eventos e dois resultados.
- `codegen`: `make pre-commit` e `make test-rabbitmq` — cálculo, decisão e retomada após falha.
- `frontend`: `make check` — vínculo por versão, atualização SSE, aceitação e desfechos da alternativa.
- `worker`: `sh verify.sh` — contratos e execução isolada do consumidor existente.
