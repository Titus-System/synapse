# Modelagem do banco de dados

* Este arquivo possui os motivos das decisões de modelagem e um explicação com exemplos dos conceitos mais propensos a gerar confusão.

* Não há aqui detalhamento extensivo das regras de negócio da aplicação, apenas o suficiente para entender a modelagem de dados.

* As US-05 e US-04 orientam a modelagem e exigem auditabilidade e explicabilidade do sistema.

O arquivo [`modelo-dados.dbml`](modelo-dados.dbml) é a fonte canônica e define tabelas, colunas, tipos, nulidade, chaves e índices; as convenções do esquema estão no cabeçalho dele. Se os dois divergirem, vale o DBML.

O formato das colunas `jsonb` é definido pelos schemas em [`contracts/domain/`](../../contracts/domain/), que dizem quais chaves são obrigatórias, que tipo cada uma tem e que valores aceita. Os exemplos deste documento são ilustrativos e servem para leitura; o que vale para implementar é o schema.

O DBML reúne a estrutura existente e as extensões aprovadas para a Sprint 2. A seção 6 distingue a estrutura implementada dos fluxos e migrations pendentes, conforme [Fluxo e decisões da Sprint 2](../FLUXO-SPRINT-2.md).

## 1. As tabelas

São 18 tabelas no DBML, num schema único. As seções abaixo explicam o que guardam e, quando há coluna `jsonb` ou array, mostram exemplos dos conteúdos mais propensos a confusão.

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

Uma linha por envio do usuário, com o conteúdo como ele chegou e antes de qualquer processamento. A coluna `tipo` diz como o conteúdo chegou e determina qual carga está preenchida:

| `tipo` | Quem grava | Carga |
| --- | --- | --- |
| `formulario` | `POST /jobs` | `conteudo` |
| `texto` | `POST /submissoes`, na entrada inicial e na correção | `transcricao`, com o texto digitado, gravado no envio |
| `voz` | `POST /submissoes`, na entrada inicial e na correção | `binario` e `formato` no envio, e `transcricao` quando a transcrição fica pronta |

O codegen lê a descrição e a correção sempre em `transcricao`, seja ela digitada ou transcrita.

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

As outras quatro colunas cobrem as submissões de texto e de voz. `binario` guarda os bytes do áudio. `formato` é o contêiner que o navegador gravou, declarado no `Content-Type` da parte `audio` de `POST /submissoes`: `webm`, `ogg`, `wav` ou `mp4`. `transcricao` guarda o texto, digitado ou transcrito, e `transcrito_em` marca a conclusão da transcrição do áudio.

`conteudo` de um lado e `binario` mais `formato` do outro são mutuamente exclusivos, e `tipo` diz qual par está preenchido; na submissão de texto, os dois ficam nulos.

Guardar o binário na mesma linha não pesa as leituras que não pedem a coluna. O PostgreSQL move valores grandes para armazenamento externo por TOAST e só os busca quando a coluna é selecionada, de modo que consultar `tipo` ou `criado_em` não arrasta o áudio junto.


### `jobs`

O processamento de uma submissão do início ao fim. O `id` desta tabela é a chave de correlação que reaparece em quase todas as outras e em todos os eventos do RabbitMQ.

A coluna `nome` é texto nullable, sem valor padrão nem preenchimento retroativo. Guarda somente o nome definido pelo usuário, com 1 a 100 caracteres após remover os espaços das extremidades, compartilhado por todas as versões da regra. Nomes iguais são permitidos. O nome padrão não é gravado nessa coluna.

Em `JobResumo` e `JobDetalhado`, a API devolve um único `nome` resolvido: o nome definido pelo usuário tem prioridade; na ausência dele, usa `submissoes.transcricao` da submissão apontada por `jobs.submissao_id`. Remove espaços das extremidades, substitui cada sequência de espaços, tabulações e quebras de linha por um espaço e usa os primeiros 50 pontos de código Unicode, sem reticências. Textos de até 50 caracteres são usados inteiros. Correções e novas versões não mudam `jobs.submissao_id` nem a origem do nome padrão.

No reprocessamento, a API segue `jobs.job_origem_id` até o primeiro job com submissão para obter o texto inicial. O nome definido pelo usuário no job de origem é copiado para o job novo; renomear um deles depois não altera o outro. A resolução na listagem deve fazer parte da consulta da página, sem uma consulta adicional por item.

