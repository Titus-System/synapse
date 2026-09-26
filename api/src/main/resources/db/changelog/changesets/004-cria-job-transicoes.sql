-- liquibase formatted sql

-- changeset synapse:004-cria-job-transicoes
CREATE TABLE job_transicoes (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    status_anterior text,
    status_novo text NOT NULL,
    ocorrido_em timestamptz NOT NULL,
    ator text NOT NULL,
    motivo text,
    CONSTRAINT fk_job_transicoes_job_id FOREIGN KEY (job_id) REFERENCES jobs (id)
);

CREATE INDEX idx_job_transicoes_job_id_ocorrido_em ON job_transicoes (job_id, ocorrido_em);

GRANT SELECT, INSERT ON job_transicoes TO ${usuario_api};
-- rollback DROP TABLE job_transicoes;
