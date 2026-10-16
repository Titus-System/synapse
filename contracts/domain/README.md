# Contratos de domínio

Formato das estruturas JSON que o Synapse persiste em colunas `jsonb`. Estes schemas são a autoridade sobre o formato: a nota da coluna em [`docs/database/modelo-dados.dbml`](../../docs/database/modelo-dados.dbml) aponta para cá, e [`docs/database/modelo-dados.md`](../../docs/database/modelo-dados.md) explica as decisões com exemplos ilustrativos.

Como todo `contracts/`, isto é insumo de build e nunca dependência de runtime. Cada consumidor implementa seus próprios DTOs na sua stack.

## Os dois artefatos que atravessam o sistema

Dois schemas não descrevem uma coluna: descrevem um artefato inteiro, compondo por `$ref` as colunas que só dizem a mesma coisa quando lidas juntas.

| Schema | Artefato |
| --- | --- |
| [representacao-regra.schema.json](representacao-regra.schema.json) | A regra estruturada que é validada e que o código gerado deve implementar: `regras.nucleo` mais `regras.especificacoes` |
| [resultado-simulacao.schema.json](resultado-simulacao.schema.json) | A saída que o código gerado produz no sandbox: `totais`, `assercoes` e `decomposicao` de `resultados_simulacao` |

A composição existe porque a exigência mora no par, não na parte. A representação só é regra com núcleo e especificações juntos; a saída de sucesso reúne totais e decomposição. A quebra permite conferir cobertura e conciliação, mas não prova sozinha a correção semântica de cada elemento nem preserva todas as linhas da apuração. Cada schema de coluna continua valendo isoladamente, para quem lê ou escreve aquela coluna.

Os exemplos válidos estão em [`contracts/examples/domain/`](../examples/domain/), e é o que os testes de cada componente consomem.

## Schemas e colunas

| Schema | Coluna |
| --- | --- |
| [comum.schema.json](comum.schema.json) | nenhuma; definições reutilizadas pelos demais |
| [submissao-conteudo.schema.json](submissao-conteudo.schema.json) | `submissoes.conteudo` |
| [regra-nucleo.schema.json](regra-nucleo.schema.json) | `regras.nucleo` |
| [regra-especificacoes.schema.json](regra-especificacoes.schema.json) | `regras.especificacoes` |
| [trilha-conclusao.schema.json](trilha-conclusao.schema.json) | `trilhas_auditoria.conclusao` |
| [modelo-llm.schema.json](modelo-llm.schema.json) | `prompts.modelo` |
| [consumo-tokens.schema.json](consumo-tokens.schema.json) | `respostas_modelo.consumo_tokens` |
| [resultado-totais.schema.json](resultado-totais.schema.json) | `resultados_simulacao.totais` |
| [resultado-assercoes.schema.json](resultado-assercoes.schema.json) | `resultados_simulacao.assercoes` |
| [resultado-decomposicao.schema.json](resultado-decomposicao.schema.json) | `resultados_simulacao.decomposicao` |
| [resultado-linhas.schema.json](resultado-linhas.schema.json) | `resultados_simulacao.linhas`, consultado pela rota de detalhamento |
| [resultado-diagnostico.schema.json](resultado-diagnostico.schema.json) | `resultados_simulacao.diagnostico` |
| [conflitos-rodada.schema.json](conflitos-rodada.schema.json) | `rodadas_correcao.conflitos`, também usado em `etapa-alterada` e na API HTTP |
| [parametros-simulacao.schema.json](parametros-simulacao.schema.json) | `extracoes_regras.parametros` e `regras.parametros`, também usado em `correcao-proposta` |

`outbox_events.payload` não está aqui: é corpo de mensagem, e seu lugar é `contracts/events/`.

Coluna nula não é caso do schema. Quando a nota do DBML diz que a coluna aceita `NULL`, a ausência de valor é decidida lá; o schema descreve o formato de quando existe valor.

## Convenções

