# Modelagem do banco de dados

* Este arquivo possui os motivos das decisões de modelagem e um explicação com exemplos dos conceitos mais propensos a gerar confusão.

* Não há aqui detalhamento extensivo das regras de negócio da aplicação, apenas o suficiente para entender a modelagem de dados.

* As US-05 e US-04 orientam a modelagem e exigem auditabilidade e explicabilidade do sistema.

O arquivo [`modelo-dados.dbml`](modelo-dados.dbml) é a fonte canônica e define tabelas, colunas, tipos, nulidade, chaves e índices; as convenções do esquema estão no cabeçalho dele. Se os dois divergirem, vale o DBML.

O formato das colunas `jsonb` é definido pelos schemas em [`contracts/domain/`](../../contracts/domain/), que dizem quais chaves são obrigatórias, que tipo cada uma tem e que valores aceita. Os exemplos deste documento são ilustrativos e servem para leitura; o que vale para implementar é o schema.

O esquema abaixo é o existente. As extensões aprovadas para a Sprint 2 estão na seção 6 e em [Fluxo e decisões da Sprint 2](../FLUXO-SPRINT-2.md); não são tabelas ou colunas já disponíveis.

## 1. As tabelas

São catorze, num schema único. Cada uma aparece abaixo com o que guarda e, quando tem coluna `jsonb` ou array, com um exemplo do conteúdo dela, porque é ali que mora a maior chance de confusão.

### `usuarios`

A identidade é autenticada pelo Keycloak, conforme o [ADR-006](../adrs/ADR-006.md). A API mantém esta conta local para relacionar o usuário às submissões, aos jobs e à trilha de auditoria.

#### Identidade e restrições

- `id` é a identidade local referenciada por `submissoes.usuario_id` e `jobs.usuario_id`. O vínculo ao Keycloak preserva esse identificador e a posse dos dados.
- `login` é obrigatório e único pelo índice `uq_usuarios_login`. No provisionamento, a API usa `preferred_username`, com fallback para `sub` quando o claim está ausente ou vazio.
- `keycloak_sub` é um `text` nullable que armazena o claim `sub`, identificador estável da conta no Keycloak. `NULL` indica uma conta local sem vínculo ao provedor.
- `uq_usuarios_keycloak_sub` é um índice único parcial com `WHERE keycloak_sub IS NOT NULL`: um mesmo `sub` identifica no máximo uma conta local, e várias contas sem vínculo podem ter `NULL`. O DBML registra o predicado na nota do índice.
- `senha_hash` é uma credencial local opcional, não utilizada na autenticação OIDC. A API insere `NULL` ao provisionar uma conta pelo Keycloak; as senhas são geridas pelo provedor.

#### Provisionamento e autorização

Antes de consultar ou escrever a conta, a API exige exatamente um papel de negócio conhecido em `realm_access.roles`: `profissional-rh` ou `auditor`. Nenhum deles, ou ambos, resulta em 403; papéis técnicos adicionais são ignorados. A API procura primeiro a conta pelo `sub`; se não houver vínculo, procura uma conta com `keycloak_sub` nulo e o mesmo `login` resolvido do token. Ao encontrar uma conta ativa, preenche `keycloak_sub` e atualiza `nome` e `ultimo_login_em`. Se não encontrar uma conta, cria uma com papel local correspondente (`profissional_rh` ou `auditor`). O papel do token rege a autorização em produção; contas existentes não têm a coluna `papel` sincronizada no login. No modo de desenvolvimento sem Keycloak, a API usa o primeiro usuário ativo e lê seu papel local canônico.

Usuário desativado mantém a linha porque jobs antigos a referenciam. `ativo = false` impede a resolução dessa conta local pela API, mas não encerra a sessão no Keycloak. As operações de jobs seguem a matriz da DEC-087 e conferem a posse por `jobs.usuario_id`, conforme o ADR-006.

### `submissoes`

Uma linha por envio do usuário, com o conteúdo como ele chegou e antes de qualquer processamento. A coluna `tipo` diz se veio de formulário ou de voz e determina qual carga está preenchida: o formulário ocupa `conteudo`, a voz ocupa `binario` e `formato`, e o texto transcrito é gravado na mesma linha quando fica pronto.

A coluna `conteudo` tem duas chaves, `nucleo` e `texto_livre`, e o núcleo traz seus cinco campos.

