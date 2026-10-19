# Mensageria do codegen (T-049)

## Contratos e topologia

A implementação segue ADR-001, ADR-002, DEC-088 e DEC-089. Usa `aio-pika`, também adotado pelo worker, com conexão robusta compartilhada, publisher confirms, publicação obrigatória (`mandatory`) e mensagens persistentes JSON UTF-8 sem envelope. O corpo é o contrato; `type`, `correlation_id` e `message_id` são propriedades AMQP.

| DTO manual | Direção | Fila / routing key | Exchange |
| --- | --- | --- | --- |
| `RegraSubmetida` | entrada | `regra-submetida` | padrão (`""`) |
| `ParametrosConfirmados` | entrada | `parametros-confirmados` | padrão (`""`) |
| `CorrecaoSubmetida` | entrada | `correcao-submetida` | padrão (`""`) |
| `SimulacaoConcluida` | entrada | `simulacao-concluida.codegen` / `""` | `simulacao-concluida` (fanout) |
| `JobEncerrado` | entrada | `job-encerrado` | padrão (`""`) |
| `ExecutarCodigo` | saída | `executar-codigo` | padrão (`""`) |
| `EtapaAlterada` | saída | `etapa-alterada` | padrão (`""`) |
| `NoConcluido` | saída | `no-concluido` | padrão (`""`) |
| `SugestaoAdaptacaoProposta` | saída | `sugestao-adaptacao-proposta` | padrão (`""`) |
| `CorrecaoProposta` | saída | `correcao-proposta` | padrão (`""`) |

Os DTOs canônicos ficam em `app/contratos/mensagens.py` e são reutilizados pela mensageria, sem subclasses de transporte. Os nomes de mensagens e o roteamento ficam na camada de mensageria. A validação JSON Schema ocorre na fronteira de transporte, por `app/contratos/validacao.py`, antes de construir o DTO recebido ou publicar o corpo serializado por `app/contratos/serializacao.py`.

Cada DTO corresponde a `contracts/events/<mensagem>.schema.json`, inclusive o comando `executar-codigo`. A topologia é durável, não exclusiva, sem auto-delete e sem argumentos `x-*`. Cada lado declara as filas em que participa de forma idempotente. O codegen não declara nem consome `simulacao-concluida.api`.

`RegraSubmetida` e `ParametrosConfirmados` têm os campos opcionais `orcamento` (`Decimal`, vindo de `jobs.orcamento`) e `meta_venda` (`Decimal`, vindo de `jobs.meta_venda`), aditivos ao contrato existente. Nenhum dos dois tem limite inferior, como no contrato: o orçamento negativo e a meta zero ou negativa chegam ao grafo como foram ditos, e a validação de domínio os aponta como conflito (T-280). O estado do grafo carrega os dois como texto decimal (nunca `float`), e `dispatch_execution` os repassa a `executar-codigo` quando presentes, com `proposito = simulacao`. O codegen não decide viabilidade com eles, que é apuração do worker sobre dados reais. A recusa do despacho de uma meta zero ou negativa (`MetaVendaInvalidaError`, abaixo) fica como guarda, porque a validação já barra a versão antes da geração.

`scripts/preparar_contratos.py` incorpora dinamicamente todos os schemas, mantendo os caminhos relativos e removendo cópias obsoletas. O Docker já copia `contracts/`. O runtime registra os schemas incorporados por `$id`, sem consulta ao monorepo nem download de referências. Os DTOs são independentes de `EstadoGrafo`.

Números recebidos são decodificados com `simplejson` em `Decimal`. Após validar o schema, esses decimais são representados como texto apenas no JSON intermediário entregue ao Pydantic, evitando perda de precisão no parser e preservando `strict=True` e a conversão de UUIDs e enums a partir de JSON. A saída usa `use_decimal=True`, mantendo número JSON sem conversão para float. Campos opcionais ausentes não são emitidos; `null` explícito é recusado pelo schema. Campos adicionais são ignorados nos DTOs conforme ADR-002. Datas incluem fuso e são verificadas pelo validador de formatos RFC 3339 de `jsonschema[format-nongpl]`.

