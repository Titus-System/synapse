---
name: correction-loop
description: Como a api implementa o loop de correção - os nomes atuais das classes que as tarefas do E3 citam, por que as rodadas moram no pacote `job`, como a fatia `submissoes` chega ao domínio sem tocar no repositório nem perder a autorização, as transições novas, os consumidores de `etapa-alterada` e `correcao-proposta`, o outbox de `correcao-submetida` e `parametros-confirmados`, o fechamento das rodadas na confirmação direta e no cancelamento, e as armadilhas do código atual. Use ao implementar T-214 a T-217 ou T-225, ou ao depurar uma rodada que não abriu, não fechou ou abriu duas vezes.
---

# Loop de correção na api

Leia antes a skill da raiz [`correction-loop`](../../../../.agents/skills/correction-loop/SKILL.md). A tabela de transições conjuntas de lá é o que cada peça daqui implementa. Esta skill diz onde e como, no código da api.

## Os nomes que as tarefas usam

As tarefas do E3 foram escritas antes da reorganização do pacote `job` e citam classes que não existem mais. Os equivalentes atuais:

| Nome nas tarefas | Onde está |
| --- | --- |
| `EtapaAlteradaService` | `JobEventosService.aplicarEtapaAlterada` |
| `SugestaoAdaptacaoService` | `JobEventosService.aplicarSugestaoAdaptacao` |
| `ConfirmarParametrosService` | `JobService.confirmar` |
| `ExecutarAcaoService` | `JobService.executarAcao` |
| `CriarJobService` (gravação da submissão) | `JobService`, por `JobRepository.inserirSubmissao` |
| `ConfirmarParametrosController`, `ConfirmarParametrosAdvice` | `JobController`, `JobAdvice` |
| `AutorizarJob` e os interceptors | `AutorizacaoJobs.java`: `@AutorizarJob`, `OperacaoJob`, `AutorizadorDeJob` |
| `EtapaAlteradaConsumidor`, `SugestaoAdaptacaoConsumidor` | `ConsumidoresJob.java` |
| `EtapaAlteradaDto` e os demais DTOs de fila | `MensagensRecebidasJob.java` e `MensagensPublicadasJob.java` |
| `EventoEtapaDto`, `EventoEstadoDto` | `EventosSseJob.java` |

## As rodadas moram no pacote `job`

Toda mudança de rodada acontece junto com uma leitura do job sob trava, uma transição de estado, uma versão de regra ou um evento de outbox. `MaquinaDeEstadosDoJob`, `VersoesDaRegra`, `JobRepository` e o `Outbox` já estão ao alcance package-private do pacote `job`. Uma fatia `rodada` separada precisaria de todos eles como API pública, que é o acoplamento que a skill [`architecture`](../architecture/SKILL.md) evita.

- O repositório das rodadas fica no pacote `job`, com `JdbcTemplate` e parâmetros bind, como `JobRepository`.
- O estado é um enum package-private com `paraColuna` e `deColuna`, no molde de `JobStatus`. `pendente` e `em_reextracao` são os abertos.
- A resposta `Rodada` é um record em `RespostasJob.java`. `correcao` sai de um join com `submissoes` pelo `submissao_correcao_id`: `texto` vem de `transcricao` e `enviada_em` de `criado_em`. Fica nula enquanto não há submissão.
- Quando uma rodada nova sucede a última do job, `rodada_anterior_id` aponta para a mais recente pela ordem de criação, aberta ou fechada.

## A fatia `submissoes` e a autorização

`POST /submissoes` vive num pacote próprio, `synapse.api.submissoes`. A entrada inicial por texto e voz (E4) também chega por ele, e a primeira tarefa integrada cria o pacote. A fatia grava a linha em `submissoes` com SQL próprio, sem reaproveitar `JobRepository`. Duplicar um `INSERT` custa menos que expor o repositório do job.

**O interceptor de autorização não cobre esta rota.** `AutorizacaoJobsConfig` registra o interceptor só em `/jobs` e `/jobs/**`, e o Spring Security exige apenas autenticação no resto. Sem uma conferência explícita, qualquer usuário autenticado, inclusive o auditor, corrigiria o job de outra pessoa. A rota precisa exigir o papel `PROFISSIONAL_RH` e a posse sobre o `job_id` do corpo antes de gravar qualquer coisa. `AutorizadorDeJob` é package-private, então a conferência entra na operação pública do `job` que a fatia chama, e não numa cópia dentro de `submissoes`.

A operação pública do `job` faz o resto, nesta ordem:

