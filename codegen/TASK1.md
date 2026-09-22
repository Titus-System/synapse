# T-094 - Chamar o grafo a partir do consumer de `regra-submetida`

- **Componente**: codegen
- **Estimativa**: 2
- **Depende de**: nada. Roda em paralelo com T-096, T-097 e T-098, seguindo o combinado abaixo.

**Entregável**: um roteador que, ao receber `regra-submetida`, chama o grafo do job, com a aplicação subindo o consumer.

## Descrição

Os consumers e producers já existem (T-049, `app/mensageria/`). O consumer chama `RoteadorGrafo.entregar(job_id, mensagem)`, mas `RoteadorGrafo` é só um `Protocol` sem implementação, e `criar_aplicacao()` não injeta roteador. Por isso o `lifespan` emite "consumo não iniciado" e nenhum consumer sobe. O grafo (T-048, em `develop`) só sabe ser chamado com `entrypoint.run(job_id, prompt)`.

Esta tarefa implementa o roteador, monta o estado inicial a partir do evento, chama o grafo e faz a aplicação subir o consumer.

## Interface acordada com as outras tarefas (não mudar sem avisar)

- Os nós recebem `sessoes` (`async_sessionmaker[AsyncSession]`) e `producers` (`Producers`) por `config["configurable"]`. Esta tarefa monta os dois na aplicação.
- Campos de `AgentState` que esta tarefa preenche (opcionais, com esta mesma definição): `job_id`, `regra_id`, `origem` (`str`), `competencias` (`list[str]`) e `orcamento` (`str`, texto decimal, nunca `float`). Os demais campos são da T-096 e da T-097.
- Os nós do grafo (`load_rule`, `code_generation`, etc.) são das T-096 e T-097. Nos testes desta tarefa, use um grafo falso.

## Escopo

**Dentro do escopo**

- Implementação de `RoteadorGrafo` em `app/mensageria/`: traduz `RegraSubmetida` no estado inicial, chama o grafo com `thread_id = job_id` e só retorna quando o grafo termina ou pausa.
- Nova função em `app/graph/entrypoint.py` que recebe o `job_id` e o estado inicial (em vez de `prompt`) e consome o `astream` até o fim.
- DTO `RegraSubmetida`: campo opcional `orcamento` (`Decimal`, `>= 0`), conforme a T-098. O estado leva o valor como `str`.
- `lifespan`: cria o engine do banco e o `async_sessionmaker`, roda `checkpointer.setup()` (idempotente) e passa o roteador a `criar_aplicacao`.
- `iniciar_consumers` sobe só o consumer de `regra-submetida`. As outras duas filas ficam com as mensagens preservadas.
- Teste com grafo falso.

**Fora do escopo**

- Nós do grafo (T-096 e T-097).
- Retomada com `Command(resume=...)`, reentrega idempotente e política de falha do consumer.
- Alterações em `api` ou `worker`.

## Requisitos

- O `Consumer` chama o grafo só pela fronteira `RoteadorGrafo`. Nada de LangGraph dentro de `Consumer`.
- Só `astream`/`ainvoke`, nunca as variantes síncronas.
- O evento carrega referências. O estado inicial não recebe conteúdo de artefato.
- Logs com `job_id`, sem estado, prompt, resposta, código nem texto de exceção.
- `make pre-commit` verde e `make lint` (Bandit).

## Contexto técnico

- Arquivos principais: `app/mensageria/consumers.py`, `roteamento.py`, `broker.py`, `app/main.py`, `app/graph/entrypoint.py`, `app/graph/core/checkpointer.py`.
- `AsyncPostgresSaver` usa `psycopg` e cria tabelas próprias em `setup()`. O usuário de banco do codegen tem `CREATE` no schema `public`. O SQLAlchemy usa `asyncpg`.
- A mensagem fica sem `ack` durante toda a execução do grafo, inclusive a chamada ao LLM. O `consumer_timeout` do RabbitMQ precisa ser maior que o timeout do cliente do LLM (T-096).
- Mudança interna ao codegen.

## Critérios de aceitação

- Um `regra-submetida` válido chama o grafo uma vez com o estado inicial correto e `thread_id == job_id`, e recebe `ack` depois do retorno.
- `criar_aplicacao(roteador=...)` inicia só o consumer de `regra-submetida`, e `checkpointer.setup()` roda na subida.
- **Validação final** (depois de T-096, T-097 e T-098 em `develop`): com os serviços reais, um `POST /jobs` resulta em `executar-codigo` consumido pelo worker e em uma linha em `resultados_simulacao`. Registrar no PR, sem prompt, resposta, código nem chave.

## Definição de concluído (DoD)

- [ ] Código, testes e `docs/mensageria.md` atualizados.
- [ ] `make pre-commit` e `make lint` verdes.
- [ ] PR de um serviço só (`codegen`), de `feature/...` para `develop`, com a CI verde.