Sem nome definido pelo usuário nem texto inicial não vazio após normalização, a API omite `nome`: inclui formulário, cujo `transcricao` é nulo, e voz ainda sem transcrição. O frontend usa então o rótulo com a data de criação. O schema mantém a aceitação de `null` por compatibilidade com a T-200 D; a resolução definida na T-251 representa ausência pela omissão do campo.

A coluna `competencias` é um array de texto com os meses a simular.

```
["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
```

O job cobre o período inteiro em uma simulação, com os meses agregados. Qualquer subconjunto das cinco competências canônicas de agosto a dezembro de 2025 é válido, contíguo ou não, e a lista nunca fica vazia. A forma canônica é ordem crescente sem repetição. Competência usa `AAAA-MM`; datas diárias de vendas existem somente na particularidade de novembro/Black Friday.

Na entrada por texto ou voz definida pela T-277, o job nasce antes da extração, com todas as competências publicadas e com `orcamento` e `meta_venda` nulos. A API aplica depois os parâmetros extraídos: substitui o período quando o texto o diz e grava os valores monetários como foram ditos. Orçamento negativo, meta zero ou negativa e competência fora das publicadas ficam disponíveis para a validação apontar conflitos, antes da execução. Não há restrição numérica de faixa nessas duas colunas.

`orcamento` é o orçamento de comissão do período; sem ele, a simulação não verifica orçamento. `meta_venda` é o total de vendas pretendido para o período; sem ela, a simulação usa as vendas históricas. A ausência de período preserva todas as competências publicadas. A migration e a aplicação dos parâmetros no job pertencem à T-279; a extração é da T-278 e a validação, da T-280. O DBML registra esse contrato, não a conclusão dessas implementações.

A procedência é `submissao_id` ou `job_origem_id`, nunca as duas. É dela que se deduz o ponto de entrada no grafo, sem precisar de coluna dedicada.

### `trabalhos_transcricao`

Controle de processamento da API, criado pela T-231. Cada submissão tem no máximo um trabalho, garantido por `uq_trabalhos_transcricao_submissao_id`. As referências obrigatórias a `jobs` e `submissoes` têm FKs sem exclusão em cascata. A API tem `SELECT`, `INSERT` e `UPDATE`, sem `DELETE`; codegen e worker não têm acesso.

`finalidade` documenta `entrada_inicial | correcao`; `estado`, `pendente | em_andamento | concluido | falhou | descartado`. São colunas `text`, sem enum nativo ou `CHECK`. `tentativas` começa em zero; `reservado_ate` indica o prazo da reserva e `proxima_tentativa_em` agenda uma nova tentativa, ambos nulos na criação. `criado_em` e `atualizado_em` são obrigatórios e recebem o mesmo instante inicial.

Texto e voz trazem os parâmetros na descrição. `POST /submissoes` aceita e ignora os campos obsoletos `orcamento` e `competencias`, sem validá-los. O job nasce com todas as competências publicadas, pela mesma fonte de `POST /jobs`, e com orçamento e meta nulos. A T-279 aplica os parâmetros extraídos depois.

A T-231 grava submissão, job em `aguardando_transcricao`, transição inicial e trabalho pendente na mesma transação, sem `regra-submetida`. O áudio permanece em `submissoes.binario`, com seu formato canônico em `formato`. A T-232 preencherá `submissoes.transcricao` e `transcrito_em` e concluirá o trabalho junto com a transição e o outbox. O processador, a reserva, as novas tentativas e a correção por voz não são implementados pela T-231.

A disponibilidade é consultada por `DisponibilidadeTranscricao`, package-private em `submissoes`, que delega a `ClienteDeepgram.configurado()`. Essa consulta verifica a configuração, sem chamar a transcrição. Sem chave configurada, a API inicia normalmente e recusa voz com `409 estado_invalido`. Os testes podem substituir a disponibilidade sem fazer chamadas externas.

Texto inicial grava a descrição verbatim em `submissoes.transcricao`, cria o job em `gerando_regra` e registra `regra-submetida` sem `regra_id`, orçamento ou meta, sem criar versão de regra. A porta `JobsDeSubmissoes` exige transação existente, centraliza a autorização de criação e compartilha somente `CompetenciasPublicadas` com `POST /jobs`, que preserva suas próprias validações. As operações de concluir/falhar transcrição conferem job, submissão, origem e estado sob trava e, depois do commit, anunciam o novo estado no stream SSE do job. A falha grava o motivo `erro_transcricao`, que o stream e `GET /jobs/{id}` traduzem para a razão exibida ao usuário. A T-232 será responsável por chamá-las na transação final que grava o texto e atualiza o trabalho.

