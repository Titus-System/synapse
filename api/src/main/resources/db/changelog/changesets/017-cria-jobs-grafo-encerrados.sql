-- liquibase formatted sql

-- changeset synapse:017-cria-jobs-grafo-encerrados
CREATE TABLE jobs_grafo_encerrados (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    evento_id uuid NOT NULL,
    status text NOT NULL,
    encerrado_em timestamptz NOT NULL,
    limpo_em timestamptz,
    CONSTRAINT fk_jobs_grafo_encerrados_job_id FOREIGN KEY (job_id) REFERENCES jobs (id)
);

CREATE UNIQUE INDEX uq_jobs_grafo_encerrados_job_id ON jobs_grafo_encerrados (job_id);

-- Parcial: a retomada na subida do codegen só procura as limpezas que não terminaram.
CREATE INDEX idx_jobs_grafo_encerrados_pendentes ON jobs_grafo_encerrados (job_id)
    WHERE limpo_em IS NULL;

-- O codegen registra o encerramento e marca a limpeza; não altera o encerramento registrado
-- nem apaga a linha, que sustenta o reconhecimento de reentregas depois da limpeza.
GRANT SELECT, INSERT ON jobs_grafo_encerrados TO ${usuario_codegen};
GRANT UPDATE (limpo_em) ON jobs_grafo_encerrados TO ${usuario_codegen};
-- rollback DROP TABLE jobs_grafo_encerrados;
