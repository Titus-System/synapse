-- liquibase formatted sql

-- changeset synapse:008-cria-respostas-modelo
CREATE TABLE respostas_modelo (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    prompt_id uuid NOT NULL,
    conteudo text NOT NULL,
    consumo_tokens jsonb,
    criado_em timestamptz NOT NULL,
    CONSTRAINT fk_respostas_modelo_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_respostas_modelo_prompt_id FOREIGN KEY (prompt_id) REFERENCES prompts (id)
);

CREATE UNIQUE INDEX uq_respostas_modelo_prompt_id ON respostas_modelo (prompt_id);
CREATE INDEX idx_respostas_modelo_job_id ON respostas_modelo (job_id);
-- rollback DROP TABLE respostas_modelo;