O multipart admite arquivo de até 5 MiB (`5MB` no Spring) e requisição de até 6 MiB para acomodar JSON e cabeçalhos. O Tomcat drena até 10 MB do corpo recusado (`max-swallow-size: 10MB`) para entregar o JSON 413 sem interromper a conexão; isso não amplia o limite de aceitação, e o teto impede que um corpo sem fim prenda uma thread em qualquer rota. Formatos são conferidos por Content-Type e assinatura do contêiner, sem decodificação. O contador `submissoes_criacao_total`, exposto em `/metrics`, registra criações confirmadas e recusas HTTP por `tipo` e `resultado`; rollback não conta como `aceita`. Duração HTTP usa a instrumentação existente. Logs registram resultado, tipo, referências e, para voz validada, formato e faixa de tamanho; não contêm descrição, binário ou filename.

A porta de transcrição emite `transcricao_transicao_seconds` (contagem e duração) até o término da transação do chamador, por `operacao` (`concluir` ou `falhar`) e `resultado` (`aplicada`, `descartada` ou `rollback`). Conta chamadas, não jobs únicos: uma repetição descartada não conta como transição aplicada. Logs de transição preservam `job_id` também nos callbacks após commit e limpam o contexto ao terminar. Esses instrumentos medem apenas a transição, sem incluir espera na fila ou chamada ao provedor.

Os conversores MVC e o vinculador de parâmetros JDBC têm nível mínimo `INFO` mesmo quando o restante da aplicação usa `DEBUG`/`TRACE`: seus logs de diagnóstico podem imprimir o corpo HTTP ou os parâmetros SQL. O teste HTTP captura também os logs do framework, além dos eventos de domínio, para verificar a ausência do texto, dos bytes, do filename e do token.

### `rodadas_correcao`

A estrutura criada pela T-214 guarda uma linha por rodada de validação/correção. `job_id` identifica o job e `regra_analisada_id` a versão que produziu os conflitos. `conflitos` é `jsonb NOT NULL`, no formato de [`contracts/domain/conflitos-rodada.schema.json`](../../contracts/domain/conflitos-rodada.schema.json); o banco não replica a validação desse contrato em `CHECK`.

`submissao_correcao_id` fica nula até o envio da correção e `regra_resultante_id` até existir uma versão resultante. `rodada_anterior_id`, nula na primeira rodada, encadeia o histórico. Os cinco vínculos são chaves estrangeiras, sem exclusão em cascata. `id` nasce de `uuidv7()`, e `criada_em` e `atualizada_em` são obrigatórias, fornecidas por quem grava.

A rodada é mutável: a API atualiza seu estado e suas referências conforme o fluxo. A submissão da correção continua sendo um envio próprio e imutável, sem sobrescrever o texto anterior, e a regra resultante continua sendo uma versão imutável. Esta migration não altera as permissões existentes de `submissoes` ou `regras`. Nenhum serviço recebe `DELETE` em `rodadas_correcao`.

`estado` é `text NOT NULL`, sem `CHECK` ou enum nativo. O vocabulário documentado é `pendente | em_reextracao | reextracao_falhou | corrigida | abandonada`. Apenas `pendente` e `em_reextracao` contam como abertas nesta migration; a ampliação para `em_transcricao` pertence à T-238.

Exemplo de três rodadas do mesmo job:

| Rodada | Regra analisada | Estado | Submissão de correção | Regra resultante | Anterior |
| --- | --- | --- | --- | --- | --- |
| A | v1 | `corrigida` | S1 | v2 | `null` |
| B | v2 | `reextracao_falhou` | S2 | `null` | A |
| C | v2 | `pendente` | `null` | `null` | B |

A cadeia `A → B → C` é permitida. `A → B` e `A → C` juntas são recusadas pelo índice único parcial `uq_rodadas_correcao_rodada_anterior_id`, cujo predicado é `WHERE rodada_anterior_id IS NOT NULL`. Cada rodada pode ter no máximo uma sucessora; este índice não faz validação recursiva de ciclos.