Cada producer recebe um DTO pronto, serializa e valida o corpo serializado pelo schema oficial antes de tocar o broker. Alterações posteriores à construção do DTO também passam por essa validação. Falha local gera `ProdutorError` sem publicar; falhas AMQP e mensagens devolvidas pelo broker propagam ao chamador. Uma confirmação do broker não prova execução pelo worker. Nenhum producer decide quando publicar.

## Entrega ao grafo e confirmações

`RoteadorGrafo.entregar(job_id, mensagem)` é a única fronteira com o grafo. A implementação injetada deve criar/resolver o grafo inicial, retomar os demais eventos pelo job_id e retornar apenas quando o processamento estiver persistido. Deve tolerar reentregas de forma idempotente: uma desconexão pode ocorrer depois da persistência e antes do ACK. T-049 não implementa nós nem checkpointer.

| Situação | Decisão |
| --- | --- |
| Retorno seguro do roteador | `ack()` |
| Falha de processamento | `nack(requeue=True)` |
| JSON/DTO/schema inválido | `reject(requeue=False)` |
| `JobDesconhecidoError` do roteador | `reject(requeue=False)` e log correlacionado |
| `ContextoAusenteError` do roteador | `reject(requeue=False)`, causa `contexto_ausente`, sem `etapa-alterada` |
| `JobEncerradoError` do roteador | `ack()` sem processar e log correlacionado: mensagem antiga de um job que a `api` encerrou |
| `FalhaDoJobError` do roteador | `reject(requeue=False)`, log correlacionado e `etapa-alterada` com `erro` |
| Cancelamento | sem ACK; fechamento da conexão devolve mensagens não confirmadas |

A rejeição de mensagens inválidas e jobs desconhecidos é a decisão mínima local para falhas não recuperáveis. **As filas de entrada do codegen não têm DLQ; essas rejeições descartam a mensagem.** Ausência de roteador configurado não é job desconhecido: nesse caso nenhum consumer é iniciado e as mensagens ficam nas filas. Falhas transitórias usam a reentrega do broker, sem republicação/retry manual. Sem backoff configurado, uma falha persistente pode causar reentregas repetidas. A indisponibilidade do provedor de LLM é a exceção: ver *Indisponibilidade do provedor* abaixo.

## Confirmação de parâmetros (T-218)

`parametros-confirmados` abre o ciclo da versão `regra_id`, com thread `thread_do_ciclo(job_id, regra_id)`, passando por `run_to_completion`. O estado inicial contém `job_id`, `regra_id`, `competencias` e, quando informados, `orcamento` e `meta_venda` como texto decimal. `origem` não é preenchida. O ciclo começa em `load_rule` e segue pelos nós existentes.

Campos opcionais ausentes preservam compatibilidade com a T-213. Sem competências, o roteador lança `ContextoAusenteError`, independente de `FalhaDoJobError`; o consumer descarta sem requeue e sem levar o job a erro. Sem orçamento ou sem meta, o ciclo segue normalmente e o comando sai sem o campo. Depois de `job-encerrado`, confirmações recebem ACK sem criar checkpoints, inclusive quando a limpeza ainda está pendente.

O guard do entrypoint reutiliza o checkpoint da mesma versão. Ciclo incompleto continua com entrada `None`; finalizado não executa novamente; à espera do worker permanece pausado. `run_to_completion` informa se houve atualização de nó, desconsiderando o sinal `__interrupt__`, para distinguir processamento de duplicatas sem nova execução.

O contador `codegen_parametros_confirmados_total{resultado}` é carregado na composição de `app/main.py` e exposto em `/metrics`. Conta resultados do consumo, não jobs únicos:

| `resultado` | Significado |
| --- | --- |
| `ciclo_aberto` | Entrega que avançou o ciclo até pausa/fim; inclui continuação bem-sucedida após falha transitória |
| `reentrega_ignorada` | Checkpoint não produziu nova execução de nó, inclusive ciclo terminado ou aguardando worker |
| `descartada` | Descarte definitivo por contrato, contexto ausente, job desconhecido/encerrado ou falha permanente |