Nenhum schema usa `additionalProperties: false`. A evolução é aditiva: campo novo entra opcional, nada é removido nem renomeado sem decisão arquitetural explícita (ADR-002). Fechar o objeto quebraria produtor e consumidor em versões diferentes.

Enums listam o vocabulário conhecido. Acrescentar valor é mudança aditiva e exige atualizar produtor e consumidores na mesma alteração.

Código de loja, marca e cargo é sempre string, na mesma forma em qualquer estrutura. São identificadores, nunca operandos: são comparados por igualdade e usados como chave de objeto, e chave de objeto JSON é string por definição.

Percentual e diferença percentual são fração, nunca porcentagem. `0.025` são 2,5%.

Competência é `AAAA-MM`. As vendas têm granularidade mensal, com exceção das datas reais da janela de Black Friday em novembro. Admissão e demissão também têm datas completas no RH. `janela_datas` usa data completa para os recortes que os dados efetivamente sustentam.

## Identificação das partes da regra

Campos do núcleo e elementos de `especificacoes` compartilham um espaço único de identificação, definido em `comum.schema.json` como `elemento_ref`. Campo do núcleo usa `nucleo.<campo>`; item de `especificacoes` usa o `ref` dele, sequencial, como `elem.1`.

O espaço é único porque as mesmas listas citam os dois lado a lado: a declaração de cobertura do código gerado e a quebra por elemento em `resultado-decomposicao`. O identificador não carrega o construto, que já tem campo próprio e mudaria se o elemento fosse reclassificado.

Os parâmetros da simulação (orçamento, meta de venda e período) não fazem parte da regra nem desse espaço. Um conflito ou um rebaixamento que os cita usa `parametros.orcamento`, `parametros.meta_venda` ou `parametros.competencias`. Essas referências são aceitas só em `conflitos-rodada.schema.json` e em `rebaixamentos-extracao.schema.json`, para que a cobertura declarada pelo código gerado e a quebra por elemento continuem restritas às partes da regra.

## Estado existente e evolução planejada

Os schemas descrevem formatos compartilhados; sua existência não comprova que a extração ou a geração de todos os construtos já esteja implementada.

A decomposição exige cinco mapas de diferenças, que somam `totais.diferenca_abs`: `elemento`, `loja`, `marca`, `cargo` e `competencia`. Admite também três mapas absolutos opcionais, que somam `totais.simulado`: `matricula`, com o total de cada colaborador no período, `loja_absoluto` e `competencia_absoluto`. Os absolutos fazem parte do contrato, e o harness do worker os produz desde a T-259. O cruzamento por competência e matrícula é definido separadamente em `resultado-linhas.schema.json`, com loja e marca da lotação no RH. A T-256 define esse contrato; a T-259 entregou a produção, no harness, e a persistência, em `resultados_simulacao.linhas`, e a conferência dos valores contra os totais e as quebras é da T-262.

Os conflitos do chatbot têm formato em `conflitos-rodada.schema.json`, mas a tabela de rodadas ainda não existe no esquema do banco; a migration acompanha a implementação do loop de correção. Os schemas atuais permanecem a autoridade até serem evoluídos e validados com seus consumidores. Ver [Fluxo e decisões da Sprint 2](../../docs/FLUXO-SPRINT-2.md).

## Compatibilidade dos parâmetros da simulação (T-277)

O formato único está em `parametros-simulacao.schema.json`. `correcao-proposta.parametros` referencia o objeto inteiro; `regra-submetida`, `parametros-confirmados` e `correcao-submetida` referenciam suas propriedades, mantendo os campos no nível atual do evento. Ausência e `null` são distintos: os campos conhecidos aceitam ausência, mas não `null`.

