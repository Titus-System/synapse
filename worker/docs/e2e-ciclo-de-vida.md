# E2E do ciclo de vida do worker

Testes que tratam o worker como **caixa-preta**: sobem o processo de verdade
(`uvicorn app.main:create_app --factory`, o mesmo comando do container), publicam um comando no
RabbitMQ, esperam o evento e conferem o que sobrou no banco, nas filas, no Docker e no log. Nada do
worker é importado nem substituído. É o que garante que o ciclo do worker (T-063 a T-067) fecha: todo
comando que entra termina, e termina de um jeito que dá para consultar.

```bash
make e2e        # ou: poetry run pytest -m e2e tests/e2e -v
```

Pedem o compose de pé (`docker compose -f deploy/docker-compose.yml up -d postgres rabbitmq`), o daemon
Docker e a imagem do sandbox, que a fixture `imagem` constrói uma vez (ou reusa
`SANDBOX_IMAGE_TESTE=<tag>`). Levam alguns minutos, e por isso ficam **fora do `verify.sh` e do
`make test`** (o marcador `e2e` é excluído por padrão em `pyproject.toml`).

## Como isolam

- **Um vhost novo do RabbitMQ por teste.** Um worker do compose de pé não vê nem rouba as mensagens, e
  nada do compose é tocado. O worker de teste recebe `RABBITMQ_VHOST` e `SANDBOX_IMAGE` por ambiente.
- **O Postgres é o do compose**, e o dono do schema semeia e limpa a cadeia job, regra, prompt e código
  (`tests/semente.py`), porque o worker só tem `SELECT` e `INSERT`.
- **O processo roda numa pasta temporária**, então o `logs/app.json` dele não suja o repositório.
- O teste declara, no vhost, as filas que a `api` e o codegen declaram ao subir
  (`simulacao-concluida.api` e `.codegen`), e as lê. Nenhum dos dois serviços sobe.

## O que garantem

| Garantia | Teste |
| --- | --- |
| `sucesso` grava **uma** linha e publica o mesmo evento nas duas filas, com o veredito pelo orçamento do comando | `test_desfechos::test_sucesso_grava_a_linha_e_publica_o_evento_nas_duas_filas` |
| asserção violada é categoria própria, sem veredito | `test_assercao_violada_e_categoria_propria_e_sem_veredito` |
| erro da regra é `erro_codigo` e **nada da regra** (exceção, stdout, stderr, fonte) nem o orçamento chega ao log | `test_erro_do_codigo_e_erro_codigo_e_nada_da_regra_chega_ao_log` |
| código que não termina é morto no prazo real de 60 s e o ciclo fecha | `test_codigo_que_nao_termina_e_morto_no_prazo_e_o_ciclo_fecha` |
| sem a imagem do sandbox: três tentativas, `erro_infra` gravado e publicado uma vez, comando na DLQ (DEC-094) | `test_infra_esgotada_grava_e_publica_erro_infra_e_so_entao_vai_a_dlq` |
| comando inválido, código inexistente e par job/código incoerente vão à DLQ sem linha nem evento, e não travam a fila | `test_comando_ruim_vai_a_dlq_e_nao_trava_a_fila` |
| todo log do processamento carrega o `job_id` | `test_todo_log_do_processamento_carrega_o_job_id` |
| comando duplicado republica o evento, sem segunda linha nem segunda execução | `test_reentrega::test_comando_duplicado_nao_duplica_a_linha_nem_executa_de_novo` |
| `kill -9` no meio da execução: o comando volta, um segundo worker o conclui, uma linha e um evento | `test_worker_morto_no_meio_da_execucao_nao_perde_o_comando` |
| SIGTERM no meio da execução: o comando não se perde e o job termina com uma linha | `test_processo::test_sigterm_no_meio_da_execucao_nao_perde_o_comando` |
| SIGTERM no meio da execução: o container é morto e removido, dentro dos 10 s do `docker stop` | `test_sigterm_no_meio_da_execucao_mata_e_remove_o_container_dentro_do_prazo_do_docker_stop` |
| toda linha de log do processo segue o schema do monorepo | `test_os_logs_do_processo_seguem_o_schema_de_log_do_monorepo` |
| sobe pronto, com a topologia e um consumidor | `test_sobe_pronto_com_a_topologia_e_um_consumidor` |
| SIGTERM ocioso encerra limpo e solta o consumidor | `test_sigterm_ocioso_encerra_limpo_e_solta_o_consumidor` |
| `/health` responde em menos de 1 s enquanto um container executa (o loop não trava) | `test_health_responde_enquanto_o_container_executa` |
| `prefetch` 1: um comando de cada vez | `test_dois_comandos_sao_processados_um_de_cada_vez` |
| sem acesso ao daemon Docker o worker recusa subir, e não toca nos comandos da fila | `test_sem_acesso_ao_daemon_docker_o_worker_recusa_subir` e `test_worker_que_nao_sobe_nao_toca_nos_comandos_da_fila` |