Falhas transitórias mantêm o log existente e reenfileiram; só o resultado definitivo incrementa o contador. Cancelamento não conta como conclusão. Os logs de resultado levam `job_id` pelo contexto e `regra_id` como referência, quando este é UUID válido. As causas de descarte são fechadas: `contrato_invalido`, `contexto_ausente`, `job_desconhecido`, `job_encerrado` e `falha_do_job`. Nenhum identificador vira label e nenhum artefato vai para telemetria. O `Consumer` restaura a correlação em `finally`.

## Reextração de correções (T-221)

`correcao-submetida` abre o ciclo de reextração da correção `submissao_id`, com thread `thread_da_correcao(job_id, submissao_id)`, no formato `job_id:correcao:submissao_id`. Cada correção é uma submissão distinta, então a reentrega cai no mesmo checkpoint, e o segmento `correcao` impede a colisão com a thread `job_id:regra_id` de um ciclo de regra. O estado inicial leva só `job_id`, `regra_origem_id`, `submissao_correcao_id`, `competencias` e, quando informados, `orcamento` e `meta_venda` como texto decimal. O texto da correção e a regra não entram no estado, que o checkpointer persiste.

A primeira aresta lê campos que o roteador copiou da mensagem validada, nunca saída de modelo: com `submissao_correcao_id`, o grafo começa em `reextract_rule`; sem ele e com `regra_id`, em `load_rule`; sem os dois, em `extract_rule`. O nó termina o ciclo e não pausa.

`reextract_rule` (`app/graph/nodes/reextract_rule.py`) segue uma ordem fixa:

1. `etapa-alterada` com `etapa = extracao_parametros` e `status = iniciada`.
2. A leitura da versão analisada por `buscar_regra(job_id, regra_origem_id)`, que recusa a regra de outro job, e a do texto em `submissoes.transcricao`.
3. O recálculo dos conflitos por `verificar_versao`, a mesma função da validação de domínio, com os parâmetros atuais e os parâmetros que a extração descartou por falta de lastro, para chegar ao resultado que a rodada guarda. Os conflitos, inclusive os dos parâmetros (T-280), entram no prompt como dados do sistema.
4. A chamada ao motor da T-220 (`app/extracao/reextracao.py`) com o modelo `extraction`, os parâmetros atuais e as competências publicadas do vocabulário, e não as do job, para a correção poder levar o período a um mês que o job não tinha.
5. A gravação do prompt e da resposta com `no = extracao_parametros`, ids derivados e `ON CONFLICT DO NOTHING`.
6. `correcao-proposta` com a representação corrigida e o conjunto completo de parâmetros, mesmo quando a correção não os mudou.
7. `no-concluido` com `prompt_id`, `regra_id` igual à versão analisada e `evento_id` derivado da submissão da correção.

Com o ciclo terminado, a reentrega é descartada pelo checkpoint sem chamar o modelo nem publicar, e o roteador registra o log `correção já reextraída, reentrega ignorada`. Depois de uma falha transitória, o nó roda de novo desde o início. Com as mesmas entradas, o prompt é o mesmo, e o nó procura em `prompts` a resposta gravada para ele no job depois da submissão da correção: se ela existe, a reaplica sem chamar o modelo. Uma correção nova com o mesmo texto de uma anterior chama o modelo de novo. Uma segunda chamada poderia trazer outra proposta, e a trilha apontaria um prompt que não gerou a versão aplicada. Uma queda entre `correcao-proposta` e `no-concluido` republica a mesma proposta, que a `api` trata como duplicada, com o mesmo `evento_id` e o mesmo `prompt_id` na trilha.