| Campo ou contrato | Evolução e compatibilidade |
| --- | --- |
| `POST /submissoes` inicial: `orcamento` | Deixa de ser obrigatório, fica obsoleto e é ignorado. Qualquer valor JSON é aceito nesse campo, sem efeito, tanto no JSON de texto quanto na parte `parametros` do multipart. |
| `POST /submissoes` inicial: `competencias` | Continua opcional, fica obsoleto e é ignorado sem validar sua forma. Requisições antigas continuam válidas; os valores efetivos vêm só da descrição. |
| `parametros-simulacao.orcamento` e `meta_venda` | Números em reais, opcionais e sem `minimum`/`exclusiveMinimum`. Aceitam orçamento negativo e meta zero ou negativa para a validação apontar conflitos. |
| `parametros-simulacao.competencias` | Lista opcional, não vazia, de `AAAA-MM`, sem enum dos meses publicados. Um mês fora das publicadas chega à validação. O schema não aplica o período padrão. |
| `regra-submetida.orcamento` e `parametros-confirmados.orcamento` | Continuam opcionais; perde-se apenas `minimum: 0`. Números anteriormente válidos continuam válidos; strings, booleanos e `null` continuam recusados. |
| `regra-submetida.meta_venda` e `parametros-confirmados.meta_venda` | Campos novos opcionais. `competencias` permanece obrigatória no primeiro evento e opcional no segundo, com o mesmo formato anterior. |
| `correcao-submetida.orcamento` e `meta_venda` | Campos novos opcionais com os valores atuais do job; `competencias` permanece opcional. Mensagens anteriores continuam válidas. |
| `correcao-proposta.parametros` | Objeto novo opcional com o conjunto completo após a correção. Ausente, preserva os parâmetros do job; `{}` remove orçamento/meta e restaura todas as competências publicadas. Campo omitido dentro do objeto significa parâmetro não definido após a correção. |
| `JobResumo` e `JobDetalhado` | `orcamento` deixa de ser obrigatório; `meta_venda` é opcional. A ausência é omissão, não `null`. Clientes que presumiam orçamento presente precisam aceitar a omissão; o tipo `Job` do frontend acompanha essa mudança. |
| `conflitos-rodada.elementos` e `rebaixamentos-extracao.ref` | Aceitam as três referências `parametros.<campo>` além das referências anteriores. Por decisão autorizada, `comum.elemento_ref` permanece restrito às partes da regra. |
| `rebaixamentos-extracao.motivo` | Acrescenta `valor_sem_lastro`, `codigo_fora_do_vocabulario`, `termo_ambiguo` e `periodo_nao_resolvido`; os dois motivos anteriores continuam válidos. |
| `jobs` no DBML | `orcamento` passa a nullable; `meta_venda` é nova e nullable. `competencias` mantém o período padrão até a extração. A migration é da T-279. |
| `extracoes_regras.parametros` e `regras.parametros` | A primeira tem padrão `{}` para aceitar produtores anteriores; a segunda é nullable, preservando a serialização e o hash anteriores quando nula. Objetos presentes, inclusive `{}`, entram no hash da versão. |

A ampliação do contrato não torna automaticamente um consumidor antigo compatível com valores novos. O codegen ainda exige orçamento não negativo nos DTOs e no estado; a T-280 precisa ajustar esses pontos antes de ativar na T-279 a republicação de valores inválidos. A extração é da T-278, e a correção, das T-220/T-217. `POST /jobs` e o schema de resposta `Job` mantêm o contrato anterior. A execução e os resultados sem orçamento, além da meta na execução, são tratados pela T-269, integrada depois desta tarefa.

## Compatibilidade da simulação na meta e das sugestões (T-269)

A simulação passa a poder ser feita na meta de venda e sem orçamento, e o resultado na meta gera uma de duas sugestões: uma taxa nova, em até três tentativas, quando a comissão passa do orçamento, ou uma meta maior, quando fica abaixo dele. Nenhum campo existente muda de nome ou tipo. Os campos novos são opcionais, e a ausência de `meta_venda` e de `proposito` reproduz o comportamento anterior.

