> HISTÓRICO CONTESTADO: as anotações deste documento foram contestadas pelo usuário. Consulte transcricao.md para a conclusão corrigida; não usar este texto como reprovação vigente.
# Revisão textual preliminar — 06/10/2026

Revisão das respostas Deepgram contra os textos esperados do manifesto, sem conferência auditiva. Não é ground truth validado nem medição final de qualidade. As respostas reais permanecem no JSON original; nenhum arquivo de áudio foi renomeado, remapeado ou marcado como conferido.

## Problemas do conjunto a investigar

| Arquivo | Referência registrada | Conteúdo reconhecido |
| --- | --- | --- |
| voz-a-r04 | matrícula, vinte mil reais e exclusão | texto semelhante à frase r05, intervalo de novembro e loja 21 |
| voz-a-r05 | intervalo de novembro e loja 21 | texto semelhante à frase r06, admissão, cargo 100 e bônus |
| voz-a-r06 | admissão, cargo 100 e bônus | texto semelhante à frase r07, marcas e faixas de vendas |
| voz-a-r07 | marcas e faixas de vendas | texto semelhante à frase r08, gerentes e faixas |
| voz-a-r08 | gerentes e faixas | percentual de 1,75%, cargo 200, marca 20 e exclusão da loja 13; conferir possível relação com r09 |

Essa sequência sugere associação incorreta entre áudio e frase, mas somente ouvir os arquivos pode confirmar. Não contabilizar esses casos automaticamente como cinco erros do ASR e não corrigir o manifesto usando apenas a hipótese de um provedor. A possível presença de r09 em outro arquivo precisa ser investigada antes de nova rodada, pois r09 foi excluída no conjunto recebido.

## Divergências críticas que precisam de conferência auditiva

- voz-a-r03: referência `MATRIC nove zero zero zero zero um`; resposta `matric nove mil um`. A identidade numérica não pode ser considerada preservada automaticamente.
- voz-a-r11: primeira matrícula perde o prefixo e aparece como `nove mil - zero três`; segunda matrícula aparece com a sequência esperada. Revisar separadamente.
- voz-b-r03: resposta tem um zero a menos na sequência da matrícula.
- voz-b-r04: prefixo da matrícula ausente, sequência menor e verbo reconhecido como `representa`, em vez de `acrescente`.
- voz-b-r11: prefixo MATRIC da primeira matrícula ausente.
- voz-b-r01 e voz-b-r06: `cargo` aparece como `carro`. O número isolado está presente, mas seu tipo/alvo pode não ser extraído corretamente pelo E1.
- voz-b-r02: `aos gerentes` aparece como `ao gerente`; conferir o efeito sobre a exclusão e o plural.

Há preservação textual visível de diversos percentuais, valores e datas nos demais casos, mas isso não valida a leitura nem a extração. O resultado é um diagnóstico de itens a revisar, sem percentual de acerto final.

## Latência observada

22 chamadas Deepgram, uma por arquivo, todas HTTP 200: média de 1.030,41 ms, incluindo upload e resposta. Essa média não é p95, não cobre gravações de três minutos e não mede disponibilidade em produção.

## OpenAI

Duas tentativas reais no mesmo primeiro áudio: a rodada inicial e uma chamada diagnóstica. Ambas HTTP 429. A segunda retornou código `credit_balance_exhausted`, tipo `insufficient_quota`; ver [diagnóstico sanitizado](diagnostico-openai.json). Nenhuma transcrição OpenAI foi recebida. O usuário precisa ajustar crédito/quota no painel da API para prosseguir; não houve compra de créditos nem contratação nesta sessão.

## Decisão

Manter ADR-007 proposto e sem vencedor. Antes de aceitar, corrigir/conferir referências dos áudios, completar cobertura, obter respostas do segundo candidato, revisar elementos e testar E1. Se as divergências críticas se confirmarem e nenhum candidato cumprir o critério, encaminhar à PO a revisão obrigatória da transcrição ou outra mudança de escopo. Não introduzir conversão de números ou correção automática de transcrições.

Verificação offline reexecutada: nove autotestes e onze testes de manifesto/agregação passaram; `git diff --check` passou. Não houve execução de E1, gate Java, gravação humana adicional ou verificação visual da página auxiliar de captura.
