-- liquibase formatted sql

-- changeset synapse:006-cria-regras
CREATE TABLE regras (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    versao int NOT NULL,
    origem text NOT NULL,
    regra_origem_id uuid,
    nucleo jsonb NOT NULL,
    especificacoes jsonb NOT NULL,
    hash char(64) NOT NULL,
    criada_em timestamptz NOT NULL,
    CONSTRAINT fk_regras_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_regras_regra_origem_id FOREIGN KEY (regra_origem_id) REFERENCES regras (id)
);

CREATE UNIQUE INDEX uq_regras_job_id_versao ON regras (job_id, versao);
CREATE UNIQUE INDEX uq_regras_job_id_hash ON regras (job_id, hash);
CREATE INDEX idx_regras_regra_origem_id ON regras (regra_origem_id);
-- rollback DROP TABLE regras;
