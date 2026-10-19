# Busca da meta de venda — T-273

`BUSCA_META_ENABLED` é `true` por padrão. A API separa `busca_meta` da simulação do job e consome `meta-venda-sugerida` (T-274), e expõe a busca em curso em `busca_meta_em_curso` (T-283). A flag controla a abertura de buscas: desligada, nenhuma busca nova começa, e uma busca já gravada continua pelo seu checkpoint. A apresentação e a aceitação pertencem à API e ao frontend.

## Elegibilidade e algoritmo

O `decision` abre uma busca por versão quando a flag está ligada, a simulação normal terminou com sucesso e veredito viável, a representação não tem especificações e a comissão persistida é estritamente menor que o orçamento do job. A checagem confirma código, regra, propósito e orçamento do resultado. Sem meta, usa `vendas_historicas`; resultados legados sem esse total não abrem uma busca sem ponto de partida. Alternativas de taxa têm o mesmo direito à busca que as versões originais. A candidata aceita não volta ao `decision`, nem começa outro ciclo.

`LIMITE_CANDIDATOS = 12` usa o teto de 60 segundos do sandbox como referência: até 720 segundos de execução de candidatas, além de baseline, fila, gravação e transporte. O caso de referência documentado pelo worker executa em cerca de 1,2 segundo; o teto limita trabalho, não promete latência. O consumidor assenta cada mensagem quando o grafo pausa: não espera as doze execuções dentro de uma única entrega RabbitMQ.

A primeira candidata é `meta × orçamento / comissão`. Com comissão zero, começa no dobro da meta. Enquanto não houver uma meta cuja comissão supere o orçamento, dobra a meta anterior. Encontrado o intervalo, faz bisseção; `TOLERANCIA_RELATIVA = 0.001` encerra quando a distância entre os limites é até 0,1% da meta inferior. Metas candidatas usam a representação decimal do `float` recebido pelo worker, sem arredondamento para centavos: uma margem pequena pode comportar um aumento inferior a um centavo. A comparação de viabilidade sempre usa o total efetivamente gravado pelo worker, sem tolerância sobre o orçamento.

A busca sugere somente uma candidata maior que o ponto de partida, executada com sucesso e dentro do orçamento. Retorna a maior dessas candidatas quando atinge a tolerância ou o limite de execuções com intervalo delimitado. Não afirma um máximo matemático exato. Se não consegue delimitar uma solução maior dentro do limite ou da precisão numérica, publica `intervalo_esgotado`; não oferece a simulação original como se fosse uma meta maior. Qualquer inversão de monotonicidade entre amostras ordenadas por meta, inclusive durante a bisseção, termina com `nao_monotonica`. Uma candidata sem execução bem-sucedida ou sem totais utilizáveis termina com `falha_execucao`.

## Persistência e mensagens

O nó `search_sales_target` escolhe a próxima meta e grava a escolha no checkpoint antes de `dispatch_execution` publicar. O comando conserva código, competências, orçamento e elementos exigidos; recebe a meta candidata e `proposito=busca_meta`. O `await_execution` mantém a pausa existente. Candidatas não repetem os anúncios da delegação da simulação principal, não geram código e não chamam modelo.

O checkpoint conserva as amostras, suas referências, a meta pendente e o desfecho, sem alterar a meta original do job. Na retomada, o codegen lê o resultado e confere job, regra, código, propósito e meta contra a execução pendente. Resultados já processados ou divergentes não avançam o ciclo. Uma falha posterior à gravação do resultado retoma o nó pendente sem escolher outra candidata. Uma trava de sessão PostgreSQL serializa avanços do mesmo ciclo entre conexões e é liberada ao pausar; a conexão pertence à chamada, então uma queda também a libera.

A publicação continua com entrega pelo menos uma vez. Uma queda entre confirmação do broker e checkpoint pode republicar o mesmo comando, cuja identidade o worker já deduplica por job, código, meta e propósito. Também pode repetir o mesmo desfecho; `meta-venda-sugerida` identifica a versão e o mesmo resultado vencedor. A conclusão de auditoria usa `no=decisao`, resumo específico e UUIDv5 de job, regra e busca, distinto da decisão inicial. Nenhum contrato público é ampliado.

Antes de despachar outra candidata ou publicar a sugestão, o fluxo consulta o registro de encerramento. Se o job foi encerrado, termina a busca sem novo comando ou sugestão. O mecanismo existente de limpeza remove seus checkpoints quando o processamento pendente termina.

## Observabilidade e verificação

Logs de início, publicação de candidata, recebimento de resultado, descarte, cancelamento, falha e conclusão usam mensagens estáveis. O consumidor estabelece `job_id`; os nós usam `no=search_sales_target` e restauram o contexto. Só referências, contagem de candidatas, operação e motivos sanitizados são registrados; não há valores financeiros, representação ou código.

| Métrica | O que mede |
| --- | --- |
| `codegen_busca_meta_total{desfecho,motivo}` | Publicações de desfecho ou cancelamento, com conjuntos fechados |
| `codegen_busca_meta_candidatos` | Quantidade de candidatas nas buscas concluídas |
| `codegen_busca_meta_espera_seconds` | Tempo entre envio e processamento do resultado, incluindo fila e worker |
| `codegen_busca_meta_processamento_seconds` | Processamento ativo de avaliação e publicação final, inclusive quando falha |

Reentregas já assentadas não repetem as observações. As medidas não são um registro transacional de jobs únicos: uma queda antes do checkpoint pode repetir a publicação e sua observação. A duração de espera não é tempo de CPU do worker; não substitui a instrumentação dele.

Os testes do grafo usam os nós e produtores reais, substituindo banco e transporte. A integração usa PostgreSQL descartável com as migrations da API, usuário do codegen, `AsyncPostgresSaver` e RabbitMQ real em vhost exclusivo; o teste representa somente o worker, persistindo seus resultados antes de publicá-los. Não executa a regra no sandbox. Confere sucesso, os três motivos de ausência de solução, duplicatas antigas, contratos, métricas em `/metrics` e duas retomadas concorrentes. Os testes também validam logs serializados contra o schema e restauram o contexto entre jobs.

Comandos no diretório `codegen`:

```sh
make graph
make pre-commit
RUN_RABBITMQ_INTEGRATION=1 RUN_POSTGRES_INTEGRATION=1 make test-rabbitmq
```

O gate pode chamar o provedor nos testes existentes marcados `llm` se houver uma chave configurada. A busca é determinística e seus testes não precisam dessa chave. O relatório de validação deve distinguir esses testes opcionais, a integração simulando o worker e uma execução completa com sandbox.