1. Trava o job e confere posse, estado `aguardando_confirmacao_parametros` e rodada `pendente`.
2. Muda a rodada para `em_reextracao` e grava `submissao_correcao_id`.
3. Registra `correcao-submetida` no outbox, com `regra_origem_id` igual à `regra_analisada_id` da rodada e as competências do job.
4. Devolve à fatia o necessário para `SubmissaoCriada`: o status do job e a rodada já atualizada.

Declare essa operação com `@Transactional(propagation = Propagation.MANDATORY)`. Assim ela só roda dentro da transação da fatia que gravou a submissão, e "gravar a submissão e mudar a rodada na mesma transação" deixa de depender de quem chama. As recusas são `RuntimeException`, para que o rollback desfaça a submissão já inserida.

A fatia tem o próprio `@RestControllerAdvice` e o próprio record de erro, porque `ErroDto` é package-private no `job`. Códigos: 400 `requisicao_invalida` (finalidade, tipo ou texto inválidos, texto vazio depois de `strip()` ou com mais de 4000 caracteres), 403 `sem_permissao`, 404 `job_nao_encontrado` e 409 `estado_invalido`, este com uma mensagem para o job fora da espera e outra para a falta de rodada pendente.

O `CorrelationFilter` só limpa o MDC. Abra `CorrelationContext` com o `job_id` do corpo assim que ele for lido e validado, porque nenhum filtro o extrai do caminho.

## Máquina de estados

- Acrescente `GERANDO_REGRA → AGUARDANDO_CONFIRMACAO_PARAMETROS` em `JobStatus`. As transições `AGUARDANDO_CONFIRMACAO_PARAMETROS → GERANDO_REGRA` e `→ CANCELADO` já existem.
- Pausa: `maquina.avancarSeEm(jobId, GERANDO_REGRA, AGUARDANDO_CONFIRMACAO_PARAMETROS, "evento", "validacao_com_conflitos")`.
- Correção aplicada: `maquina.avancarSeEm(jobId, AGUARDANDO_CONFIRMACAO_PARAMETROS, GERANDO_REGRA, "evento", "correcao_aplicada")`.
- `validacao_com_conflitos` é espera, não parada. Confira que `MotivoDaParada.razaoLocalizada` não o traduz como razão de parada e que `GET /jobs/{id}` não o devolve em `motivo`.

## `etapa-alterada` (T-215)

`EtapaAlteradaDto` ganha `regra_id` e `conflitos`, ambos `@Nullable`. Receba `conflitos` como `JsonNode`, e não como lista tipada. A rodada guarda os conflitos exatamente como chegaram, e o SSE os repassa como chegaram. Um record tipado descartaria em silêncio um campo que o codegen acrescentar aos itens numa evolução aditiva do contrato. Confira só que é um array não vazio.

Em `JobEventosService.aplicarEtapaAlterada`, leia o status do job sob trava uma vez e ramifique por ele:

1. `confirmacao` + `aguardando_correcao` com `regra_id` e `conflitos`: primeiro confira se já existe rodada para `(job_id, regra_id)` e se `regra_id` é a versão mais recente do job. Só depois tente a transição. A ordem importa: uma pausa reentregue de uma versão antiga encontra o job em `gerando_regra` por causa da versão nova, e a transição viria primeiro e pausaria o ciclo errado.
2. `extracao_parametros` + `erro` com o job em `aguardando_confirmacao_parametros` e uma rodada `em_reextracao`: fecha a rodada como `reextracao_falhou` e abre a `pendente` nova, copiando `conflitos` e `regra_analisada_id`. O job não muda.
3. Os ramos existentes (`delegacao_worker` iniciada e `erro` a partir de `gerando_regra`) continuam como estão.

O serviço devolve ao consumidor o que ele precisa emitir. `EtapaAlteradaConsumidor` continua emitindo depois de o serviço retornar, que é depois do commit, e mantém a ordem `etapa` antes de `estado` da skill [`sse`](../sse/SKILL.md). `EventoEtapaDto` ganha `conflitos` com `@JsonInclude(NON_NULL)`, como `EventoEstadoDto` já faz: o contrato SSE não aceita `conflitos: null`. `regra_id` não vai ao SSE, porque o contrato HTTP não o declara em `EventoEtapa`.

## `correcao-proposta` (T-217)

O modelo é `SugestaoAdaptacaoConsumidor` com `aplicarSugestaoAdaptacao`: valida os campos obrigatórios no consumidor, abre a correlação, delega a um método `@Transactional` que trava o job e grava a versão e o outbox, e emite o SSE `estado` depois.

