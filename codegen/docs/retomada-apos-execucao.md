# Retomada do grafo após a execução no worker

Desenho da retomada do grafo com `simulacao-concluida`. **Já implementado**: o consumer sobe em
`app/mensageria/broker.py::iniciar_consumers`, a triagem do checkpoint está em
`app/graph/entrypoint.py::resume_to_completion` e a entrega ao `interrupt()` pendente em
`GraphRouter._retomar`. O texto abaixo continua valendo como a justificativa de cada cuidado.

## Onde o grafo para

```
load_rule → code_generation → persist_response → extract_code → dispatch_execution → await_execution ⏸
```

- `dispatch_execution` publica `etapa-alterada` (`delegacao_worker`/`iniciada`, que leva o job a
  `simulando`) e depois `executar-codigo` com `job_id`, `codigo_gerado_id`, `competencias` e
  `orcamento`. A ordem e o motivo estão em [`mensageria.md`](mensageria.md).
- `await_execution` só chama `interrupt({"job_id", "codigo_gerado_id"})`. O checkpoint fica no
  Postgres (`AsyncPostgresSaver`) com `thread_id = job_id`, e `graph.astream(...)` retorna
  normalmente: `run` termina, a `regra-submetida` recebe `ack` e o processo fica livre. Nada fica
  esperando em memória.
- Um grafo pausado tem `(await graph.aget_state(config)).next == ("await_execution",)`, e o valor do
  `interrupt()` aparece em `state.tasks[0].interrupts[0].value`.

## Como retomar

1. Consumir `simulacao-concluida.codegen`. Hoje `ConexaoBroker.iniciar_consumers` só inicia o
   consumer de `regra-submetida`, e `GraphRouter.entregar` recusa as outras mensagens. Enquanto
   isso, os resultados do worker ficam retidos na fila, sem perda.
2. Em `GraphRouter.entregar`, para `SimulacaoConcluida`, chamar o grafo com o **mesmo**
   `thread_id` (`job_id`) e `Command(resume=...)` no lugar do estado inicial:

   ```python
   graph.astream(Command(resume={"resultado_id": ..., "status": ...}), config, ...)
   ```

   O valor de retomada leva só referências e campos de controle (`resultado_id`, `status`). Os
   números da simulação ficam no banco (ADR-001); a LLM nunca os produz.
3. Dentro de `await_execution`, o mesmo `interrupt()` agora **retorna** esse valor. O nó grava
   no estado o que recebeu (por exemplo, `resultado_id` e `status_simulacao`), e uma aresta
   condicional em `engine.py` decide o próximo passo: análise, nova geração ou falha do job.

## Cuidados

- **O nó pausado reexecuta desde a primeira linha.** `await_execution` deve continuar sem efeito
  colateral antes do `interrupt()`. Por isso a publicação fica em `dispatch_execution`, que já
  foi concluído e não roda de novo.
- **Corrida na pausa.** O worker pode publicar `simulacao-concluida` antes de o checkpoint com o
  `interrupt()` pendente ser gravado. Antes de retomar, conferir `aget_state(config)`:
  - sem checkpoint para o `job_id`: `JobDesconhecidoError` (rejeição definitiva);
  - checkpoint existe, mas `next` ainda não é `("await_execution",)`: falha transitória,
    `nack(requeue=True)`;
  - `next` vazio (grafo já retomado e concluído): reentrega, `ack` sem retomar de novo.
- **Resultado de outro código.** Se o grafo gerar código mais de uma vez no mesmo job, conferir
  que o resultado corresponde ao `codigo_gerado_id` do `interrupt()` pendente antes de retomar.
  Hoje `simulacao-concluida` não carrega `codigo_gerado_id`; o vínculo teria de vir de
  `resultados_simulacao` no banco.
- **Comando duplicado.** `codigo_gerado_id` é determinístico (UUID v5 do `prompt_id`), então uma
  reexecução de `dispatch_execution` publica o mesmo comando. Ainda não foi verificado se o worker
  tolera receber o mesmo `executar-codigo` duas vezes.
- **Estado inicial é ignorado na retomada.** Nunca chamar `run` com um estado novo para um job
  pausado: uma entrada que não é `Command(resume=...)` não retoma o `interrupt()` pendente.
