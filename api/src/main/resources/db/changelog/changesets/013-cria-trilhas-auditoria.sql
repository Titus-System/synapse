-- liquibase formatted sql

-- changeset synapse:013-cria-trilhas-auditoria
CREATE TABLE trilhas_auditoria (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    evento_id uuid NOT NULL,
    job_id uuid NOT NULL,
    simulacao_id uuid,
    no text NOT NULL,
    concluido_em timestamptz NOT NULL,
    regra_id uuid,
    conclusao jsonb NOT NULL,
    prompt_id uuid,
    codigo_gerado_id uuid,
    explicacao_id uuid,
    CONSTRAINT fk_trilhas_auditoria_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_trilhas_auditoria_simulacao_id FOREIGN KEY (simulacao_id) REFERENCES simulacoes (id),
    CONSTRAINT fk_trilhas_auditoria_regra_id FOREIGN KEY (regra_id) REFERENCES regras (id),
    CONSTRAINT fk_trilhas_auditoria_prompt_id FOREIGN KEY (prompt_id) REFERENCES prompts (id),
    CONSTRAINT fk_trilhas_auditoria_codigo_gerado_id FOREIGN KEY (codigo_gerado_id) REFERENCES codigos_gerados (id),
    CONSTRAINT fk_trilhas_auditoria_explicacao_id FOREIGN KEY (explicacao_id) REFERENCES explicacoes (id)
);

-- evento_id vem na mensagem, não do default acima: é a chave de idempotência que
-- rejeita a reentrega do broker já no insert.
CREATE UNIQUE INDEX uq_trilhas_auditoria_evento_id ON trilhas_auditoria (evento_id);
CREATE INDEX idx_trilhas_auditoria_job_id_concluido_em ON trilhas_auditoria (job_id, concluido_em);
CREATE INDEX idx_trilhas_auditoria_simulacao_id ON trilhas_auditoria (simulacao_id);
-- rollback DROP TABLE trilhas_auditoria;