```json
{
  "nucleo": {
    "vigencia":   { "inicio": "2025-11", "fim": "2025-11" },
    "loja":       ["13"],
    "marca":      ["10"],
    "cargo":      ["100"],
    "percentual": 0.03
  },
  "texto_livre": null
}
```

O núcleo tem esses cinco campos e nenhum outro. Matrícula não está entre eles, aqui nem em `regras.nucleo`, pelo motivo da seção 3; quando a regra precisa mirar pessoas, isso entra em `regras.especificacoes`.

As outras quatro colunas cobrem a submissão por voz. `binario` guarda os bytes do áudio. `formato` diz a extensão do arquivo, com valores como `webm`, `ogg` ou `wav`.

`conteudo` de um lado e `binario` mais `formato` do outro são mutuamente exclusivos, e `tipo` diz qual par está preenchido.

Guardar o binário na mesma linha não pesa as leituras que não pedem a coluna. O PostgreSQL move valores grandes para armazenamento externo por TOAST e só os busca quando a coluna é selecionada, de modo que consultar `tipo` ou `criado_em` não arrasta o áudio junto.


### `jobs`

O processamento de uma submissão do início ao fim. O `id` desta tabela é a chave de correlação que reaparece em quase todas as outras e em todos os eventos do RabbitMQ.

A coluna `competencias` é um array de texto com os meses a simular.

```
["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
```

O job cobre o período inteiro em uma simulação, com os meses agregados. Qualquer subconjunto das cinco competências canônicas de agosto a dezembro de 2025 é válido, contíguo ou não, e a lista nunca fica vazia. A forma canônica é ordem crescente sem repetição. Competência usa `AAAA-MM`; datas diárias de vendas existem somente na particularidade de novembro/Black Friday.

A procedência é `submissao_id` ou `job_origem_id`, nunca as duas. É dela que se deduz o ponto de entrada no grafo, sem precisar de coluna dedicada.

### `regras`

A representação estruturada da regra, armazenada em `nucleo` e `especificacoes`. O fluxo atual de formulário gera versões com especificações vazias. Na Sprint 2, extração e reextração produzem a regra completa; validação sem problemas permite geração automática, enquanto problemas acionam o chatbot.

```json
{
  "vigencia":   { "inicio": "2025-11", "fim": "2025-11" },
  "loja":       ["13"],
  "marca":      ["10", "20"],
  "cargo":      ["100", "300"],
  "percentual": 0.025
}
```

São esses cinco campos e nenhum outro, no vocabulário da DEC-084. Matrícula não é um deles, e a seção 3 explica por quê. `percentual` é fração e não porcentagem, então `0.025` são 2,5%. `vigencia` usa `AAAA-MM` pelo mesmo motivo que `competencias`. Chave ausente é situação válida: sem `vigencia`, a regra vale para todas as competências do job.

`especificacoes` é um array, vazio quando a regra é só o núcleo.

```json
[
  { "ref": "elem.1", "construto": "faixa_valor",
    "limite_inferior": 40000, "limite_superior": 50000,
    "efeito": { "tipo": "bonus_fixo", "valor": 3500 } },

  { "ref": "elem.2", "construto": "exclusao",
    "dimensao": "cargo", "valores": ["150"] },

  { "ref": "elem.3", "construto": "generico",
    "descricao": "dobrar a comissão no aniversário da loja",
    "campos": { "evento": "aniversario_loja" } }
]
```

Todo item tem a mesma anatomia: `ref` identifica, `construto` diz de que forma o elemento é, e o resto são os campos que aquela forma exige. Sem o construto não há como validar, porque é ele que diz que `elem.1` é uma faixa e portanto precisa de limite superior. Elemento que não corresponde a nenhuma forma conhecida entra como `generico`. A ordem do array é a ordem de exibição dos elementos da regra.

#### Identificação das partes da regra

Cada parte da regra tem um identificador estável dentro da versão. Campo do núcleo usa o nome do campo prefixado, como `nucleo.percentual`. Item de `especificacoes` usa o `ref` dele, atribuído sequencialmente na criação: `elem.1`, `elem.2`.

Os dois formam um espaço único porque as mesmas listas citam campos do núcleo e elementos lado a lado. É por esses identificadores que o código gerado declara o que implementa, que a cobertura é conferida, e que `resultados_simulacao.decomposicao` chaveia a quebra por elemento.

O identificador não carrega o construto. `elem.faixa.1` duplicaria informação que já tem campo próprio e quebraria se o elemento fosse reclassificado.

