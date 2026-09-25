# Mensageria do codegen (T-049)

## Contratos e topologia

A implementação segue ADR-001, ADR-002, DEC-088 e DEC-089. Usa `aio-pika`,
também adotado pelo worker, com conexão robusta compartilhada, publisher confirms,
publicação obrigatória (`mandatory`) e mensagens persistentes JSON UTF-8 sem envelope.
O corpo é o contrato; `type`, `correlation_id` e `message_id` são propriedades AMQP.

| DTO manual | Direção | Fila / routing key | Exchange |
| --- | --- | --- | --- |
| `RegraSubmetida` | entrada | `regra-submetida` | padrão (`""`) |
| `ParametrosConfirmados` | entrada | `parametros-confirmados` | padrão (`""`) |
| `SimulacaoConcluida` | entrada | `simulacao-concluida.codegen` / `""` | `simulacao-concluida` (fanout) |
| `ExecutarCodigo` | saída | `executar-codigo` | padrão (`""`) |
| `EtapaAlterada` | saída | `etapa-alterada` | padrão (`""`) |
| `NoConcluido` | saída | `no-concluido` | padrão (`""`) |

Os DTOs canônicos ficam em `app/contratos/mensagens.py` e são reutilizados pela
mensageria, sem subclasses de transporte. Os nomes de mensagens e o roteamento
ficam na camada de mensageria. A validação JSON Schema ocorre na fronteira de
transporte, por `app/contratos/validacao.py`, antes de construir o DTO recebido ou
publicar o corpo serializado por `app/contratos/serializacao.py`.

Cada DTO corresponde a `contracts/events/<mensagem>.schema.json`, inclusive
o comando `executar-codigo`. A topologia é durável, não exclusiva, sem auto-delete
e sem argumentos `x-*`. Cada lado declara as filas em que participa de forma
idempotente. O codegen não declara nem consome `simulacao-concluida.api`.

`RegraSubmetida` tem um campo opcional `orcamento` (`Decimal`, `>= 0`, vindo de
`jobs.orcamento`), aditivo ao contrato existente. O estado do grafo o carrega como
texto decimal (nunca `float`) e não o usa para decidir viabilidade - isso é apuração
do worker sobre dados reais.

`scripts/preparar_contratos.py` incorpora dinamicamente todos os schemas, mantendo
os caminhos relativos e removendo cópias obsoletas. O Docker já copia `contracts/`.
O runtime registra os schemas incorporados por `$id`, sem consulta ao monorepo
nem download de referências. Os DTOs são independentes de `EstadoGrafo`.

Números recebidos são decodificados com `simplejson` em `Decimal`. Após validar o
schema, esses decimais são representados como texto apenas no JSON intermediário
entregue ao Pydantic, evitando perda de precisão no parser e preservando `strict=True`
e a conversão de UUIDs e enums a partir de JSON. A saída usa
`use_decimal=True`, mantendo número JSON sem conversão para float. Campos opcionais
ausentes não são emitidos; `null` explícito é recusado pelo schema. Campos adicionais
são ignorados nos DTOs conforme ADR-002. Datas incluem fuso e são verificadas pelo
validador de formatos RFC 3339 de `jsonschema[format-nongpl]`.

Cada producer recebe um DTO pronto, serializa e valida o corpo serializado pelo
schema oficial antes de tocar o broker. Alterações posteriores à construção do DTO
também passam por essa validação. Falha local gera `ProdutorError` sem publicar;
falhas AMQP e mensagens devolvidas pelo broker propagam ao chamador. Uma confirmação
do broker não prova execução pelo worker. Nenhum producer decide quando publicar.

## Entrega ao grafo e confirmações

`RoteadorGrafo.entregar(job_id, mensagem)` é a única fronteira com o grafo.
A implementação injetada deve criar/resolver o grafo inicial, retomar os demais
eventos pelo job_id e retornar apenas quando o processamento estiver persistido.
Deve tolerar reentregas de forma idempotente: uma desconexão pode ocorrer depois
da persistência e antes do ACK. T-049 não implementa nós nem checkpointer.

| Situação | Decisão |
| --- | --- |
| Retorno seguro do roteador | `ack()` |
| Falha de processamento | `nack(requeue=True)` |
| JSON/DTO/schema inválido | `reject(requeue=False)` |
| `JobDesconhecidoError` do roteador | `reject(requeue=False)` e log correlacionado |
| `FalhaDoJobError` do roteador | `reject(requeue=False)`, log correlacionado e `etapa-alterada` com `erro` |
| Cancelamento | sem ACK; fechamento da conexão devolve mensagens não confirmadas |

A rejeição de mensagens inválidas e jobs desconhecidos é a decisão mínima local
para falhas não recuperáveis. **As filas de entrada do codegen não têm DLQ;
essas rejeições descartam a mensagem.** Ausência de roteador configurado não é job
desconhecido: nesse caso nenhum consumer é iniciado e as mensagens ficam nas filas.
Falhas transitórias usam a reentrega do broker, sem republicação/retry manual.
Sem backoff configurado, uma falha persistente pode causar reentregas repetidas.

