-- liquibase formatted sql

-- changeset synapse:007-cria-prompts
CREATE TABLE prompts (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    no text NOT NULL,
    conteudo text NOT NULL,
    modelo jsonb NOT NULL,
    criado_em timestamptz NOT NULL,
    CONSTRAINT fk_prompts_job_id FOREIGN KEY (job_id) REFERENCES jobs (id)
);

CREATE INDEX idx_prompts_job_id ON prompts (job_id);

GRANT SELECT ON prompts TO ${usuario_api};
GRANT SELECT, INSERT ON prompts TO ${usuario_codegen};
-- rollback DROP TABLE prompts;