Várias rodadas fechadas podem coexistir para o mesmo job, mas apenas uma em `pendente` ou `em_reextracao`. O índice único parcial `uq_rodadas_correcao_job_id_aberta` aplica `WHERE estado IN ('pendente', 'em_reextracao')`, preservando o histórico fechado.

A tabela existe, mas criar a estrutura não torna o loop funcional: os fluxos que a preenchem pertencem às T-215/T-216/T-217/T-225. O envio de correção por `POST /submissoes` e a consulta em `GET /jobs/{id}/rodadas` ainda dependem das tarefas de implementação correspondentes.

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

Nenhum usuário de banco tem `UPDATE` ou `DELETE` nesta tabela. A unicidade de `(job_id, hash)` deduplica a mesma versão lógica no job.

Pela T-277, `regras.parametros` registra os parâmetros com que cada versão nascida do texto foi criada, conforme [`parametros-simulacao.schema.json`](../../contracts/domain/parametros-simulacao.schema.json). Fica fora de `nucleo` e `especificacoes`. Na extração, recebe `extracoes_regras.parametros`; na correção, recebe o conjunto completo de `correcao-proposta.parametros`. Se o evento omitir esse campo, a API preserva os parâmetros do job e registra na versão nova os da versão corrigida. O objeto `{}` registra que nenhum parâmetro foi dito; `NULL` identifica formulário, reprocessamento e versões anteriores à coluna.

O hash SHA-256 cobre a serialização canônica da representação e, quando `parametros` não é `NULL`, também os parâmetros, inclusive `{}`. Com `NULL`, usa exatamente a serialização anterior. Assim, a correção que muda só os parâmetros gera uma versão nova com a mesma representação, e versões sem parâmetros preservam seus hashes.

### `job_transicoes`

Uma linha por mudança de status do job. É a trilha da máquina de estados da API, diferente da trilha por nó do grafo. Só recebe `INSERT`. `motivo` guarda o código da razão; a API o traduz para a mensagem exibida. A exposição consistente desse motivo em consulta e SSE é parte da T-201.

### `job_acoes`

As ações de finalização que o usuário dispara sobre um job. Junto com `jobs`, é o que sustenta a tela de histórico, e por isso não existe tabela de histórico separada. `aceitar_meta` não finaliza o job: registra que o usuário aceitou a meta de venda sugerida, cuja simulação passa a ser a vigente, e ele segue para as ações de fechamento.

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

### `extracoes_regras`

O artefato imutável produzido pelo codegen ao interpretar uma submissão. `representacao` guarda a regra completa conforme [`representacao-regra.schema.json`](../../contracts/domain/representacao-regra.schema.json); `rebaixamentos` guarda os diagnósticos por elemento conforme [`rebaixamentos-extracao.schema.json`](../../contracts/domain/rebaixamentos-extracao.schema.json). Não é uma versão de `regras`: a API cria essa versão ao consumir a referência do artefato (T-202).

A coluna `parametros`, definida pela T-277, guarda orçamento, meta de venda e período num objeto separado, conforme [`parametros-simulacao.schema.json`](../../contracts/domain/parametros-simulacao.schema.json). É `jsonb` não nulo, com padrão `{}`, que mantém compatível o `INSERT` do produtor anterior à coluna. Não aplica padrões do job: campos não ditos ficam ausentes. Um valor inválido com lastro é preservado para a validação; um parâmetro sem lastro fica ausente e gera um diagnóstico em `rebaixamentos` com `parametros.<campo>`. Esses diagnósticos e os conflitos admitem as três referências de parâmetro; `elemento_ref` continua identificando somente partes da regra.

`job_id` e `submissao_id` identificam a extração lógica, com unicidade do par. `resposta_id` aponta a resposta original, que aponta o prompt e seus metadados de modelo. Prompt, resposta e extração são inseridos na mesma transação; a chamada da LLM ocorre antes dela. Uma gravação concorrente perdedora reverte seus três artefatos e retorna a extração vencedora. O repositório não sobrescreve uma extração existente.

O evento `regra-extraida` leva somente `job_id`, `submissao_id` e `extracao_id`. A publicação pertence à T-204: consultar o artefato antes de chamar a LLM, fazer commit antes de publicar e confirmar a entrada somente após a confirmação do broker. Uma reentrega reutiliza o artefato persistido e republica sua referência. O codegen não escreve no outbox da API. Na T-202, a API deve conferir a associação das três referências antes de criar a versão e seu evento no próprio outbox, atomicamente.