| Situação | Exceção | Decisão |
| --- | --- | --- |
| Texto ausente ou vazio | `TranscricaoIndisponivelError` | `etapa-alterada` com `erro` e `reject(requeue=False)` |
| Versão inexistente, de outro job ou fora do contrato | `RegraDaCorrecaoIndisponivelError` | o mesmo |
| Resposta do modelo inutilizável | `FalhaExtracaoError` | o mesmo |
| Mensagem sem `competencias`, sem como preservar o período do job | `EntradaReextracaoInvalidaError` | o mesmo |
| Provedor indisponível durante toda a janela | `ProvedorIndisponivelReextracaoError` | o mesmo, com `causa = provedor_indisponivel` |
| Banco, broker ou erro não classificado da chamada ao modelo | `FalhaTransitoriaReextracaoError` | `nack(requeue=True)`, sem `erro` |

Para toda `FalhaDoJobError` de uma `CorrecaoSubmetida`, o `GraphRouter` publica `etapa-alterada` com `etapa = extracao_parametros`, `status = erro`, `regra_id` igual ao `regra_origem_id` e `submissao_id`, qualquer que seja a etapa da exceção. A `api` só reconhece a falha da reextração nessa etapa e com essas referências: fecha a rodada daquela correção e reabre a correção numa rodada pendente nova, sem encerrar o job. Depois de `job-encerrado`, a correção recebe ACK sem abrir ciclo, como a submissão e a confirmação.

O nó registra `reextraction started`, `reextraction finished`, com `prompt_id`, `elementos_por_construto` e `rebaixamentos_por_motivo`, e `reextraction failed`, com `classe`, `motivo` e `operacao`. A conclusão e a falha levam `resposta_reutilizada`, que diz se a resposta veio de uma execução anterior. Os três levam `job_id`, `no = extracao_parametros`, `regra_id` e `submissao_id`, e nunca o texto, o prompt, a resposta, a representação ou os conflitos.

As métricas contam execuções do nó, e a reentrega que o checkpoint descarta não conta. `job_runs_total`, `job_failures_total` e `job_duration_seconds` usam `job_name = reextract_rule`, e a duração é observada também na falha. `codegen_extracao_elementos_total{construto}`, sobre a regra corrigida inteira, `codegen_extracao_rebaixamentos_total{motivo}`, com os rebaixamentos e as operações da correção não aplicadas, e `codegen_extracao_falhas_total{classe}` são os mesmos da extração inicial. A classe `regra_indisponivel` só ocorre nesta origem.

## Encerramento do job e limpeza dos checkpoints

`job-encerrado` chega quando a `api` leva o job a um estado terminal. O `GraphRouter` registra o encerramento em `jobs_grafo_encerrados` e só então confirma a mensagem; uma falha ao registrar reenfileira, porque o fato ainda não está durável, e um job que não existe em `jobs` é rejeitado. Depois do registro, `app/mensageria/limpeza.py` remove os checkpoints, blobs e writes de todos os ciclos do job (`job_id:regra_id`, as reextrações `job_id:correcao:submissao_id` e o legado `job_id`) e preenche `limpo_em` quando nenhum resta.

Toda mensagem de submissão, confirmação ou resultado é processada sob o lock compartilhado do job e consulta o registro antes de tocar o grafo: depois da limpeza ela é confirmada sem efeito (`JobEncerradoError`), e uma submissão ou confirmação de job encerrado nunca recomeça a geração. Um resultado de job encerrado e ainda não limpo é processado normalmente, porque os efeitos dele, como as publicações de auditoria, não podem se perder; a limpeza adia enquanto algum ciclo espera um resultado e é tentada de novo ao fim de cada processamento do job. Uma limpeza interrompida é retomada na subida do serviço, antes de os consumers começarem. A decisão está na [DEC-095](../../docs/decisoes/dec-095.md).

| Log | Quando |
| --- | --- |
| `encerramento do job registrado` | o evento foi gravado (`ja_registrado` diz se era reentrega) |
| `limpeza de checkpoints concluída` | nenhum checkpoint do job resta e `limpo_em` foi preenchido |
| `limpeza de checkpoints adiada` | `processamento_em_andamento` (outra mensagem do job segura o lock) ou `ciclo_pendente` (um ciclo espera o resultado) |
| `limpeza de checkpoints falhou` | a tentativa caiu; só a classe da exceção vai ao log, e a subida retoma |
| `limpezas pendentes retomadas` | na subida, com a quantidade de jobs com `limpo_em` nulo |