## Falha permanente do job

`FalhaDoJobError` (`app/falhas.py`) é a classe base das falhas que uma reentrega não
corrige. O `Consumer` tem uma decisão só para todas elas — `reject(requeue=False)`,
nunca `nack` — e cada uma declara a etapa do grafo em que aconteceu:

| Exceção | Onde nasce | Etapa | Por que é permanente |
| --- | --- | --- | --- |
| `RegraInvalidaError` | `app/repositorio/regras.py`, no nó `load_rule` | `geracao_codigo` | a regra referenciada por `regra_id` não existe para o `job_id`, ou falha o contrato de `RepresentacaoRegra`; reentregar não a torna válida |
| `RespostaModeloInvalidaError` | `app/graph/nodes/code_generation.py` | `geracao_codigo` | a resposta veio vazia, bloqueada ou truncada; com `temperature=0` a chamada é determinística, e reentregar só pagaria a mesma resposta inútil de novo |
| `CodigoInvalidoError` | `app/codigo_gerado.py`, no nó `extract_code` | `geracao_codigo` | a resposta já está gravada em `respostas_modelo` e a reentrega continua do checkpoint sobre ela, que seguiria sem um `regra.py` válido |
| `OrcamentoAusenteError` | `app/graph/nodes/dispatch_execution.py` | `delegacao_worker` | o evento não trouxe o `orcamento`, que `executar-codigo` exige, e a ausência nunca é lida como zero |

Antes de rejeitar, o `GraphRouter` publica `etapa-alterada` com `status="erro"` e a etapa
da exceção. **Sem esse aviso a `api` deixaria o job em `gerando_regra` para sempre**: a
rejeição só afeta o broker. A `api` move o job para `erro` e grava a transição com motivo
`erro_<etapa>`. Uma falha ao publicar o aviso não é tratada de propósito: ela sobe como
falha comum, o consumer reenfileira e a reentrega tenta avisar de novo.

Nenhuma dessas exceções carrega conteúdo de artefato, e a mensagem delas nunca vai para
log nem para evento — só a etapa e a correlação do job.

Falha transitória (banco ou broker indisponível, erro de rede do provedor) não é
`FalhaDoJobError`: continua em `nack(requeue=True)`, porque a reentrega é a resposta certa.

Para o comando de saída `executar-codigo`, a
[DEC-091](../../docs/decisoes/dec-091.md) define retry gerenciado pela aplicação no
**worker, lado consumidor**. O producer do codegen apenas publica o comando inicial.
O worker usa o header AMQP `synapse_retry_count` (ausente = zero), com até três
tentativas totais, sem alterar o payload ou o schema. Somente falhas de
infraestrutura permitem retry automático; falhas permanentes e tentativas esgotadas
vão para `executar-codigo.dlq`, declarada pelo worker, sem consumidor automático.
O worker republica uma cópia persistente, aguarda publisher confirm e só então
confirma a original; se a publicação falhar, devolve a original com requeue.
As filas permanecem sem argumentos `x-*`, conforme DEC-089, e não há backoff,
TTL ou plugins. A classificação completa da T-065 e a persistência/publicação de
resultado da T-067 permanecem fora desta camada.

Logs usam o logger do codegen, `job_id_ctx` com restauração ao sair e atributos
operacionais `tipo_mensagem`, `causa` e `decisao`. Não incluem payloads, texto de
exceção ou traceback do processador, que podem carregar dados confidenciais.

## Ciclo de vida e configuração

O lifespan cria o engine assíncrono do banco (`app/db.py`, `asyncpg`) e o
`async_sessionmaker`, roda `checkpointer.setup()` (idempotente), abre a conexão
RabbitMQ robusta, habilita confirmações e limita prefetch (padrão 1), declara
topologia e disponibiliza `aplicacao.state.producers`. `criar_aplicacao(roteador=...)`
injeta a implementação real de `RoteadorGrafo` e inicia **só o consumer de
regra-submetida**; `parametros-confirmados` e `simulacao-concluida` ficam com as
mensagens preservadas no broker até a retomada com `Command(resume=...)` existir.
Sem essa integração, o processo emite um aviso e mantém as mensagens no broker.
`/health` continua sendo liveness do processo.

`GraphRouter` (`app/mensageria/roteamento.py`) é o `RoteadorGrafo` real: traduz
`RegraSubmetida` no estado inicial do grafo e chama
`app/graph/entrypoint.py::run_to_completion`, nunca invocado diretamente pelo
`Consumer`. Ele nasce sem `sessoes`/`producers`; o lifespan os
atribui depois de criar o engine e conectar ao broker, porque `GraphRouter` existe
antes de qualquer um dos dois estar pronto.

Em uma reentrega, o entrypoint continua do último checkpoint do `job_id` em vez de
recomeçar do `START`: os nós já concluídos, como a chamada ao modelo e as gravações, não
rodam de novo.