A migration `020-cria-extracoes-regras` precede a ativação do fluxo: codegen recebe `SELECT`/`INSERT`, API recebe `SELECT`, worker não recebe acesso; nenhum serviço pode atualizar ou excluir o artefato.

### `codigos_gerados`

O código Python executável, já extraído da resposta do modelo. A linha aponta a versão da regra que ele traduz e o prompt que o produziu. É o que o worker lê para executar.

### `explicacoes`

A narrativa em linguagem de negócio sobre o que a simulação mostrou, uma por resultado. A coluna `aderencia_conferida` registra se os números citados no texto batem com o que foi apurado, e é falsa quando algum não bate.

### `resultados_simulacao`

O artefato produzido pela execução e pela verificação do worker, persistido com `INSERT` e sem alteração posterior. No sucesso, contém totais, asserções e decomposição. Falha de execução ou asserção violada não produz valores financeiros válidos. Em `erro_codigo`, a coluna `diagnostico` registra por que a execução falhou.

A coluna `totais` traz os agregados do período inteiro, somando todas as competências do job, e é nula quando `status` não é `sucesso`.

```json
{ "baseline": 480312.00, "simulado": 492100.00,
  "diferenca_abs": 11788.00, "diferenca_pct": 0.0245,
  "orcamento": 485000.00 }
```

Os valores são em reais, com exceção de `diferenca_pct`, que é fração. O orçamento aparece aqui embora também exista em `jobs.orcamento`: como esta tabela só aceita `INSERT`, guardar o critério junto do veredito impede que o parâmetro que produziu aquele julgamento seja alterado depois.

Definido pela T-269, o job sem orçamento é simulado sem a verificação de orçamento: `totais.orcamento` fica ausente e `veredito` fica nulo num `sucesso`, porque o número vale e não há critério que o julgue. `totais.vendas_historicas` é o total de vendas das competências do job antes de qualquer escalonamento, acrescentado pelo worker fora do container.

```json
{ "baseline": 529520.00, "simulado": 541900.00,
  "diferenca_abs": 12380.00, "diferenca_pct": 0.0234,
  "orcamento": 600000.00, "vendas_historicas": 23583194.87 }
```

`meta_venda` é a meta em que a execução foi simulada, nula quando ela usou as vendas históricas. Com meta, o sandbox escala todas as vendas do período pelo fator `meta_venda / vendas_historicas` e reapura o baseline antes de chamar o código gerado, e por isso `baseline` e `simulado` são os da meta. A coluna repete o valor do comando pelo mesmo motivo do orçamento: a entrada que produziu o número fica junto dele.

`proposito` separa a simulação do job (`simulacao`) da execução candidata da busca da meta maior (`busca_meta`). A busca roda o mesmo código gerado em várias metas candidatas, e cada candidata é gravada aqui como qualquer resultado. Nenhuma delas é desfecho do job: a API não muda o estado por elas nem as liga a `simulacoes` pelo `codigo_gerado_id`. Só a candidata que fecha a busca é referenciada, por `meta-venda-sugerida`, e passa a ser a simulação vigente se o usuário aceita a meta. O padrão `simulacao` cobre as linhas anteriores à coluna. A migration das colunas é da T-281; o registro da meta sugerida e da aceitação é da T-274.

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

As chaves de `elemento` são os identificadores definidos em `regras`. Essas cinco quebras são mapas independentes de diferenças e não permitem reconstruir linhas de colaborador × loja × competência. A T-200 C acrescenta três mapas opcionais de valores absolutos (`matricula`, `loja_absoluto` e `competencia_absoluto`), que também não preservam esse cruzamento.

A coluna `linhas`, definida pela T-256, guarda o detalhamento em um único `jsonb`, indexado por competência e depois por matrícula. Seu formato canônico é [`resultado-linhas.schema.json`](../../contracts/domain/resultado-linhas.schema.json). Há uma entrada por mês e colaborador, com loja, marca e cargo do RH naquele mês, comissões do baseline congelado e da simulação, diferença e contribuições por elemento. Loja e marca são as da lotação: vendas em outras lojas ou marcas são consolidadas nessa mesma entrada.

