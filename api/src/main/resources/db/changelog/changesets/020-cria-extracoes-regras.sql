-- liquibase formatted sql

-- changeset synapse:020-cria-extracoes-regras
CREATE TABLE extracoes_regras (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    submissao_id uuid NOT NULL,
    resposta_id uuid NOT NULL,
    representacao jsonb NOT NULL,
    rebaixamentos jsonb NOT NULL,
    criado_em timestamptz NOT NULL,
    CONSTRAINT fk_extracoes_regras_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_extracoes_regras_submissao_id FOREIGN KEY (submissao_id) REFERENCES submissoes (id),
    CONSTRAINT fk_extracoes_regras_resposta_id FOREIGN KEY (resposta_id) REFERENCES respostas_modelo (id)
);

CREATE UNIQUE INDEX uq_extracoes_regras_job_id_submissao_id ON extracoes_regras (job_id, submissao_id);
CREATE INDEX idx_extracoes_regras_submissao_id ON extracoes_regras (submissao_id);
CREATE INDEX idx_extracoes_regras_resposta_id ON extracoes_regras (resposta_id);

GRANT SELECT, INSERT ON extracoes_regras TO ${usuario_codegen};
GRANT SELECT ON extracoes_regras TO ${usuario_api};
-- rollback DROP TABLE extracoes_regras;
