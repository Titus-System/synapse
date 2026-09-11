# Modelagem do banco de dados

* Este arquivo possui os motivos das decisões de modelagem e um explicação com exemplos dos conceitos mais propensos a gerar confusão.

* Não há aqui detalhamento extensivo das regras de negócio da aplicação, apenas o suficiente para entender a modelagem de dados.

* O principal guia de decisões foram as US-05 e US-04, que exigem auditabilidade e explicabilidade do sistema.

O arquivo [`modelo-dados.dbml`](modelo-dados.dbml) é a fonte canônica e define tabelas, colunas, tipos, nulidade, chaves e índices; as convenções do esquema estão no cabeçalho dele. Se os dois divergirem, vale o DBML.

O formato das colunas `jsonb` é definido pelos schemas em [`contracts/domain/`](../../contracts/domain/), que dizem quais chaves são obrigatórias, que tipo cada uma tem e que valores aceita. Os exemplos deste documento são ilustrativos e servem para leitura; o que vale para implementar é o schema.

## 1. As tabelas

São catorze, num schema único. Cada uma aparece abaixo com o que guarda e, quando tem coluna `jsonb` ou array, com um exemplo do conteúdo dela, porque é ali que mora a maior chance de confusão.

### `usuarios`

Quem entra no sistema. A autenticação é local, feita pela própria API, sem provedor de identidade externo. Usuário desativado mantém a linha, porque jobs antigos a referenciam.

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
["2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
```

O job cobre o período inteiro em uma simulação, com os meses agregados, e não uma simulação por competência. Qualquer subconjunto das seis competências do dataset é válido, contíguo ou não, e a lista nunca fica vazia. A forma canônica é ordem crescente sem repetição, senão o mesmo conjunto de meses vira dois valores distintos. O formato é `AAAA-MM` porque as bases só trazem competência mensal.

A procedência é `submissao_id` ou `job_origem_id`, nunca as duas. É dela que se deduz o ponto de entrada no grafo, sem precisar de coluna dedicada.

### `regras`

A representação estruturada da regra, que é o artefato que o usuário confirma antes de qualquer código ser gerado. A regra vive em duas colunas: `nucleo`, com os campos que toda regra tem, e `especificacoes`, com tudo o mais que ela tiver.

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

Todo item tem a mesma anatomia: `ref` identifica, `construto` diz de que forma o elemento é, e o resto são os campos que aquela forma exige. Sem o construto não há como validar, porque é ele que diz que `elem.1` é uma faixa e portanto precisa de limite superior. Elemento que não corresponde a nenhuma forma conhecida entra como `generico`. A ordem do array é a ordem de exibição na tela de confirmação.

#### Identificação das partes da regra

Cada parte da regra tem um identificador estável dentro da versão. Campo do núcleo usa o nome do campo prefixado, como `nucleo.percentual`. Item de `especificacoes` usa o `ref` dele, atribuído sequencialmente na criação: `elem.1`, `elem.2`.

Os dois formam um espaço único porque as mesmas listas citam campos do núcleo e elementos lado a lado. É por esses identificadores que o código gerado declara o que implementa, que a cobertura é conferida, e que `resultados_simulacao.decomposicao` chaveia a quebra por elemento.

O identificador não carrega o construto. `elem.faixa.1` duplicaria informação que já tem campo próprio e quebraria se o elemento fosse reclassificado.

#### Imutabilidade

Uma versão já usada por um resultado nunca é alterada. Edição na confirmação, alternativa da adaptação e reprocessamento geram versão nova, com `versao` incrementado e `regra_origem_id` registrando de onde ela derivou.

O que garante isso não é disciplina de código: nenhum usuário de banco tem `UPDATE` ou `DELETE` nesta tabela. O par `(job_id, hash)` é único, o que impede a mesma regra entrar duas vezes como versões diferentes.

### `job_transicoes`

Uma linha por mudança de status do job. É a trilha da máquina de estados da API, coisa diferente da trilha por nó do grafo. Só recebe `INSERT`.

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

A coluna `evento_id` é a chave de idempotência, com índice único. O broker entrega ao menos uma vez, e uma reentrega duplicaria a trilha. O valor é um uuid aleatório que o codegen gera ao publicar e carrega na mensagem, e precisa vir de fora porque qualquer valor gerado na recepção seria diferente nas duas entregas. Não cobre republicação pelo produtor, que geraria um uuid novo.

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

O que o sandbox apurou. É escrita pelo worker num único `INSERT` e nunca alterada depois, e por isso as três colunas de conteúdo são `jsonb`: chegam juntas, são lidas inteiras e nenhuma serve de critério de busca.

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

Zero e ausência dizem coisas diferentes. `2025-08` com zero é um mês que foi simulado e que a regra não afetou. Ausente da quebra por elemento significa efeito não mensurável ou implementação faltante.

As chaves de `elemento` são os identificadores definidos em `regras`.

### `outbox_events`

A fila de saída transacional da API. A linha do evento e a mudança de estado que o motivou entram na mesma transação, e um poller lê os pendentes, publica no RabbitMQ e marca como enviados. Nenhum outro serviço acessa esta tabela.

A coluna `payload` é o corpo do evento, carregando referências e nunca o conteúdo de um artefato.

```json
{ "job_id": "b3f1…", "submissao_id": "9ac2…", "origem": "formulario",
  "competencias": ["2025-08", "2025-11"], "regra_id": "77de…" }
```

`origem` e `competencias` viajam como valor mesmo existindo no banco, porque nem codegen nem worker têm permissão em `jobs`: o `job_id` é chave de correlação e não ponteiro que o consumidor consiga seguir. O formato ainda é provisório e será reconciliado com os schemas em `contracts/events/`.

## 2. Quem escreve o quê

A API escreve `usuarios`, `submissoes`, `jobs`, `job_transicoes`, `job_acoes`, `simulacoes`, `trilhas_auditoria`, `regras` e `outbox_events`. O codegen insere `prompts`, `respostas_modelo`, `codigos_gerados` e `explicacoes`. O worker insere só `resultados_simulacao`.

O que impõe isso é a permissão do usuário de banco com que cada serviço conecta, definida nas migrations e portanto ausente do DBML.

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

Para saber o que o usuário editou, compare `submissoes.conteudo` com `regras.nucleo`. A linha de confirmação na trilha lista os campos corrigidos.

Duas coisas o esquema não reconstrói. Qual simulação foi liberada, porque `job_acoes` registra a ação sem apontar simulação, e num job com várias alternativas isso só se infere pela ordem dos timestamps. E um nó cujo evento se perdeu entre a gravação dos artefatos e a publicação: os artefatos continuam alcançáveis pelo `job_id`, mas a sequência de nós fica com um buraco que nada denuncia.

## 5. Fora do modelo

O dataset e os baselines são estáticos e vivem embutidos na imagem do sandbox, sem versionamento no banco. A consequência aceita é que dois resultados apurados sobre imagens diferentes ficam indistinguíveis.

As tabelas de checkpoint do LangGraph são criadas e migradas pela própria biblioteca, ficam no mesmo schema e só o codegen as acessa. Nenhuma chave estrangeira atravessa essa fronteira, e a correlação com o resto é o `job_id` usado como `thread_id`.

Os `GRANT` que sustentam tanto o isolamento entre serviços quanto a imutabilidade da regra são migration, escritos junto ao changeset que cria cada tabela.

Os enums do DBML são vocabulário documentado e não `CHECK`. Exclusão mútua entre colunas, formato de competência e completude por construto são validados no código de cada stack, com `contracts/` como autoridade compartilhada do vocabulário.

## 6. Em aberto

O evento que alimenta a trilha precisa carregar `evento_id`, que já está no catálogo de mensagens da arquitetura e da ADR-003 mas ainda não tem schema em `contracts/events/`. O `payload` do outbox segue provisório e precisa ser reconciliado com esses schemas antes de a migration congelar o formato. Nada no esquema aponta qual simulação foi liberada. E `job_transicoes` recebe um `INSERT` por evento consumido sem ter chave de idempotência, o mesmo problema que `evento_id` resolve na trilha.