Em **todo** desfecho `fechar_o_ciclo` confere o mesmo: a fila do comando vazia (nada pronto e nada sem
`ack`, lido do broker por `rabbitmqctl`, que enxerga o que um `get` não vê), a DLQ com a quantidade
esperada, nenhum container do job e o processo vivo.

Os testes foram validados por mutação: sem a consulta prévia, com `ack` antes de processar, com o
container no loop, com o stderr da regra no log, sem o registro do esgotamento e sem a guarda do
`job_id`, cada um derruba o e2e correspondente.

## O que o e2e encontrou (e já foi corrigido)

Duas lacunas anteriores à T-067 apareceram no primeiro dia do e2e, ficaram registradas como `xfail`
com motivo, e foram corrigidas (os testes agora passam, sem marcador):

1. **SIGTERM no meio da execução deixava o container do sandbox órfão.** O uvicorn encerra de forma
   graciosa e reemite o SIGTERM, e o processo morre (`-15`, o 143 do `docker stop`) sem esperar
   threads: a thread do container nunca chegava ao `finally: remove`, e como o prazo de 60 s é
   imposto pelo worker, um código que não termina ficava rodando sem quem o parasse. **Correção:**
   a execução é cancelável (`executar_no_sandbox(..., cancelar=Event)`, com a espera em passos de
   0,5 s) e o consumidor, ao ser cancelado, marca o pedido e **espera** a thread limpar antes de
   deixar o cancelamento seguir. A remoção forçada (`remove(force=True)`) mata e remove o container
   numa chamada só. O e2e mede que o desligamento cabe nos 10 s do `docker stop`.
   `test_sigterm_no_meio_da_execucao_mata_e_remove_o_container_dentro_do_prazo_do_docker_stop`.
2. **Os logs não seguiam `contracts/observability/log.schema.json`.** O worker emitia `service`,
   `version` e `host`; o schema exige `service.name` e prevê `service.version` e `host.name`, e a
   localização vai sob `code`. **Correção:** o `JsonFormatter` emite o envelope do schema, o mesmo do
   codegen. Um teste unitário valida o envelope contra o schema, e o e2e valida toda linha do
   processo real. `test_os_logs_do_processo_seguem_o_schema_de_log_do_monorepo`.

O que **não** muda: `kill -9` (e a queda da máquina) ainda deixa o container do job órfão, porque não
há código que rode depois de um SIGKILL. É o que o watchdog (T-068) fecha, e por isso o e2e do
`kill -9` só exige que o container do **segundo** worker seja removido.

## Fora do e2e

- **A `api` e o codegen reais.** Os testes fazem o papel dos dois (declaram a fila, ligam e leem); a
  integração entre os três serviços exigiria subir o compose inteiro e atravessa componentes.
- **A imagem do worker.** O processo roda do código-fonte, e não de `docker run` da imagem: o
  `Dockerfile`, o grupo do socket e a cópia dos baselines não são exercitados aqui.
- **Queda do RabbitMQ ou do Postgres no meio de um job.**