#### Imutabilidade

Uma versão já usada por um resultado nunca é alterada. Edição na confirmação, alternativa da adaptação e reprocessamento geram versão nova, com `versao` incrementado e `regra_origem_id` registrando de onde ela derivou.

O que garante isso não é disciplina de código: nenhum usuário de banco tem `UPDATE` ou `DELETE` nesta tabela. O par `(job_id, hash)` é único, o que impede a mesma regra entrar duas vezes como versões diferentes.

### `job_transicoes`

Uma linha por mudança de status do job. É a trilha da máquina de estados da API, diferente da trilha por nó do grafo. Só recebe `INSERT`. `motivo` guarda o código da razão; a API o traduz para a mensagem exibida. A exposição consistente desse motivo em consulta e SSE é parte da T-201.

### `job_acoes`

As ações de finalização que o usuário dispara sobre um job. Junto com `jobs`, é o que sustenta a tela de histórico, e por isso não existe tabela de histórico separada.

### `simulacoes`

Um ciclo de backtest. A linha amarra o id da simulação, o timestamp, a versão exata da regra e o código exato executado, e passa a apontar o resultado quando ele chega. Um job tem mais de uma quando passa pelo laço de adaptação.

A coluna `codigo_gerado_id` existe porque uma mesma versão da regra pode ser traduzida em código mais de uma vez. Sem ela, o caminho de volta do resultado para a simulação passaria por `regras` e encontraria duas respostas.

### `trilhas_auditoria`

Uma linha por nó do grafo concluído, montada pela API a partir do evento que o codegen publica ao terminar cada nó. As colunas de referência apontam o prompt, o código e a explicação produzidos naquele nó.

A coluna `conclusao` guarda o que o nó concluiu, e a forma muda de nó para nó.

```json
{ "resumo": "5 elementos extraídos da transcrição",
  "elementos_extraidos": ["nucleo.percentual", "elem.1"] }
```

```json
{ "resumo": "usuário corrigiu o percentual antes de confirmar",
  "editado_pelo_usuario": true,
  "campos_corrigidos": ["nucleo.percentual"] }
```

```json
{ "resumo": "diferença concentrada em duas lojas",
  "diagnostico": "a faixa de bônus respondeu por 30% do acréscimo",
  "concentracao": ["13", "elem.1"] }
```

Só `resumo` é comum aos três. Achatar essa variação em colunas produziria dezenas delas quase sempre nulas. O objeto não repete o que a linha já alcança: o nome do nó está na coluna `no`, o veredito em `resultados_simulacao` e a razão de uma parada em `job_transicoes.motivo`.

A coluna `evento_id` é a chave de idempotência, com índice único. O codegen usa UUIDv5 derivado do job, nó e referência do artefato em `id_do_evento_de_trilha`. Reentregas e republicações do mesmo evento lógico conservam a identidade; a API grava o identificador recebido e evita duplicação da trilha.

### `prompts`

O texto enviado ao modelo numa chamada. Fica em tabela própria para textos longos não pesarem as consultas de rotina.

A coluna `modelo` guarda os metadados do provedor, e este é o único lugar onde eles são gravados.

```json
{ "provedor": "openai", "modelo": "gpt-4.1", "versao": "2025-04-14",
  "parametros": { "temperature": 0, "top_p": 1, "seed": 42 } }
```

`parametros` não vira colunas tipadas porque o conjunto varia entre provedores. O que precisa sobreviver é poder dizer, meses depois, com qual modelo e quais parâmetros um texto foi gerado, mesmo que o provedor tenha trocado o modelo por baixo.

### `respostas_modelo`

A resposta do modelo, verbatim, sem extração nem limpeza. Uma linha por prompt, e o nó que originou a chamada é lido em `prompts`.

A coluna `consumo_tokens` fica nula quando o provedor não devolve essa informação.

```json
{ "tokens_in": 3120, "tokens_out": 480, "custo_usd": 0.0212 }
```

### `codigos_gerados`

O código Python executável, já extraído da resposta do modelo. A linha aponta a versão da regra que ele traduz e o prompt que o produziu. É o que o worker lê para executar.

### `explicacoes`

A narrativa em linguagem de negócio sobre o que a simulação mostrou, uma por resultado. A coluna `aderencia_conferida` registra se os números citados no texto batem com o que foi apurado, e é falsa quando algum não bate.

### `resultados_simulacao`

