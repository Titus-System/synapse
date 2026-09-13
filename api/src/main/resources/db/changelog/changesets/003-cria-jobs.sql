-- liquibase formatted sql

-- changeset synapse:003-cria-jobs
CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    status text NOT NULL,
    usuario_id uuid NOT NULL,
    submissao_id uuid,
    competencias text[] NOT NULL,
    orcamento numeric NOT NULL,
    job_origem_id uuid,
    criado_em timestamptz NOT NULL,
    iniciado_em timestamptz,
    finalizado_em timestamptz,
    tentativas int NOT NULL DEFAULT 0,
    CONSTRAINT fk_jobs_usuario_id FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
    CONSTRAINT fk_jobs_submissao_id FOREIGN KEY (submissao_id) REFERENCES submissoes (id),
    CONSTRAINT fk_jobs_job_origem_id FOREIGN KEY (job_origem_id) REFERENCES jobs (id)
);

CREATE INDEX idx_jobs_submissao_id ON jobs (submissao_id);
CREATE INDEX idx_jobs_usuario_id_criado_em ON jobs (usuario_id, criado_em DESC);
CREATE INDEX idx_jobs_status ON jobs (status);
CREATE INDEX idx_jobs_job_origem_id ON jobs (job_origem_id);

GRANT SELECT, INSERT, UPDATE ON jobs TO ${usuario_api};
-- rollback DROP TABLE jobs;