O worker grava `linhas` no mesmo `INSERT` do resultado, e a API lê o objeto inteiro. A coluna é nula quando o status não é `sucesso` e nos resultados anteriores à mudança, sem backfill. Fica fora de `decomposicao` e de `resultado-simulacao` para não carregar o detalhamento de todas as simulações em `GET /jobs/{id}`. A rota `GET /jobs/{id}/simulacoes/{simulacaoId}/linhas` devolve `DetalhamentoSimulacao` sem filtros nem paginação; quando não há detalhamento, responde 200 omitindo `linhas`. A migration pertence à T-258 e usa as permissões de INSERT do worker e SELECT da API já existentes.

A conferência fora do container (T-262) classifica como `resultado_incoerente` o detalhamento que não fecha com os totais ou as quebras. Essa causa é distinta de `baseline_divergente`, preservando a classificação existente da conferência do baseline congelado.

A coluna `diagnostico` registra por que uma execução terminou em `erro_codigo`. A `causa` é a classificação do worker e está sempre presente. A `falha` é a exceção que o sandbox efetivamente capturou, conservada como veio no envelope.

```json
{ "causa": "excecao",
  "falha": { "tipo": "KeyError", "mensagem": "'vlr_vendas'",
             "traceback": "  File \"regra.py\", line 31, in aplicar_regra\n    )[\"vlr_vendas\"].sum()\n" } }
```

Timeout, memória excedida e saída inválida são decididos fora do código gerado, a partir do que o worker observou do processo e da saída. Nesses casos não há exceção capturada, e o diagnóstico traz só a causa, sem falha nem traceback reconstruídos.

```json
{ "causa": "timeout" }
```

Quando o envelope diz sucesso mas o resultado não valida contra o schema, `problemas` lista o caminho e a palavra-chave de cada erro, sem o valor rejeitado.

```json
{ "causa": "resultado_fora_do_schema",
  "problemas": [ { "caminho": "$.decomposicao", "palavra_chave": "required" } ] }
```

Quando a conferência de cobertura reprova o código, `elementos_ausentes` lista os elementos exigidos pela regra que o código não declarou, e `elementos_fora_da_regra` os elementos a que ele atribuiu valor sem que a regra os exija. Os dois trazem só identificadores de elemento, nunca texto livre.

```json
{ "causa": "cobertura_incompleta", "elementos_ausentes": ["elem.1"] }
```

Mensagem, traceback e caminhos vieram de código não confiável. São artefato: ficam nesta coluna e não entram em log nem em evento. O evento `simulacao-concluida` continua igual, e o leitor chega ao diagnóstico pelo `resultado_id` que já recebe. O worker grava o diagnóstico no mesmo `INSERT` do resultado; a API e o codegen o leem com o `SELECT` que já têm na tabela. O diagnóstico não é número e não se mistura a `totais` nem a `decomposicao`, que continuam existindo só em sucesso.

A coluna é nula fora de `erro_codigo` e nas linhas gravadas por versões do worker anteriores ao diagnóstico. Linhas antigas não são reconstruídas. A migration da API vai para o ambiente antes da versão do worker que escreve a coluna: o `INSERT` do worker anterior não a menciona e continua funcionando contra o banco migrado, enquanto o novo falharia contra um banco sem ela.

### `outbox_events`

A fila de saída transacional da API. A linha do evento e a mudança de estado que o motivou entram na mesma transação, e um poller lê os pendentes, publica no RabbitMQ e marca como enviados. Nenhum outro serviço acessa esta tabela.

A coluna `payload` é o corpo do evento, carregando referências e nunca o conteúdo de um artefato.

```json
{ "job_id": "b3f1…", "submissao_id": "9ac2…", "origem": "formulario",
  "competencias": ["2025-08", "2025-11"], "regra_id": "77de…",
  "orcamento": 485000.00 }
```

`origem` e `competencias` viajam como valor mesmo existindo no banco, porque nem codegen nem worker têm permissão em `jobs`: o `job_id` é chave de correlação e não ponteiro que o consumidor consiga seguir. O formato é definido pelo schema da mensagem em `contracts/events/`. `orcamento` e `meta_venda` são opcionais em `regra-submetida`; os três campos de parâmetros referenciam as propriedades de `parametros-simulacao.schema.json`. No fluxo de texto e voz, a primeira publicação não leva orçamento nem meta. A republicação após extração leva os parâmetros do job, inclusive valores que a validação ainda deve apontar como conflito. A T-277 define o contrato; a publicação desses valores extraídos pertence à T-279.