| Campo ou contrato | Evolução e compatibilidade |
| --- | --- |
| `executar-codigo.orcamento` | Deixa de ser obrigatório. Ausente, a simulação é feita sem a verificação de orçamento. Comandos anteriores continuam válidos. O codegen só publica o comando sem orçamento depois de o worker aceitá-lo (T-281, T-272). |
| `executar-codigo.meta_venda` | Campo novo opcional, `brl` estritamente positivo. É a definição única: `simulacao-concluida` e `meta-venda-sugerida` a referenciam. O payload do container ganha o mesmo campo (`contracts/harness/README.md`), e, como o executor recusa campo desconhecido, worker e imagem do sandbox mudam juntos (T-270). |
| `executar-codigo.proposito` | Campo novo opcional, `simulacao` ou `busca_meta`; ausente equivale a `simulacao`. Não entra no payload do container. |
| `resultado-totais.orcamento` | Deixa de ser obrigatório. Ausente quando o comando não trouxe orçamento. Resultados anteriores continuam válidos. Quem lia o campo como sempre presente precisa aceitar a omissão. |
| `resultado-totais.vendas_historicas` | Campo novo opcional: total de vendas das competências antes do escalonamento, acrescentado pelo worker fora do container. Ausente nos resultados anteriores. |
| `resultado-totais.baseline` e `simulado` | Mesmo nome e tipo. Com meta, são os valores apurados sobre as vendas escaladas até a meta. |
| `simulacao-concluida.veredito` | Pode faltar num `sucesso` sem orçamento. Até a T-281, a api lê esse par como desfecho desconhecido (`DesfechoDaSimulacao.de`), e por isso o worker só o publica depois de o PR da api da T-281 ser integrado. |
| `simulacao-concluida.meta_venda` e `proposito` | Campos novos opcionais, por referência a `executar-codigo`. Um consumidor que ignore `proposito` trataria uma execução candidata como desfecho do job: o filtro da api (T-274) entra antes de o codegen publicar candidatas (T-273). |
| `meta-venda-sugerida` | Evento novo, do codegen para a api, em fila simples de mesmo nome. Leva `job_id`, `regra_id` e exatamente uma de duas formas: `meta_venda` com `resultado_id`, ou `sem_solucao` com `motivo` (`nao_monotonica`, `intervalo_esgotado` ou `falha_execucao`). |
| `sugestao-adaptacao-proposta.tentativa` | Campo novo opcional, inteiro de 1 a 3. Ausente nas propostas anteriores, que eram tentativa única. |
| `etapa-alterada.status` | O vocabulário continua aberto. `sem_alternativa` na etapa `sugestao_adaptacao` encerra as tentativas de taxa nova sem uma taxa que caiba. |
| `resultados_simulacao` no DBML | `meta_venda` nova e nullable; `proposito` nova, `not null` com padrão `simulacao`, que cobre as linhas anteriores sem backfill. `veredito` nulo também num sucesso sem orçamento. A migration é da T-281. |
| `job_acoes.acao` e `AcaoJob` | Acrescentam `aceitar_meta`. Os quatro valores anteriores não mudam. |
| `JobDetalhado` e `Simulacao` | `meta_sugerida` e `Simulacao.meta_venda` são opcionais. `simulacao` passa a ser a simulação vigente: a mais recente do job ou, depois de `aceitar_meta`, a da meta sugerida. `simulacoes` não lista execução candidata que não foi aceita. `veredito` também falta num sucesso sem orçamento. |
| Evento SSE `etapa` | Sem forma nova. Na etapa `sugestao_adaptacao`, a api emite `meta_sugerida` ou `sem_solucao` ao registrar `meta-venda-sugerida`, e repassa `sem_alternativa` do codegen. |

O contrato da função gerada não muda. O payload do container e a execução na meta ficam em seções de `contracts/harness/README.md` que não alimentam `codegen/app/prompts/regrafn.md`: a função gerada recebe `bases["vendas"]` e `apuracao_base` já escalados, no mesmo formato. O prompt de geração embute `resultado-totais.schema.json` inteiro, e por isso passa a levar `orcamento` opcional, `vendas_historicas` e as descrições dos totais na meta. A função gerada não produz totais, e o que ela recebe e devolve continua o mesmo. A implementação é das T-270 a T-276 e da T-281.
