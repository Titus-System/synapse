# Contratos de domínio

Formato das estruturas JSON que o Synapse persiste em colunas `jsonb`. Estes schemas são a autoridade sobre o formato: a nota da coluna em [`docs/database/modelo-dados.dbml`](../../docs/database/modelo-dados.dbml) aponta para cá, e [`docs/database/modelo-dados.md`](../../docs/database/modelo-dados.md) explica as decisões com exemplos ilustrativos.

Como todo `contracts/`, isto é insumo de build e nunca dependência de runtime. Cada consumidor implementa seus próprios DTOs na sua stack.

## Os dois artefatos que atravessam o sistema

Dois schemas não descrevem uma coluna: descrevem um artefato inteiro, compondo por `$ref` as colunas que só dizem a mesma coisa quando lidas juntas.

| Schema | Artefato |
| --- | --- |
| [representacao-regra.schema.json](representacao-regra.schema.json) | A regra que o usuário confirma e que o código gerado implementa: `regras.nucleo` mais `regras.especificacoes` |
| [resultado-simulacao.schema.json](resultado-simulacao.schema.json) | A saída que o código gerado produz no sandbox: `totais`, `assercoes` e `decomposicao` de `resultados_simulacao` |

A composição existe porque a exigência mora no par, não na parte. A representação só é regra com núcleo e especificações juntos; o resultado só é resultado com totais e decomposição juntos, porque um total sem a quebra não diz de onde veio a diferença nem permite conferir que todo elemento teve efeito. Cada schema de coluna continua valendo isoladamente, para quem lê ou escreve aquela coluna.

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

`outbox_events.payload` não está aqui: é corpo de mensagem, e seu lugar é `contracts/events/`.

Coluna nula não é caso do schema. Quando a nota do DBML diz que a coluna aceita `NULL`, a ausência de valor é decidida lá; o schema descreve o formato de quando existe valor.

## Convenções

Nenhum schema usa `additionalProperties: false`. A evolução é aditiva: campo novo entra opcional, nada é removido nem renomeado sem decisão arquitetural explícita (ADR-002). Fechar o objeto quebraria produtor e consumidor em versões diferentes.

Enums listam o vocabulário conhecido. Acrescentar valor é mudança aditiva e exige atualizar produtor e consumidores na mesma alteração.

Código de loja, marca e cargo é sempre string, na mesma forma em qualquer estrutura. São identificadores, nunca operandos: são comparados por igualdade e usados como chave de objeto, e chave de objeto JSON é string por definição.

Percentual e diferença percentual são fração, nunca porcentagem. `0.025` são 2,5%.

Competência é `AAAA-MM`. As bases só têm granularidade mensal. A única exceção é o construto `janela_datas`, que usa data completa porque a base de vendas de novembro carrega data real.

## Identificação das partes da regra

Campos do núcleo e elementos de `especificacoes` compartilham um espaço único de identificação, definido em `comum.schema.json` como `elemento_ref`. Campo do núcleo usa `nucleo.<campo>`; item de `especificacoes` usa o `ref` dele, sequencial, como `elem.1`.

O espaço é único porque as mesmas listas citam os dois lado a lado: a declaração de cobertura do código gerado e a quebra por elemento em `resultado-decomposicao`. O identificador não carrega o construto, que já tem campo próprio e mudaria se o elemento fosse reclassificado.
