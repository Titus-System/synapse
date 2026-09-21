# T-038 — Outbox transacional e poller (api)

## Contexto

Hoje a `api` cria o job (`CriarJobService`) mas não publica nada: se ela gravasse o job e
só depois publicasse no RabbitMQ, uma queda entre os dois passos deixaria o job no banco sem
que ninguém o processasse. O outbox fecha essa janela. A linha do evento entra em
`outbox_events` **na mesma transação** da operação de negócio, e um poller `@Scheduled`
publica o que está pendente e marca como enviado.

A tabela (`014-cria-outbox-events.sql`, T-024) e a topologia (`RabbitTopologyConfig`, T-088)
já existem. Esta tarefa entrega só o **componente reutilizável**, que é núcleo de
infraestrutura. Os eventos concretos ficam para T-040 (`regra-submetida`) e T-041
(`parametros-confirmados`). Nenhuma mudança de contrato, migration ou serviço externo.

Branch: `feature/t-038-outbox-transacional`, a partir de `develop`.

**Passo 0:** assim que o plano for aprovado, copiar este arquivo para
`/home/pedro/projects/synapse/plano.md`, para leitura e edição. Esse arquivo não entra em
nenhum commit (não é adicionado ao `git add`).

## Desenho

### Pacote `synapse.api.core.outbox` (núcleo, classes `public` só onde as fatias precisam)

| Arquivo | Papel |
| --- | --- |
| `EventoOutbox.java` (enum, public) | Os eventos que a api publica: `REGRA_SUBMETIDA`, `PARAMETROS_CONFIRMADOS`. Cada valor carrega o nome da fila, lido das constantes de `RabbitTopologyConfig`. Com o enum, um `tipo` sem fila declarada não compila. |
| `Outbox.java` (`@Component`, public) | Porta de escrita: `void registrar(UUID jobId, EventoOutbox evento, Object payload)`. Usa `@Transactional(propagation = MANDATORY)`, então chamar sem transação ativa lança `IllegalTransactionStateException`. Serializa com `JsonMapper` (mesmo idioma do `CriarJobService`; o nome dos campos vem do DTO de quem chama) e faz `INSERT INTO outbox_events (job_id, tipo, payload, criado_em) VALUES (?, ?, ?::jsonb, ?)`. |
| `PublicadorOutbox.java` (`@Component`, package-private) | Um ciclo do poller: `void publicarPendentes()`. É onde está a lógica (ver abaixo). |
| `OutboxConfig.java` (`@Configuration @EnableScheduling`, package-private) | `SchedulingConfigurer`, no mesmo padrão de `HeartbeatSseConfig`: `registrar.addFixedDelayTask(publicador::publicarPendentes, properties.outbox().pollInterval())`. Usa **fixed delay** e não fixed rate, para que um ciclo lento nunca se sobreponha ao seguinte. Tem `@ConditionalOnBooleanProperty(name = "app.outbox.enabled", matchIfMissing = true)`. |

### Um ciclo do poller (`publicarPendentes`, `@Transactional`)

1. Busca um lote:
   ```sql
   SELECT id, job_id, tipo, payload::text FROM outbox_events
   WHERE publicado_em IS NULL
   ORDER BY criado_em, id
   LIMIT ? FOR UPDATE SKIP LOCKED
   ```
   O lote é uma constante de 50. A trava de linha dura a transação inteira: um ciclo
   concorrente (outra thread, ou uma retentativa manual) **pula** as linhas em voo em vez de
   publicá-las de novo. É isso que garante o critério "não republica, mesmo concorrendo".