`checkpoint_limpezas_total{resultado}` conta tentativas por job encerrado que ainda tinha o que limpar (`concluida`, `adiada`, `falhou`), e `checkpoint_limpeza_duracao_seconds{resultado}` mede cada tentativa.

## Falha permanente do job

`FalhaDoJobError` (`app/falhas.py`) é a classe base das falhas que uma reentrega não corrige. O `Consumer` tem uma decisão só para todas elas — `reject(requeue=False)`, nunca `nack` — e cada uma declara a etapa do grafo em que aconteceu:

| Exceção | Onde nasce | Etapa | Por que é permanente |
| --- | --- | --- | --- |
| `RegraInvalidaError` | `app/repositorio/regras.py`, no nó `load_rule` | `geracao_codigo` | a regra referenciada por `regra_id` não existe para o `job_id`, ou falha o contrato de `RepresentacaoRegra`; reentregar não a torna válida |
| `RespostaModeloInvalidaError` | `app/graph/nodes/code_generation.py` | `geracao_codigo` | a resposta veio vazia, bloqueada ou truncada; com `temperature=0` a chamada é determinística, e reentregar só pagaria a mesma resposta inútil de novo |
| `CodigoInvalidoError` | `app/codigo_gerado.py`, no nó `extract_code` | `geracao_codigo` | a resposta já está gravada em `respostas_modelo` e a reentrega continua do checkpoint sobre ela, que seguiria sem um `regra.py` válido |
| `MetaVendaInvalidaError` | `app/graph/nodes/dispatch_execution.py` | `delegacao_worker` | a meta de venda é zero ou negativa, e `executar-codigo` exige meta positiva; a entrada a aceita como foi dita para a validação de domínio apontá-la (T-280); sem esta falha, o comando seria recusado com um erro que não é `FalhaDoJobError`, a mensagem voltaria à fila e cada reentrega falharia igual |

Antes de rejeitar, o `GraphRouter` publica `etapa-alterada` com `status="erro"` e a etapa da exceção. **Sem esse aviso a `api` deixaria o job em `gerando_regra` para sempre**: a rejeição só afeta o broker. A `api` move o job para `erro` e grava a transição com motivo `erro_<etapa>`. Uma falha ao publicar o aviso não é tratada de propósito: ela sobe como falha comum, o consumer reenfileira e a reentrega tenta avisar de novo.

Nenhuma dessas exceções carrega conteúdo de artefato, e a mensagem delas nunca vai para log nem para evento — só a etapa e a correlação do job.

Falha transitória (banco ou broker indisponível) não é `FalhaDoJobError`: continua em `nack(requeue=True)`, porque a reentrega é a resposta certa. O erro de rede do provedor de LLM é tratado antes disso, pela espera dentro do próprio processamento (ver *Indisponibilidade do provedor* abaixo); só o esgotamento da janela vira `FalhaDoJobError`.

Para o comando de saída `executar-codigo`, a [DEC-091](../../docs/decisoes/dec-091.md) define retry gerenciado pela aplicação no **worker, lado consumidor**. O producer do codegen apenas publica o comando inicial. O worker usa o header AMQP `synapse_retry_count` (ausente = zero), com até três tentativas totais, sem alterar o payload ou o schema. Somente falhas de infraestrutura permitem retry automático; falhas permanentes e tentativas esgotadas vão para `executar-codigo.dlq`, declarada pelo worker, sem consumidor automático. O worker republica uma cópia persistente, aguarda publisher confirm e só então confirma a original; se a publicação falhar, devolve a original com requeue. As filas permanecem sem argumentos `x-*`, conforme DEC-089, e não há backoff, TTL ou plugins. A classificação completa da T-065 e a persistência/publicação de resultado da T-067 permanecem fora desta camada.

