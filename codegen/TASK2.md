# T-096 - Carregar a regra e enviar o prompt de geração ao LLM

- **Componente**: codegen
- **Estimativa**: 4
- **Depende de**: nada. Roda em paralelo com T-094, T-097 e T-098, seguindo o combinado abaixo.

**Entregável**: dois nós do grafo, `load_rule` e `code_generation`, que leem a regra confirmada do banco e enviam o prompt de geração ao LLM, devolvendo ao estado a resposta bruta e os dados da chamada.

## Descrição

O evento `regra-submetida` traz só referências. Para `formulario`, a `api` já grava a linha de `regras` (núcleo e especificações) e envia o `regra_id`. O codegen já sabe montar o prompt (`montar_prompt_geracao`, `app/prompts/geracao_codigo.py`) e, em `develop` (T-048), tem o registro de modelos (`app/graph/core/llm/registry.py`, Gemini) e um nó de exemplo (`calculator`). Nenhum nó lê a regra nem usa o prompt real.

Esta tarefa cria os dois primeiros nós do fluxo: `load_rule` lê a regra de `regras`, e `code_generation` monta o prompt, chama o modelo e devolve a resposta.

## Interface acordada com as outras tarefas (não mudar sem avisar)

- **Dependências dos nós** chegam por `config["configurable"]`: `sessoes` (`async_sessionmaker[AsyncSession]`) e `producers` (`Producers`). A T-094 monta os dois na aplicação. Nos testes, o próprio teste monta.
- **Campos de `AgentState`** (todos opcionais; declare os que usa, com esta mesma definição):

  | Campo                                                          | Tipo                                                          | Quem escreve           |
  | -------------------------------------------------------------- | ------------------------------------------------------------- | ---------------------- |
  | `job_id`, `regra_id`, `origem`                                 | `str`                                                         | T-094 (estado inicial) |
  | `competencias`                                                 | `list[str]`                                                   | T-094                  |
  | `orcamento`                                                    | `str` (texto decimal, nunca `float`)                          | T-094                  |
  | `representacao_regra`                                          | `dict` (`RepresentacaoRegra.para_contrato()`)                 | **esta tarefa**        |
  | `prompt_enviado`, `resposta_bruta`                             | `str`                                                         | **esta tarefa**        |
  | `modelo`                                                       | `dict` (`modelo-llm.schema.json`)                             | **esta tarefa**        |
  | `consumo_tokens`                                               | `dict` (`consumo-tokens.schema.json`), ausente sem informação | **esta tarefa**        |
  | `prompt_id`, `resposta_id`, `codigo_fonte`, `codigo_gerado_id` | `str`                                                         | T-097                  |

- **Cadeia do grafo**: `START → load_rule → code_generation → persist_response → extract_code → dispatch_execution → await_execution`. Esta tarefa cria os dois primeiros nós e as arestas `START → load_rule → code_generation`. A aresta `code_generation → persist_response` é adicionada por quem mergear por último entre esta tarefa e a T-097. Nos testes, use um nó falso no lugar do vizinho.
- Conflitos triviais em `state.py`, `engine.py` e `docs/graph.md` (regenerar com `make graph`) são resolvidos por quem mergear depois.

## Escopo

**Dentro do escopo**