O nó `dispatch_execution` publica dois eventos, nesta ordem, depois de o prompt, a resposta
e o código estarem gravados:

1. `etapa-alterada` com `etapa="delegacao_worker"` e `status="iniciada"`, que move o job de
   `gerando_regra` para `simulando` na `api`;
2. `executar-codigo`, levando só `codigo_gerado_id`, nunca o código (claim-check, ADR-001).

A ordem é deliberada. `etapa-alterada` é idempotente do lado da `api` — a transição só vale
a partir de `gerando_regra`, então uma segunda cópia não faz nada —, enquanto
`executar-codigo` não é: se o nó rodar de novo, republica o comando. Com o idempotente na
frente, uma reexecução arrisca duplicar só o comando, e o job já está em `simulando` antes
de o worker poder concluir; na ordem inversa, `simulacao-concluida` poderia chegar com o job
ainda em `gerando_regra`, transição que a `api` recusa em silêncio.

Antes disso, ao concluir a extração e a gravação do código, o nó `extract_code` publica
`no-concluido` para a etapa `geracao_codigo`, com `regra_id`, `prompt_id` e
`codigo_gerado_id`. Não é opcional nem só trilha de auditoria: é desse evento que a `api`
cria a linha de `simulacoes`, e é ela que liga o job ao resultado que o worker vai gravar.
Publicar antes de `executar-codigo` é o que garante essa ordem - se o resultado chegasse
primeiro, `SimulacaoConcluidaService` não teria o que amarrar, o cliente nunca receberia o
evento SSE `resultado` e as telas de relatório e histórico ficariam sem o desfecho.

O `evento_id` é determinístico (UUID v5 de `job_id`, etapa e `codigo_gerado_id`), então uma
reexecução do nó republica o mesmo evento e o índice único de `trilhas_auditoria.evento_id`
na `api` reconhece a reentrega. As demais etapas do grafo ainda não publicam `no-concluido`.

Em seguida, `await_execution` pausa o grafo com `interrupt()`, a `regra-submetida` recebe
`ack` e o processo fica livre. A retomada com `simulacao-concluida` está descrita em
[`retomada-apos-execucao.md`](retomada-apos-execucao.md).

O entrypoint Docker/uvicorn chama `app.main:criar_aplicacao_padrao`, que monta um
`GraphRouter` e o passa a `criar_aplicacao`, ativando o consumer de regra-submetida
em produção. `criar_aplicacao` (sem roteador) continua existindo para os testes e
para compor um roteador diferente.

Ao encerrar, cancela as inscrições, aguarda handlers ativos e fecha a conexão
(incluindo canais). Falha na abertura de canal/topologia também fecha a conexão.
Não abre conexão por mensagem, não expõe endpoint HTTP de negócio e não inclui
grafo simulado na aplicação.

Configure `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`,
`RABBITMQ_VHOST` e `RABBITMQ_PREFETCH` pelo ambiente ou `.env`.
Localmente o padrão é `localhost:5672`, usuário/senha `guest`, vhost `/`.
O compose compartilhado injeta host e credenciais no serviço codegen.

## Verificação

Na pasta `codegen/`:

```bash
poetry install
poetry run python scripts/preparar_contratos.py
poetry run pytest -p no:cacheprovider -m 'not rabbitmq'
poetry run ruff check app/ tests/ scripts/
poetry run ruff format --check app/ tests/ scripts/
poetry run mypy app/
poetry run bandit -r app/
poetry check --lock
make pre-commit
```

Os testes de contrato leem os exemplos oficiais da raiz, validam entrada e saída
por um registro independente dos schemas oficiais. A suíte unitária cobre roteamento,
ACK, falhas, decimais, campos opcionais e ciclo de vida.

Para integração, configure `deploy/.env` conforme a instalação do repositório e suba
apenas o broker do compose oficial, a partir da raiz:

```bash
docker compose -f deploy/docker-compose.yml up -d rabbitmq
```

Na pasta `codegen/`, com as mesmas credenciais do broker no ambiente:

```bash
make test-rabbitmq
```

PowerShell sem make:

```powershell
$env:RUN_RABBITMQ_INTEGRATION = '1'
poetry run pytest -p no:cacheprovider -m rabbitmq
Remove-Item Env:RUN_RABBITMQ_INTEGRATION
```

Cada teste cria e remove somente seu próprio vhost `t049-<uuid>` no RabbitMQ real,
usando `docker compose exec ... rabbitmqctl`; não há segundo ambiente RabbitMQ.
As credenciais precisam permitir acesso a esse vhost. São sete cenários: três
entradas sem fila/consumer da API, fanout com cópia independente na fila API sem
consumer, e três producers. Nenhum serviço API ou worker precisa ser iniciado.
Sem `RUN_RABBITMQ_INTEGRATION=1`, esses testes são explicitamente pulados;
habilitados, ausência de broker/Docker é falha, nunca aprovação simulada.
