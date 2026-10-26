-- liquibase formatted sql

-- changeset synapse:030-inclui-em-transcricao-nas-rodadas-abertas
DROP INDEX uq_rodadas_correcao_job_id_aberta;

CREATE UNIQUE INDEX uq_rodadas_correcao_job_id_aberta ON rodadas_correcao (job_id)
WHERE estado IN ('pendente', 'em_transcricao', 'em_reextracao');

-- rollback DROP INDEX uq_rodadas_correcao_job_id_aberta;
-- rollback CREATE UNIQUE INDEX uq_rodadas_correcao_job_id_aberta ON rodadas_correcao (job_id) WHERE estado IN ('pendente', 'em_reextracao');