Logs usam o logger do codegen, `job_id_ctx` com restauração ao sair e atributos operacionais `tipo_mensagem`, `causa` e `decisao`. Não incluem payloads, texto de exceção ou traceback do processador, que podem carregar dados confidenciais.

## Ciclo de vida e configuração

O lifespan cria o engine assíncrono do banco (`app/db.py`, `asyncpg`) e o `async_sessionmaker`, roda `checkpointer.setup()` (idempotente), abre a conexão RabbitMQ robusta, habilita confirmações e limita prefetch (padrão 1), declara topologia e disponibiliza `aplicacao.state.producers`. `criar_aplicacao(roteador=...)` injeta a implementação real de `RoteadorGrafo` e inicia os consumers de **regra-submetida**, **parametros-confirmados**, **correcao-submetida**, **simulacao-concluida.codegen** e **job-encerrado**. Sem roteador configurado, o processo emite um aviso e mantém as mensagens no broker. `/health` continua sendo liveness do processo.

`GraphRouter` (`app/mensageria/roteamento.py`) é o `RoteadorGrafo` real: traduz `RegraSubmetida`, `ParametrosConfirmados` ou `CorrecaoSubmetida` no estado inicial do grafo e chama `app/graph/entrypoint.py::run_to_completion`, nunca invocado diretamente pelo `Consumer`. Ele nasce sem `sessoes`/`producers`; o lifespan os atribui depois de criar o engine e conectar ao broker, porque `GraphRouter` existe antes de qualquer um dos dois estar pronto.

Em uma reentrega, o entrypoint continua do último checkpoint do ciclo `job_id:regra_id` em vez de recomeçar do `START`: os nós já concluídos, como a chamada ao modelo e as gravações, não rodam de novo.

## Onde cada evento é publicado

| Evento | Onde | Papel |
| --- | --- | --- |
| `etapa-alterada` `geracao_codigo`/`iniciada` | `load_rule`, antes de ler a regra | progresso |
| `no-concluido` `geracao_codigo` | `extract_code`, depois de gravar o código | estrutural + trilha |
| `etapa-alterada` `delegacao_worker`/`iniciada` | `dispatch_execution`, antes do comando | estrutural |
| `no-concluido` `delegacao_worker` | `dispatch_execution`, depois do comando | trilha |
| `etapa-alterada` `decisao`/`iniciada` | `decision`, antes de encaminhar | progresso |
| `no-concluido` `decisao` | `decision`, com o `encaminhamento` | trilha |
| `etapa-alterada` `sugestao_adaptacao`/`iniciada` | `suggest_adaptation`, antes de propor | progresso |
| `sugestao-adaptacao-proposta` | `suggest_adaptation`, quando há alternativa, com a `tentativa` de 1 a 3 | estrutural |
| `etapa-alterada` `sugestao_adaptacao`/`sem_alternativa` | `suggest_adaptation`, quando não há taxa a propor ou a terceira não coube | estrutural |
| `no-concluido` `sugestao_adaptacao` | `suggest_adaptation`, depois da proposta ou do `sem_alternativa` | trilha |
| `etapa-alterada` `extracao_parametros`/`iniciada` | `reextract_rule`, antes de ler a regra e o texto | progresso |
| `correcao-proposta` | `reextract_rule`, depois de gravar o prompt e a resposta | estrutural |
| `no-concluido` `extracao_parametros` | `reextract_rule`, depois da proposta | trilha |
| `etapa-alterada` `status: erro` | `GraphRouter`, em qualquer `FalhaDoJobError`; na reextração, com `regra_id` e `submissao_id` | estrutural |

**Estrutural** quer dizer que o fluxo quebra sem o evento. `delegacao_worker`/`iniciada` é o único caminho que move o job de `gerando_regra` para `simulando`; o `no-concluido` da geração é o que faz a `api` criar a linha de `simulacoes`, sem a qual o resultado do worker não tem a que se amarrar e o cliente nunca recebe o evento SSE `resultado`; e o `erro` é o que impede o job de ficar pendurado. Os outros dois alimentam progresso e trilha, e é por isso que ficaram para trás até serem cobrados: nada quebra quando faltam.