- Nó `load_rule` (`app/graph/nodes/load_rule.py`): `SELECT nucleo, especificacoes FROM regras WHERE id = :regra_id AND job_id = :job_id`, monta e valida `RepresentacaoRegra` e grava `representacao_regra` no estado. Regra inexistente ou inválida falha o nó.
- Camada de leitura em `app/repositorio/regras.py`, usando `sessoes`.
- Nó `code_generation` (`app/graph/nodes/code_generation.py`): pede `get_model("code_generation")` ao registro, sem `bind_tools`, e envia o prompt como uma mensagem só.
- Entrada `code_generation` no registro, com modelo e parâmetros definidos na seção de decisões, timeout e tentativas explícitos.
- `montar_prompt_geracao` passa a pedir o formato da resposta: **um único bloco ```` ```python ```` com o arquivo `regra.py` completo, definindo `aplicar_regra`**. Atualizar `tests/app/prompts/test_geracao_codigo.py`. A T-097 extrai o código com base nesse formato.
- Devolver ao estado: `prompt_enviado`, `resposta_bruta` (verbatim), `modelo` (provedor, modelo, versão, parâmetros) e `consumo_tokens` quando o provedor informar.
- Falha do nó: erro do provedor, resposta vazia, bloqueada ou truncada por limite de tokens.
- O nó de exemplo `calculator` sai do caminho do grafo.
- Testes com o modelo falso de `tests/app/graph/conftest.py`, e um teste opt-in (marker `llm`) com o provedor real.

**Fora do escopo**

- Montar o estado inicial e validar a mensagem (T-094).
- Gravar prompt, resposta e código, e publicar (T-097).
- Extração de parâmetros e pausa de confirmação.
- Separar instruções e dados em `SystemMessage` e `HumanMessage`.
- Mover `app/prompts/geracao_codigo.py`.

## Requisitos

- Nenhum número de simulação é produzido pelo LLM. A resposta do modelo é dado não confiável e nunca é executada, importada nem avaliada.
- A regra é dado não confiável e não decide qual nó roda.
- Logs com `job_id`, `no`, modelo, duração e tokens. Nunca regra, prompt, resposta, código ou texto de exceção do provedor.
- A chave (`Settings.GOOGLE_API_KEY`) nunca entra em prompt nem em log. Chave ausente produz erro claro, sem valor.
- O timeout do cliente é menor que o timeout de entrega do RabbitMQ, porque a mensagem fica sem `ack` durante a chamada.
- `make pre-commit` verde e `make lint` (Bandit).

## Contexto técnico

- O prompt real é grande (bases, convenções, contrato `RegraFn`, schemas). Medir o tamanho antes de escolher o modelo e o limite de saída.
- O codegen tem `SELECT` e `INSERT` em `regras`; aqui só o `SELECT`. Em `formulario`, `especificacoes` é `[]`.
- `RepresentacaoRegra` tem `Decimal` e datas. Confirmar que o estado sobrevive ao serializador do checkpointer.
- Mudança interna ao codegen.

## Critérios de aceitação

- Com uma linha válida em `regras`, `load_rule` grava `representacao_regra` igual a `RepresentacaoRegra(...).para_contrato()`. Regra inexistente ou inválida falha o nó.
- `code_generation` chama o modelo uma vez, sem ferramentas, com o conteúdo igual a `montar_prompt_geracao(regra)`, e devolve `resposta_bruta` idêntica à do modelo.
- O prompt contém a instrução do bloco `python` único. Um teste falha se ela sair.
- `modelo` valida contra `modelo-llm.schema.json`. Sem consumo informado, `consumo_tokens` fica ausente e o nó não falha.
- Resposta vazia, bloqueada ou truncada falha o nó, sem estado parcial.
- Nenhum log dos nós contém regra, prompt ou resposta. Um teste confere isso.
- A suíte padrão não faz chamada de rede. O teste opt-in envia o prompt real, verifica exatamente um bloco `python` e é pulado sem `GOOGLE_API_KEY`.
- `docs/graph.md` regenerado com `make graph`.

## Definição de concluído (DoD)

- [ ] Código, testes, `.env.example` e `docs/graph.md` atualizados. `make pre-commit` e `make lint` verdes.
- [ ] PR de um serviço só (`codegen`), de `feature/...` para `develop`, com a CI verde.
- [ ] Resultado do teste opt-in descrito no PR, ou registrado como não executado.

## Observações / Decisões

- **Modelo e parâmetros**: `calculator` usa um `flash-lite`. Decidir modelo, temperatura, limite de saída e timeout do `code_generation`.
- **Nome da variável de chave**: o `Settings` lê `GOOGLE_API_KEY`. Conferir o nome usado nos `.env` locais e no compose.