O artefato produzido pela execução e pela verificação do worker, persistido com `INSERT` e sem alteração posterior. No sucesso, contém totais, asserções e decomposição. Falha de execução ou asserção violada não produz valores financeiros válidos. O diagnóstico persistente das falhas é uma extensão ainda prevista nas T-202–T-204.

A coluna `totais` traz os agregados do período inteiro, somando todas as competências do job, e é nula quando `status` não é `sucesso`.

```json
{ "baseline": 480312.00, "simulado": 492100.00,
  "diferenca_abs": 11788.00, "diferenca_pct": 0.0245,
  "orcamento": 485000.00 }
```

Os valores são em reais, com exceção de `diferenca_pct`, que é fração. O orçamento aparece aqui embora também exista em `jobs.orcamento`: como esta tabela só aceita `INSERT`, guardar o critério junto do veredito impede que o parâmetro que produziu aquele julgamento seja alterado depois.

A coluna `assercoes` tem o desfecho de cada invariante verificada dentro do sandbox, e fica vazia quando o erro foi de infraestrutura e nada chegou a rodar.

```json
[
  { "nome": "sem_comissao_negativa",                 "resultado": "ok",      "detalhe": null },
  { "nome": "sem_comissao_sem_venda",                "resultado": "ok",      "detalhe": null },
  { "nome": "soma_loja_igual_soma_matricula",        "resultado": "ok",      "detalhe": null },
  { "nome": "sem_regras_competencia_igual_baseline", "resultado": "violada", "detalhe": "2025-11, loja 5: delta R$ 12,30" }
]
```

Uma entrada por asserção, sempre sobre o período agregado; violação concentrada num mês vai no `detalhe` em vez de virar entrada separada. Asserção violada invalida o número apurado, e o resultado entra com `status = assercao_violada`, sem `veredito` e sem `totais`. Isso é diferente de `veredito = inviavel`, que é regra coerente cujo custo não cabe no orçamento.

A coluna `decomposicao` traz a quebra da diferença em relação ao baseline, com um objeto por dimensão de quebra mapeando chave para valor em reais.

```json
{ "elemento":    { "nucleo.percentual": 8200.00, "elem.1": 3588.00 },
  "loja":        { "13": 7100.00, "58": 4688.00 },
  "marca":       { "10": 11788.00 },
  "cargo":       { "100": 9200.00, "150": 2588.00 },
  "competencia": { "2025-08": 0, "2025-11": 11788.00 } }
```

São sempre diferença, nunca total: somar qualquer quebra dá `totais.diferenca_abs`. As duas lojas fecham em 11.788,00, e o mesmo vale para marca, cargo e competência.

Zero e ausência dizem coisas diferentes. `2025-08` com zero é um mês que foi simulado e que a regra não afetou. Um elemento com efeito zero permanece representado com zero; ausência de elemento exigido é falha de cobertura, não resultado parcial aceitável.

As chaves de `elemento` são os identificadores definidos em `regras`. Essas quebras são mapas independentes de diferenças: não incluem matrícula, não preservam os dataframes da apuração e não permitem reconstruir linhas de colaborador × loja × competência. A extensão com valores absolutos e o detalhamento estão previstos na Sprint 2.

### `outbox_events`

A fila de saída transacional da API. A linha do evento e a mudança de estado que o motivou entram na mesma transação, e um poller lê os pendentes, publica no RabbitMQ e marca como enviados. Nenhum outro serviço acessa esta tabela.

A coluna `payload` é o corpo do evento, carregando referências e nunca o conteúdo de um artefato.

```json
{ "job_id": "b3f1…", "submissao_id": "9ac2…", "origem": "formulario",
  "competencias": ["2025-08", "2025-11"], "regra_id": "77de…",
  "orcamento": 485000.00 }
```

`origem` e `competencias` viajam como valor mesmo existindo no banco, porque nem codegen nem worker têm permissão em `jobs`: o `job_id` é chave de correlação e não ponteiro que o consumidor consiga seguir. O formato é definido pelo schema da mensagem em `contracts/events/`. `orcamento` é opcional no evento por compatibilidade aditiva e já é enviado pela API.

## 2. Quem escreve o quê

A API escreve `usuarios`, `submissoes`, `jobs`, `job_transicoes`, `job_acoes`, `simulacoes`, `trilhas_auditoria` e `outbox_events`. O codegen insere `prompts`, `respostas_modelo`, `codigos_gerados` e `explicacoes`. O worker insere só `resultados_simulacao`.