**`HashDaRegra.calcular` lança `NullPointerException` sem `percentual`.** Ele faz `Objects.requireNonNull(nucleo.percentual())`, e `regra-nucleo.schema.json` não exige o campo. Percentual ausente é justamente um conflito que a validação aponta, e uma correção pode não resolvê-lo. Sem tratamento, a exceção sobe do consumidor, a mensagem volta à fila e entra em loop. O hash canônico precisa aceitar núcleo incompleto antes de gravar versões vindas de correção, e o mesmo vale para a regra extraída (`regra-extraida`, T-202). `aplicarSugestaoAdaptacao` só escapa porque recusa antes uma sugestão sem percentual positivo.

O restante, numa transação:

- A rodada `em_reextracao` para `regra_origem_id` é a chave de idempotência. Sem ela (proposta já aplicada, rodada abandonada, job fora da espera), a mensagem é descartada com log e confirmada.
- Se o hash já existe no job, `VersoesDaRegra.resolver` devolveria a versão antiga. Trate como falha da reextração, como a `erro` do item anterior, sem transição e sem publicar.
- Senão: `versoes.resolver(..., "correcao", regraOrigemId, ...)`, a rodada vai a `corrigida` com `regra_resultante_id`, o job vai a `gerando_regra`, a linha da trilha do nó `confirmacao` sai pela mesma comparação de versões de `JobService.confirmar`, e `parametros-confirmados` vai para o outbox.
- A representação é gravada como chegou. O hash canônico serve só para deduplicar.

## Outbox e topologia

- `EventoOutbox` ganha `CORRECAO_SUBMETIDA`. `RabbitTopologyConfig` ganha as constantes e declara `correcao-submetida` e `correcao-proposta`: duráveis e sem argumentos, como as demais (DEC-089). O codegen publica com `mandatory`, e uma fila ainda não declarada faz a publicação dele falhar.
- `ParametrosConfirmadosDto` ganha `competencias` e `orcamento`, lidos de `jobs`, e passa a ser `@JsonInclude(NON_NULL)`, como `RegraSubmetidaDto`: o schema recusa `null` explícito, e um job sem orçamento omite o campo. Todo `parametros-confirmados` passa a levá-los, inclusive o de `JobService.confirmar`.
- `CorrecaoSubmetidaDto` vai em `MensagensPublicadasJob.java`.

## Confirmação direta e abandono

- `JobService.confirmar` (T-217): com uma rodada aberta, feche-a como `corrigida` com a versão confirmada, na mesma transação. Se `VersoesDaRegra.resolver` devolver uma versão que já existia, decida explicitamente o que publicar. O codegen não reabre o ciclo de um `regra_id` que já terminou, e um job em `gerando_regra` sem ciclo vivo fica parado.
- `JobService.executarAcao` (T-225): depois de uma transição bem-sucedida para `cancelado` ou `arquivado`, marque as rodadas abertas como `abandonada` na mesma transação, alterando só `estado` e `atualizada_em`.

## Testes

- Consumidores: teste de integração com Postgres e RabbitMQ reais, no padrão de `EtapaAlteradaConsumidorTests`, publicando na fila como o codegen publicaria. Confira as linhas de `rodadas_correcao`, `job_transicoes` e o stream SSE.
- Contrato: em `ExemplosDeContratoTests`, desserialize `etapa-alterada-conflitos.json`, `etapa-alterada-falha-reextracao.json` e `correcao-proposta.json` com `FAIL_ON_UNKNOWN_PROPERTIES`. Valide tudo o que a api produz pelo contrato real: `ContratoDeEvento.validar` para `correcao-submetida` e `parametros-confirmados`, `validarEventoDoStream` para o `etapa` com conflitos e `validarRespostaHttp` para `Rodada` e `SubmissaoCriada`.
- Banco (T-214): `MigrationTests` para a estrutura e os dois índices parciais, e `PermissoesDeBancoTests` para `SELECT, INSERT, UPDATE` da api e só `SELECT` do codegen.
- Concorrência: duas correções simultâneas para o mesmo job resultam em um 201 e um 409, e duas pausas iguais em uma rodada só.
- Reentrega: cada consumidor recebe a mesma mensagem duas vezes e produz um único efeito, com a segunda contada como `duplicada`.

## Observabilidade

Siga as skills [`logging`](../logging/SKILL.md) e [`metrics`](../metrics/SKILL.md). Cada passo do loop tem um contador com label `resultado` de conjunto fechado, conforme a tarefa. A reentrega conta como `duplicada`, nunca como um segundo resultado de negócio.

As métricas ficam em **`GET /metrics`**, e não em `/actuator/prometheus` como algumas tarefas dizem: o endpoint `prometheus` do Actuator foi remapeado (skill `metrics`). Confira as amostras ali depois de exercitar cada resultado, num teste no molde de `MetricsEndpointTests`.

Logs levam `job_id`, `regra_id`, o id da rodada e contagens de conflitos, nunca o `motivo`, o texto da correção ou a representação.