A transição para um estado terminal grava `job-encerrado` na mesma transação. O `evento_id` dele é o id da transição em `job_transicoes`, e `encerrado_em` é o `ocorrido_em` dela: uma republicação, ou o registro de um encerramento anterior ao evento, leva os mesmos valores.

### `jobs_grafo_encerrados`

O registro com que o codegen limpa os checkpoints de um job encerrado. Não é artefato auditável: guarda só a identificação do encerramento anunciado pela API (`job-encerrado`) e os instantes. A API cria a tabela e não escreve nela; o codegen insere a linha quando recebe o evento e preenche `limpo_em` quando nenhum checkpoint do job resta, sem poder reescrever o encerramento nem apagar a linha.

```json
{ "job_id": "3f2b…", "evento_id": "0199…", "status": "cancelado",
  "encerrado_em": "2025-11-28T15:02:44.318204Z", "limpo_em": "2025-11-28T15:02:45.104Z" }
```

A linha permanece depois da limpeza porque assume o papel que o checkpoint final cumpria: uma mensagem antiga do job, de submissão ou de resultado, é reconhecida por ela e confirmada sem recomeçar a geração nem repetir publicações. `limpo_em` nulo significa limpeza pendente: adiada enquanto algum ciclo do job espera um resultado que ainda vai ser processado, ou interrompida por uma falha e retomada na subida do codegen. Um job sem linha não está encerrado e mantém seus checkpoints pelo tempo que precisar.

Na implantação, a migration da API vai antes da versão do codegen que consome o evento. A mesma migration registra no outbox o `job-encerrado` de todo job que já estava em estado terminal, com o id e o instante da transição terminal já gravada; os eventos esperam na fila `job-encerrado` até o codegen consumi-los, e um job que já tem o evento não ganha outro.

## 2. Quem escreve o quê

Em `rodadas_correcao`, a API tem `SELECT`, `INSERT` e `UPDATE`, sem `DELETE`. O codegen tem apenas `SELECT`, sem permissão para inserir, alterar ou apagar rodadas. O worker não tem acesso.

A API escreve `usuarios`, `submissoes`, `jobs`, `job_transicoes`, `job_acoes`, `simulacoes`, `trilhas_auditoria` e `outbox_events`. O codegen insere `prompts`, `respostas_modelo`, `extracoes_regras`, `codigos_gerados` e `explicacoes`, e registra em `jobs_grafo_encerrados` o encerramento recebido e a conclusão da limpeza; é a única tabela em que tem `UPDATE`, restrito a `limpo_em`. O worker insere só `resultados_simulacao`.

`regras` ainda permite inserção pela API e pelo codegen nas permissões existentes. O fluxo usa a API para versões submetidas, confirmadas ou propostas na adaptação; na extração inicial, o codegen grava `extracoes_regras` e a API cria a versão ao consumir `regra-extraida` (T-202). Nenhum dos dois tem `UPDATE` ou `DELETE`: editar significa inserir uma versão nova encadeada por `regra_origem_id`.

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

No fluxo atual, a entrada e as versões permitem comparar parâmetros. `rodadas_correcao` fornece a estrutura para preservar a relação entre versão analisada, conflito, submissão de correção e versão resultante. Seu preenchimento e a apresentação do histórico no chatbot dependem dos fluxos posteriores à T-214.

Duas coisas o esquema não reconstrói. Qual simulação foi liberada, porque `job_acoes` registra a ação sem apontar simulação, e num job com várias alternativas isso só se infere pela ordem dos timestamps. E um nó cujo evento se perdeu entre a gravação dos artefatos e a publicação: os artefatos continuam alcançáveis pelo `job_id`, mas a sequência de nós fica com um buraco que nada denuncia.

## 5. Fora do modelo

O dataset e os baselines são estáticos e vivem embutidos na imagem do sandbox, sem versionamento no banco. A consequência aceita é que dois resultados apurados sobre imagens diferentes ficam indistinguíveis.

As tabelas de checkpoint do LangGraph são criadas e migradas pela própria biblioteca, ficam no mesmo schema e só o codegen as acessa. Nenhuma chave estrangeira atravessa essa fronteira, e a correlação usa `thread_id = job_id:regra_id`, com fallback legado por job somente para o mesmo ciclo. A limpeza acontece depois do encerramento do job, e `jobs_grafo_encerrados` assume a deduplicação que o checkpoint final fazia.

