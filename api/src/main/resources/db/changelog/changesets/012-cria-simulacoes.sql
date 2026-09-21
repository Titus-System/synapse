-- liquibase formatted sql

-- changeset synapse:012-cria-simulacoes
CREATE TABLE simulacoes (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    criado_em timestamptz NOT NULL,
    regra_id uuid NOT NULL,
    job_id uuid NOT NULL,
    codigo_gerado_id uuid NOT NULL,
    resultado_id uuid,
    flag_baixa_rastreabilidade boolean NOT NULL DEFAULT false,
    CONSTRAINT fk_simulacoes_regra_id FOREIGN KEY (regra_id) REFERENCES regras (id) ON DELETE RESTRICT,
    CONSTRAINT fk_simulacoes_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_simulacoes_codigo_gerado_id FOREIGN KEY (codigo_gerado_id) REFERENCES codigos_gerados (id),
    CONSTRAINT fk_simulacoes_resultado_id FOREIGN KEY (resultado_id) REFERENCES resultados_simulacao (id)
);

CREATE UNIQUE INDEX uq_simulacoes_codigo_gerado_id ON simulacoes (codigo_gerado_id);
CREATE UNIQUE INDEX uq_simulacoes_resultado_id ON simulacoes (resultado_id);
CREATE INDEX idx_simulacoes_job_id_criado_em ON simulacoes (job_id, criado_em);
CREATE INDEX idx_simulacoes_regra_id ON simulacoes (regra_id);

GRANT SELECT, INSERT, UPDATE ON simulacoes TO ${usuario_api};
-- rollback DROP TABLE simulacoes;
