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

## Estado existente e evolução planejada

Os schemas descrevem formatos compartilhados; sua existência não comprova que a extração ou a geração de todos os construtos já esteja implementada.

A decomposição exige cinco mapas de diferenças, que somam `totais.diferenca_abs`: `elemento`, `loja`, `marca`, `cargo` e `competencia`. Admite também três mapas absolutos opcionais, que somam `totais.simulado`: `matricula`, com o total de cada colaborador no período, `loja_absoluto` e `competencia_absoluto`. Os absolutos fazem parte do contrato, mas o harness do worker ainda não os produz. O cruzamento por competência e matrícula é definido separadamente em `resultado-linhas.schema.json`, com loja e marca da lotação no RH. A T-256 define esse contrato; sua produção, persistência e conferência são entregas do worker nas T-259 e T-262.

Os conflitos do chatbot têm formato em `conflitos-rodada.schema.json`, mas a tabela de rodadas ainda não existe no esquema do banco; a migration acompanha a implementação do loop de correção. Os schemas atuais permanecem a autoridade até serem evoluídos e validados com seus consumidores. Ver [Fluxo e decisões da Sprint 2](../../docs/FLUXO-SPRINT-2.md).