`regras` permite inserção pela API e pelo codegen. O fluxo implementado usa a API para versões submetidas, confirmadas ou propostas na adaptação; a extração inicial pelo codegen ainda precisa ser construída. Nenhum dos dois tem `UPDATE` ou `DELETE`: editar significa inserir uma versão nova encadeada por `regra_origem_id`.

O que impõe isso é a permissão do usuário de banco com que cada serviço conecta, definida nas migrations e portanto ausente do DBML. Quem insere também recebe `SELECT` na mesma tabela, porque o id nasce de `DEFAULT uuidv7()` no servidor e o `INSERT` o lê de volta no próprio comando.

Daí uma aparente contradição no esquema: `resultados_simulacao.job_id` é chave estrangeira para `jobs`, tabela em que o worker não tem permissão alguma. O `INSERT` funciona porque, no PostgreSQL, a verificação de integridade referencial roda com os privilégios do dono da tabela referenciada e não com os de quem inseriu a linha.

## 3. Decisões de modelagem

### Quando `jsonb` e quando tabela

Forma uniforme com consulta filtrada vira tabela. Objeto escrito de uma vez, lido inteiro e nunca usado como critério de busca vira `jsonb`.

A decomposição mostra o que acontece quando a escolha erra. Ela chegou a ser tabela própria, com colunas `tipo`, `chave`, `dimensao` e `contribuicao`. `dimensao` ficava nula em metade das linhas, `chave` significava identificador de elemento ou valor de dimensão conforme o `tipo`, e o índice único precisava de tratamento especial de nulo. Tudo isso existia para acomodar duas quebras diferentes numa estrutura só; em JSON elas viram duas chaves. Os elementos da regra percorreram o mesmo caminho, de uma tabela `regra_elemento` para dentro de `regras.especificacoes`.

Essas fusões são seguras porque todo `jsonb` aqui é folha: pendura numa linha já identificada por chave e não guarda referência que precise de integridade. A espinha do modelo continua sendo o grafo de chaves estrangeiras.

### Por que Postgres e não um banco de documentos

`simulacoes` é quatro chaves estrangeiras e um booleano. A US-04 exige que um resultado aponte a versão exata da regra que o produziu e que essa versão não possa ser apagada enquanto for referenciada, o que é `ON DELETE RESTRICT`. Num banco de documentos isso não existe: um documento apagado deixa um id pendurado e nada acusa. A imutabilidade da regra é ausência de `UPDATE` e `DELETE` numa tabela específica. Integridade referencial e privilégio por tabela são o que se está comprando, e não é a parte que virou JSON.

### Matrícula fora do núcleo

Os campos do núcleo são filtros de escopo, e loja, marca e cargo são categorias, com conjuntos de códigos pequenos e estáveis. Matrícula identifica uma pessoa, e esse conjunto muda a cada competência por admissões e demissões.

Como campo do núcleo, ela congelaria uma lista de pessoas dentro de uma regra imutável, e essa lista já estaria desatualizada na competência seguinte. Para mirar indivíduos, o lugar é o alvo do construto `bonus_fixo`, onde as matrículas entram como dado. Matrícula continua sendo a granularidade em que o cálculo acontece, mas isso é o nível em que o código agrega e não precisa de representação.

## 4. Como percorrer o esquema

Partindo de um job, chega-se a tudo. A procedência leva a `submissoes` e à entrada crua; `job_transicoes` e `job_acoes` contam o que aconteceu com o estado; `trilhas_auditoria` ordenada por `concluido_em` dá a sequência de nós, com cada linha apontando os artefatos daquele nó; `regras` dá a cadeia de versões por `regra_origem_id`; e `simulacoes` amarra regra, código e resultado.

O caminho inverso, de um resultado até a submissão, são dois saltos: `job_id` até `jobs` e `submissao_id` até `submissoes`. Em job de reprocessamento `submissao_id` é nulo, e o percurso sobe por `job_origem_id` até encontrar o job que tem submissão, o que faz disso uma consulta recursiva e não um join fixo. Há um caminho redundante que serve de conferência, por `codigo_gerado_id` até `codigos_gerados` e daí por `regra_id` até `regras`, que também carrega `job_id`; os dois têm que dar no mesmo job.

No fluxo atual, a entrada e as versões permitem comparar parâmetros. Para o chatbot da Sprint 2, a relação entre versão analisada, conflito, submissão de correção e versão resultante será preservada em uma tabela de rodadas; o esquema existente não registra sozinho essa sequência.