Os `etapa-alterada` com `iniciada` disparam na **entrada** da etapa e os `no-concluido` na **saída** do nó, como os contratos definem; o `sem_alternativa` sai no fim da sugestão, antes do `no-concluido` dela. Só `delegacao_worker`/`iniciada`, `sem_alternativa` e `erro` movem o job; os demais a `api` apenas repassa por SSE.

O `evento_id` de cada `no-concluido` é determinístico (UUID v5 de `job_id`, etapa e `codigo_gerado_id`), então uma reexecução do nó republica o mesmo evento e o índice único de `trilhas_auditoria.evento_id` reconhece a reentrega. A etapa entra na derivação, então as duas linhas da trilha de um mesmo job não colidem.

As referências de cada `no-concluido` seguem a condição de presença declarada campo a campo no schema: o da geração leva `regra_id`, `prompt_id` e `codigo_gerado_id`; o da delegação leva só `regra_id`, porque não produziu código nem chamou modelo. Nenhum dos dois leva `simulacao_id` — quem cria a linha de `simulacoes` é a `api`, com id próprio, de modo que a linha de trilha da delegação fica sem esse vínculo. Fechar isso exigiria o codegen ditar o id no evento da geração, onde o mesmo campo deve estar ausente; fica para a tarefa da trilha completa.

O `executar-codigo` leva só `codigo_gerado_id`, nunca o código (claim-check, ADR-001). Em `dispatch_execution` a ordem é `etapa-alterada` → `executar-codigo` → `no-concluido`. O primeiro vai na frente porque é idempotente do lado da `api`, enquanto o comando não é: assim uma reexecução arrisca duplicar só o comando, e o job já está em `simulando` antes de o worker poder concluir — senão `simulacao-concluida` chegaria com o job ainda em `gerando_regra`, transição que a `api` recusa em silêncio. O `no-concluido` vai por último porque o nó conclui quando o comando foi entregue; anunciar antes afirmaria algo que ainda pode falhar. Isso alarga a janela em que uma falha republica o comando, mas o worker descarta comando repetido pelo `codigo_gerado_id` já gravado.

As demais cinco etapas do vocabulário não existem como nós e seguem sem publicar.