2. Para cada evento, na ordem, abre `CorrelationContext.abrir(jobId, null)` e publica com
   confirmação do broker:
   - `rabbitTemplate.send("", tipo, mensagem, new CorrelationData(id))`, e depois
     `correlacao.getFuture().get(TIMEOUT_CONFIRMACAO)`, com uma constante de 5 s.
   - Sucesso = `ack` **e** `correlacao.getReturned() == null`. Isso exige `mandatory`: uma
     mensagem sem fila de destino volta ao produtor em vez de sumir em silêncio.
   - Sucesso → `UPDATE outbox_events SET publicado_em = ?, tentativas = tentativas + 1 WHERE id = ? AND publicado_em IS NULL`, mais um `log.info("evento do outbox publicado")`.
   - Falha (`AmqpException`, `nack`, retorno, timeout ou interrupção) →
     `UPDATE ... SET tentativas = tentativas + 1 WHERE id = ?`, mais um `log.atWarn()` com
     `evento_id`, `tipo`, `tentativas` e `setCause`, e **o ciclo termina**. Sem exceção, o
     commit grava a tentativa, o evento continua pendente e o próximo ciclo tenta de novo.
     Parar na primeira falha preserva a ordem (um evento posterior do mesmo job nunca passa
     à frente) e evita martelar um broker que caiu.
3. Mensagem AMQP, espelhando `codegen/app/mensageria/producers.py`: corpo = `payload`
   (UTF-8), `content_type=application/json`, `content_encoding=utf-8`, `PERSISTENT`,
   `message_id=<outbox_events.id>`, `correlation_id=<job_id>`, `type=<tipo>`. Todas são
   propriedades AMQP aditivas, e nenhum schema de `contracts/` muda.
4. Nunca vai para o log: o payload. Vão: id do evento, tipo, tentativas. O `job_id` entra
   pelo `CorrelationContext`.

**Semântica de entrega: pelo menos uma vez.** Se a api cair entre o `ack` do broker e o
commit do `UPDATE`, o evento sai de novo no próximo ciclo. O `message_id` estável existe
para que o consumidor deduplique. É o custo aceito da decisão e fica documentado na skill.

### Configuração

- `application.yaml`
  - bloco `app.outbox`:
    - `enabled: ${OUTBOX_ENABLED:true}`
    - `poll-interval: ${OUTBOX_POLL_INTERVAL:1s}`
  - em `spring.rabbitmq`:
    - `publisher-confirm-type: correlated`
    - `publisher-returns: true`
    - `template.mandatory: true`
  - `spring.task.scheduling.pool.size: 2`: o scheduler padrão tem uma thread só, e o
    heartbeat SSE bloqueia enquanto envia a um cliente lento, o que atrasaria o outbox.
- `AppProperties`: novo record `Outbox(boolean enabled, @NotNull Duration pollInterval)`, com
  `@param` no Javadoc e o componente `outbox` no record raiz.
- `.env.example`: seção `---- Outbox ----` com as duas variáveis e a latência explicada.
- `src/test/resources/application-test.properties`: `app.outbox.enabled=false`. Sem isso,
  todo contexto de teste sem banco tentaria conectar ao Postgres a cada segundo.

### Documentação (é aqui que o critério "intervalo documentado" fica atendido)

- Nova skill `api/.agents/skills/outbox/SKILL.md`, no formato da skill `sse`. Cobre:
  - como registrar um evento dentro do `@Transactional` da operação;
  - o que é proibido (`AFTER_COMMIT`, `@Async`);
  - o intervalo como latência adicional entre o commit e a publicação (default 1 s);
  - a entrega pelo menos uma vez e o `message_id`;
  - a ordem e a parada na primeira falha;
  - a instância única, e por que `SKIP LOCKED` já protege contra ciclos concorrentes.
- `api/AGENTS.md`: uma linha na tabela de skills apontando para `outbox`.

## Testes

### `src/test/java/synapse/api/core/outbox/OutboxTests.java`

Usa `@EnabledIf("dockerIsAvailable")`, com Postgres 18 e RabbitMQ 3.13 via Testcontainers.

- **Montagem**
  - Roda o Liquibase à mão e define a senha de `synapse_api`, como em
    `CriarJobPersistenciaTests`.
  - Sobe a aplicação com `SpringApplicationBuilder(ApiApplication.class).web(NONE)`, perfil
    `test`, e estes ajustes:
    - Postgres e RabbitMQ apontados para os containers;
    - `spring.rabbitmq.dynamic=true`, para que as filas existam;
    - `app.outbox.enabled=false`, para que os ciclos sejam chamados à mão e o teste seja
      determinístico.
  - Assim os testes exercitam a configuração real de confirms/returns do `application.yaml`.
