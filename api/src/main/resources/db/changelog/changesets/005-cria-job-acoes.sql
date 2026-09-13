-- liquibase formatted sql

-- changeset synapse:005-cria-job-acoes
CREATE TABLE job_acoes (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    acao text NOT NULL,
    executado_em timestamptz NOT NULL,
    CONSTRAINT fk_job_acoes_job_id FOREIGN KEY (job_id) REFERENCES jobs (id)
);

CREATE INDEX idx_job_acoes_job_id_executado_em ON job_acoes (job_id, executado_em);
-- rollback DROP TABLE job_acoes;