A `sugestao-adaptacao-proposta` é estrutural pelo mesmo motivo da delegação: sem ela a alternativa não vira versão de regra e o job não volta a `gerando_regra`. Ela vai depois do `etapa-alterada` da etapa e antes do `no-concluido`, como em `dispatch_execution` e pela mesma razão. O `sem_alternativa` ocupa o lugar dela quando não há taxa a propor, e é estrutural porque é o que encerra a iteração na `api`, que não espera outra tentativa depois dele. As até três tentativas estão em [`retomada-apos-execucao.md`](retomada-apos-execucao.md#até-três-taxas-novas-por-job). A proposta viaja no corpo, e não por referência, porque a linha em `regras` que a guardaria é justamente o que o evento pede para criar - quem grava é a `api`, dona da versão, do hash canônico e do estado do job.

Em seguida, `await_execution` pausa o grafo com `interrupt()`, a `regra-submetida` recebe `ack` e o processo fica livre. O resultado do worker chega pela fila do fanout e `GraphRouter._retomar` o entrega ao `interrupt()` pendente por `app/graph/entrypoint.py::resume_to_completion`, que antes confere o checkpoint: job sem checkpoint é rejeitado sem requeue, grafo que ainda não pausou é reenfileirado, e grafo já concluído recebe `ack` sem retomar de novo. O desenho está em [`retomada-apos-execucao.md`](retomada-apos-execucao.md).

O valor da retomada leva só `resultado_id`, `status` e `veredito`: os números da simulação ficam em `resultados_simulacao` (ADR-001) e são lidos de lá por quem precisar.

O entrypoint Docker/uvicorn chama `app.main:criar_aplicacao_padrao`, que monta um `GraphRouter` e o passa a `criar_aplicacao`, ativando o consumer de regra-submetida em produção. `criar_aplicacao` (sem roteador) continua existindo para os testes e para compor um roteador diferente.

Ao encerrar, cancela as inscrições, aguarda handlers ativos e fecha a conexão (incluindo canais). Falha na abertura de canal/topologia também fecha a conexão. Não abre conexão por mensagem, não expõe endpoint HTTP de negócio e não inclui grafo simulado na aplicação.

Configure `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `RABBITMQ_VHOST` e `RABBITMQ_PREFETCH` pelo ambiente ou `.env`. Localmente o padrão é `localhost:5672`, usuário/senha `guest`, vhost `/`. O compose compartilhado injeta host e credenciais no serviço codegen.

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

Os testes de contrato leem os exemplos oficiais da raiz, validam entrada e saída por um registro independente dos schemas oficiais. A suíte unitária cobre roteamento, ACK, falhas, decimais, campos opcionais e ciclo de vida.

Para integração, configure `deploy/.env` conforme a instalação do repositório e suba apenas o broker do compose oficial, a partir da raiz:

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

Cada teste cria e remove somente seu próprio vhost `t049-<uuid>` no RabbitMQ real, usando `docker compose exec ... rabbitmqctl`; não há segundo ambiente RabbitMQ. As credenciais precisam permitir acesso a esse vhost. Os cenários cobrem entradas, encerramento, fanout e producers. O teste de `parametros-confirmados` publica mensagem válida, duplicata, mensagem sem contexto, contexto inválido e JSON malformado; passa pelo consumer, roteador e grafo reais, substituindo banco, modelo e produtores do grafo. Depois que os callbacks completam ACK/reject, consulta a fila passivamente e exige um consumer, profundidade zero e uma única delegação ao worker. O teste da taxa nova faz a api e o worker pelo broker: a cada ciclo publica `regra-submetida`, lê o `executar-codigo` e publica o resultado inviável no fanout, até as três propostas e o `sem_alternativa`, conferidos contra os schemas, sem quarta proposta e com as filas de entrada vazias. Nenhum serviço API ou worker precisa ser iniciado. Sem `RUN_RABBITMQ_INTEGRATION=1`, esses testes são explicitamente pulados; habilitados, ausência de broker/Docker é falha, nunca aprovação simulada.

## Indisponibilidade do provedor de LLM (T-268)

Falhas da chamada ao modelo que indicam provedor indisponível (HTTP 429, 500, 502, 503 e 504, timeout e erro de conexão, inclusive embrulhados pelo `langchain_google_genai`) não sobem como falha transitória. `app/graph/core/llm/disponibilidade.py` espera dentro do processamento da mensagem, antes do `ack`, nos nós `geracao_codigo` e `extracao_parametros`:

- A primeira falha publica `etapa-alterada` com `status = aguardando_provedor`, uma vez por chamada. O aviso não muda o estado do job.
- As esperas são de 30, 60 e 120 segundos e depois 120 segundos, dentro de uma janela de 10 minutos contada da primeira falha, que fica abaixo do `consumer_timeout` de 30 minutos do RabbitMQ. O `max_retries=2` do SDK não muda.
- Antes de cada nova tentativa o codegen consulta `jobs_grafo_encerrados`. Um job cancelado ou arquivado na espera lança `JobEncerradoDuranteEsperaError`, que o roteador converte em `JobEncerradoError` (ACK, sem aviso de erro).
- Esgotada a janela, o nó lança `ProvedorIndisponivelError` (`FalhaDoJobError`): o roteador publica `etapa-alterada` com `erro` e `causa = provedor_indisponivel`, e o consumer rejeita sem requeue.
- Logs (`causa = provedor_indisponivel`, sem a mensagem do provedor) e métricas `llm_provider_failures_total{no,desfecho}` e `llm_provider_wait_seconds{no}`. O contador conta chamadas com falha de provedor por desfecho (`recuperado` ou `esgotado`), não cada tentativa.
- Uma reentrega depois de queda do processo reinicia a janela e pode repetir o aviso.
