# Retomada do grafo após a execução no worker

O consumer de `simulacao-concluida.codegen` entrega o resultado ao checkpoint que solicitou
sua execução. Cada versão tem seu próprio `thread_id = job_id:regra_id`; a regra é resolvida
pelo vínculo `resultados_simulacao.codigo_gerado_id → codigos_gerados.regra_id`.
Se não houver checkpoint versionado, o entrypoint consulta o identificador antigo `job_id`
e só o reutiliza quando o estado contém o mesmo job e a mesma regra. A compatibilidade
vale tanto para resultados quanto para reentregas da submissão, sem copiar checkpoints,
repetir geração ou confundir a candidata com o ciclo original. Um checkpoint versionado
existente tem prioridade.

```text
load_rule → code_generation → persist_response → extract_code → dispatch_execution
→ await_execution ⏸ → decision → suggest_adaptation → fim
                             ↘ fim
```

`dispatch_execution` publica o comando com código, competências e orçamento. O nó
`await_execution` só interrompe: efeitos anteriores ao `interrupt()` seriam repetidos
quando o grafo fosse retomado. A retomada leva referências e status, nunca números gerados
por modelo. O worker calcula os totais sobre os dados históricos.

## Reentregas e falhas

- Sem checkpoint: o resultado é desconhecido; a mensagem é rejeitada.
- Checkpoint anterior à pausa: reentregar, pois o resultado pode chegar antes da persistência
  do `interrupt()`.
- Na pausa: entregar `Command(resume=...)`.
- Resultado já registrado e nós posteriores pendentes: continuar com entrada `None`. Isso
  recupera falhas transitórias na publicação da sugestão sem repetir a geração nem perder
  o resultado recebido.
- Grafo concluído: confirmar a reentrega sem iniciar outro ciclo.

Os artefatos e eventos de auditoria têm identificadores determinísticos. O worker deduplica
pelo par job/código, preservando a independência entre a simulação original e a alternativa.

## Uma alternativa por job

Só `status=sucesso` com `veredito=inviavel` e sem versão de sugestão existente encaminha
para `suggest_adaptation`. O candidato altera exclusivamente o percentual do núcleo:
`percentual × (orçamento − baseline) / (simulado − baseline)`, truncado em quatro casas
decimais. A estimativa só se aplica a regras sem especificações e quando
`0 ≤ baseline < orçamento < simulado`. Ela é conservadora quando já havia comissão nas
linhas afetadas; o veredito só existe após nova execução no worker. Percentual sem margem
positiva, representação incoerente ou regra fora desse recorte não produz proposta.
Ausência de proposta significa ausência de estimativa suportada, não impossibilidade
matemática de caber no orçamento. O resultado e o caminho de revisão originais permanecem.


O evento `sugestao-adaptacao-proposta` entrega a candidata à API, que valida sua procedência,
cria a versão e publica `regra-submetida` com orçamento e competências. Usar
`parametros-confirmados` aqui não fornece esses dados, e o codegen não consulta `jobs`.
A API confere a tentativa única sob trava do job, inclusive em reentregas tardias.

O fluxo completo e sua apresentação estão em
[`docs/SUGESTAO-ADAPTACAO.md`](../../docs/SUGESTAO-ADAPTACAO.md).