Duas coisas o esquema não reconstrói. Qual simulação foi liberada, porque `job_acoes` registra a ação sem apontar simulação, e num job com várias alternativas isso só se infere pela ordem dos timestamps. E um nó cujo evento se perdeu entre a gravação dos artefatos e a publicação: os artefatos continuam alcançáveis pelo `job_id`, mas a sequência de nós fica com um buraco que nada denuncia.

## 5. Fora do modelo

O dataset e os baselines são estáticos e vivem embutidos na imagem do sandbox, sem versionamento no banco. A consequência aceita é que dois resultados apurados sobre imagens diferentes ficam indistinguíveis.

As tabelas de checkpoint do LangGraph são criadas e migradas pela própria biblioteca, ficam no mesmo schema e só o codegen as acessa. Nenhuma chave estrangeira atravessa essa fronteira, e a correlação usa `thread_id = job_id:regra_id`, com fallback legado por job somente para o mesmo ciclo. A limpeza ainda não foi implementada; checkpoints concluídos participam da deduplicação.

Os `GRANT` que sustentam tanto o isolamento entre serviços quanto a imutabilidade da regra são migration, escritos junto ao changeset que cria cada tabela.

Os enums do DBML são vocabulário documentado e não `CHECK`. Exclusão mútua entre colunas, formato de competência e completude por construto são validados no código de cada stack, com `contracts/` como autoridade compartilhada do vocabulário.

## 6. Extensões aprovadas para a Sprint 2

Esta seção descreve trabalho planejado. As migrations e os schemas correspondentes devem acompanhar a implementação; as estruturas ainda não fazem parte do DBML existente.

### Rodadas de validação e correção

Tabela própria relacionada a `jobs` e à versão de `regras` analisada, com lista de conflitos em `jsonb`, referência à submissão de correção e à versão resultante. `rodada_anterior_id` encadeia as rodadas. Cada correção textual ou de voz é uma submissão separada; não incorpora nem sobrescreve as anteriores.

O histórico completo será consultável. Sair do chatbot preserva o estado do job e a rodada pendente, e não há limite de correções. O SSE não substitui esse armazenamento.

### Nome do job e apresentação como campanha

Uma coluna nullable `jobs.nome` atenderá tanto `JobResumo` quanto `JobDetalhado`. O fallback usa até 50 caracteres da entrada textual inicial ou da transcrição inicial; correções posteriores não alteram a origem. O nome pertence ao job, compartilhado por todas as versões da regra.

Campanha é a apresentação de um job com resultado viável. Não há nova tabela de campanhas nem agrupamento de vários jobs neste escopo. Versões anteriores continuam alcançáveis como histórico.

### Resultados e diagnóstico

E9 acrescenta matrícula e valores absolutos, preservando as quebras atuais de diferença. Preservar os dataframes resultantes também faz parte do planejamento. A granularidade ainda depende de confirmar se são suficientes totais independentes ou se é necessário cruzar matrícula, loja e competência.

O worker escreve o resultado e a API consulta e expõe o conteúdo. As T-202–T-204 especificam contrato, coluna e gravação do diagnóstico de falhas; não estão implementadas apenas por existirem como tarefas.

### Áudio e identidade

`submissoes.binario`, `formato`, `transcricao` e `transcrito_em` já cobrem o armazenamento inicial e das correções por voz. A API chama o ASR e grava a transcrição; o codegen lê somente o texto. Não é necessário criar novas colunas para guardar esses artefatos.

Cadastro e recuperação de senha usam Keycloak. Não exigem armazenamento próprio de senha ou token de recuperação na API; o vínculo local por `keycloak_sub` permanece.

## 7. Limites e pontos ainda em aberto

- A granularidade dos resultados e seu formato de armazenamento precisam ser definidos para atender à rastreabilidade pedida.
- O esquema não contém uma referência explícita na ação de liberação à simulação escolhida. A leitura precisa respeitar a versão e o resultado efetivamente vigentes, sem depender apenas de um timestamp.
- A publicação dos artefatos do codegen e seus eventos não usa o outbox da API; persistir um artefato não comprova por si só que seu evento foi entregue.
- A limpeza de checkpoints após encerramento precisa preservar a deduplicação. Um mecanismo específico de encerramento ainda depende da revisão da proposta.

O schema de `no-concluido` define `evento_id`, e os payloads de outbox seguem os contratos em `contracts/events/`.
