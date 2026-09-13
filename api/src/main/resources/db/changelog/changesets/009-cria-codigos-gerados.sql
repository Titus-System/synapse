-- liquibase formatted sql

-- changeset synapse:009-cria-codigos-gerados
CREATE TABLE codigos_gerados (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    regra_id uuid NOT NULL,
    linguagem text NOT NULL,
    fonte text NOT NULL,
    prompt_id uuid NOT NULL,
    criado_em timestamptz NOT NULL,
    CONSTRAINT fk_codigos_gerados_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_codigos_gerados_regra_id FOREIGN KEY (regra_id) REFERENCES regras (id),
    CONSTRAINT fk_codigos_gerados_prompt_id FOREIGN KEY (prompt_id) REFERENCES prompts (id)
);

CREATE INDEX idx_codigos_gerados_regra_id ON codigos_gerados (regra_id);
CREATE INDEX idx_codigos_gerados_prompt_id ON codigos_gerados (prompt_id);
CREATE INDEX idx_codigos_gerados_job_id ON codigos_gerados (job_id);
-- rollback DROP TABLE codigos_gerados;