Os `GRANT` que sustentam tanto o isolamento entre serviços quanto a imutabilidade da regra são migration, escritos junto ao changeset que cria cada tabela.

Os enums do DBML são vocabulário documentado e não `CHECK`. Exclusão mútua entre colunas, formato de competência e completude por construto são validados no código de cada stack, com `contracts/` como autoridade compartilhada do vocabulário.

## 6. Extensões aprovadas para a Sprint 2

Esta seção distingue estrutura e fluxos: `jobs.nome` e seu contrato HTTP já estão definidos, e a T-214 implementa a estrutura de `rodadas_correcao`. A existência dessas estruturas não conclui os fluxos; as demais migrations e schemas devem acompanhar suas tarefas de implementação.

### Rodadas de validação e correção

A tabela `rodadas_correcao`, implementada pela T-214 e descrita na seção 1, relaciona `jobs` à versão de `regras` analisada, com conflitos em `jsonb` e referências à submissão e à versão resultante. Os fluxos que a preenchem continuam nas T-215/T-216/T-217/T-225. Cada correção textual ou de voz será uma submissão separada; não incorporará nem sobrescreverá as anteriores.

O formato da lista de conflitos é [`contracts/domain/conflitos-rodada.schema.json`](../../contracts/domain/conflitos-rodada.schema.json). Os estados da rodada (`pendente`, `em_reextracao`, `reextracao_falhou`, `corrigida` e `abandonada`) e sua exposição em `GET /jobs/{id}/rodadas` estão em [`contracts/http/openapi.yaml`](../../contracts/http/openapi.yaml).

O histórico completo será consultável. Sair do chatbot preserva o estado do job e a rodada pendente, e não há limite de correções. O SSE não substitui esse armazenamento.

### Nome do job e apresentação como campanha

A T-200 D define a coluna nullable `jobs.nome` e o campo opcional nos contratos `JobResumo` e `JobDetalhado`. A T-251 define em [`contracts/http/openapi.yaml`](../../contracts/http/openapi.yaml) a resolução do nome pela API, detalhada na seção `jobs`, e `PUT /jobs/{id}/nome`. A renomeação vale em qualquer estado, sem alterar regra, simulação ou estado; não grava trilha de auditoria nem `job_acoes` e não emite evento no stream. A implementação da API pertence à T-253, e a apresentação no frontend às T-254 e T-255.

Campanha é a apresentação de um job com resultado viável. Não há nova tabela de campanhas nem agrupamento de vários jobs neste escopo. Versões anteriores continuam alcançáveis como histórico.

### Resultados e diagnóstico

E9 acrescenta matrícula e valores absolutos, preservando as quebras atuais de diferença (T-200 C). A T-256 define o cruzamento por competência e matrícula na coluna `linhas`, com loja e marca da lotação no RH, conforme a seção 1. O contrato e o modelo estão definidos; a migration, a produção, a consulta e a conferência do detalhamento pertencem às T-258, T-259, T-260 e T-262.

O worker escreve o resultado e a API consulta e expõe o conteúdo. O diagnóstico de falhas, gravado pelo worker em todo `erro_codigo`, está descrito em `resultados_simulacao`, na seção 1.

### Áudio e identidade

`submissoes.binario`, `formato`, `transcricao` e `transcrito_em` já cobrem o armazenamento inicial e das correções por voz. A API chama o ASR e grava a transcrição; o codegen lê somente o texto. Não é necessário criar novas colunas para guardar esses artefatos.

Cadastro e recuperação de senha usam Keycloak. Não exigem armazenamento próprio de senha ou token de recuperação na API; o vínculo local por `keycloak_sub` permanece.

## 7. Limites e pontos ainda em aberto

- O esquema não contém uma referência explícita na ação de liberação à simulação escolhida. A leitura precisa respeitar a versão e o resultado efetivamente vigentes, sem depender apenas de um timestamp.
- A publicação dos artefatos do codegen e seus eventos não usa o outbox da API; persistir um artefato não comprova por si só que seu evento foi entregue.
- Um ciclo pausado à espera de um resultado cuja mensagem ao codegen se perdeu mantém a limpeza do job adiada: pelo checkpoint, o codegen não distingue um resultado ainda na fila de um que não volta.

O schema de `no-concluido` define `evento_id`, e os payloads de outbox seguem os contratos em `contracts/events/`.