- **Antes de cada teste:** limpa `outbox_events` e esvazia a fila `regra-submetida`.
- **Cenários** (o job de fixture é inserido direto em `jobs`, com um usuário semeado)

| Cenário | Critério |
| --- | --- |
| Uma transação grava o job e chama `registrar`. Antes do commit, outra conexão não vê nenhum dos dois; depois do commit, vê os dois. | CA1 |
| `registrar` fora de transação lança `IllegalTransactionStateException` e não grava nada. | CA1 |
| Uma transação que chama `registrar` e depois lança exceção faz rollback: não fica job nem linha no outbox. | CA2 |
| `REVOKE INSERT ON outbox_events` faz a transação falhar e o job também não fica. É a "falha no meio" do lado do outbox. | CA2 |
| `rabbitmqctl stop_app` no container, ciclo → `publicado_em` nulo, `tentativas = 1`. Depois `start_app`, ciclo → publicado, `tentativas = 2`, e exatamente uma mensagem na fila, com corpo igual ao payload e `message_id`/`correlation_id`/`type`/`content_type` corretos. | CA3 |
| Fila apagada (mensagem devolvida por `mandatory`) → o evento continua pendente e `tentativas` sobe. Depois a fila é redeclarada, e o ciclo seguinte publica. | CA3 (falha silenciosa) |
| Ciclo depois de publicado → a fila continua com uma mensagem. | CA4 |
| Outra conexão segura a linha com `FOR UPDATE` → o ciclo não publica nada. A outra conexão libera → o ciclo publica uma vez. | CA4 (concorrência) |
| N eventos e 4 threads chamando `publicarPendentes` ao mesmo tempo → exatamente N mensagens na fila, sem duplicata de `message_id`. | CA4 |
| Três eventos, com falha no primeiro → nenhum dos três sai nesse ciclo. No ciclo seguinte, saem na ordem de `criado_em`. | ordem |
| `app.outbox.enabled=true` e `poll-interval=200ms` num contexto próprio → o evento registrado chega à fila sem chamada manual (Awaitility, que já vem no `spring-boot-starter-test`). | CA5 (agendamento real) |

- Para esvaziar e ler a fila, usa `AmqpAdmin.purgeQueue` e `RabbitTemplate.receive`, com os
  beans do próprio contexto.

### `AppPropertiesTests`

Novo `carriesTheOutboxSettings`: afirma `enabled == false` (vindo do perfil de teste) e
`pollInterval == 1s`.

## Arquivos

- Novos:
  - `api/src/main/java/synapse/api/core/outbox/{EventoOutbox,Outbox,PublicadorOutbox,OutboxConfig}.java`
  - `api/src/test/java/synapse/api/core/outbox/OutboxTests.java`
  - `api/.agents/skills/outbox/SKILL.md`
- Alterados:
  - `api/src/main/java/synapse/api/core/config/AppProperties.java`
  - `api/src/main/resources/application.yaml`
  - `api/.env.example`
  - `api/src/test/resources/application-test.properties`
  - `api/src/test/java/synapse/api/core/config/AppPropertiesTests.java`
  - `api/AGENTS.md`
- Fora deste diff:
  - `CriarJobService`, que só passa a usar o outbox em T-040;
  - `contracts/`, `deploy/` e `docs/`. O ponto em aberto "intervalo do poller", em
    ADR-003 §137, pode ser fechado num PR de docs separado, se você quiser.

## Verificação

```bash
cd api
make fmt
make check     # spring-javaformat:validate + compile (Error Prone/NullAway) + testes
```

- `OutboxTests`, `AppPropertiesTests`, `ApiApplicationTests`, `TopologiaRabbitTests` e
  `CriarJobPersistenciaTests` precisam passar. Os de Testcontainers exigem Docker.
- Manual, contra o compose:
  1. Subir `make run`.
  2. Inserir um evento de teste numa transação pelo `psql`.
  3. Conferir no painel do RabbitMQ que a mensagem chega em cerca de 1 s e que
     `publicado_em` é preenchido.
  4. Parar o broker, inserir outro evento e ver `tentativas` subir e o `WARN` no log.
  5. Religar o broker e ver o evento publicado.
- Não precisa de `docker build`: nenhum Dockerfile muda.
