-- liquibase formatted sql

-- changeset synapse:018-registra-encerramentos-anteriores
-- Jobs que chegaram a um estado terminal antes de existir job-encerrado recebem o evento no
-- outbox, para que o codegen limpe os checkpoints deles. O evento é o que a transição
-- terminal teria gravado: id e instante vêm da linha já persistida em job_transicoes, então
-- nenhuma transição é criada e nenhum instante muda. Um job que já tem job-encerrado no
-- outbox fica de fora, e o INSERT pode rodar de novo sem duplicar o fato.
INSERT INTO outbox_events (job_id, tipo, payload, criado_em)
SELECT DISTINCT ON (t.job_id)
       t.job_id,
       'job-encerrado',
       jsonb_build_object(
           'evento_id', t.id,
           'job_id', t.job_id,
           'status', t.status_novo,
           'encerrado_em', to_char(t.ocorrido_em AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')),
       now()
FROM job_transicoes t
JOIN jobs j ON j.id = t.job_id AND j.status = t.status_novo
WHERE j.status IN ('liberado', 'cancelado', 'arquivado', 'erro')
  AND NOT EXISTS (
      SELECT 1 FROM outbox_events o WHERE o.job_id = t.job_id AND o.tipo = 'job-encerrado')
ORDER BY t.job_id, t.ocorrido_em DESC, t.id DESC;
-- Um evento publicado é um fato anunciado e não volta: não há o que desfazer no schema.
-- rollback SELECT 1;
