-- liquibase formatted sql

-- changeset synapse:010-cria-resultados-simulacao
CREATE TABLE resultados_simulacao (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    codigo_gerado_id uuid NOT NULL,
    status text NOT NULL,
    totais jsonb,
    veredito text,
    assercoes jsonb NOT NULL,
    decomposicao jsonb,
    criado_em timestamptz NOT NULL,
    CONSTRAINT fk_resultados_simulacao_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_resultados_simulacao_codigo_gerado_id FOREIGN KEY (codigo_gerado_id) REFERENCES codigos_gerados (id)
);

CREATE INDEX idx_resultados_simulacao_codigo_gerado_id ON resultados_simulacao (codigo_gerado_id);
CREATE INDEX idx_resultados_simulacao_job_id ON resultados_simulacao (job_id);
-- rollback DROP TABLE resultados_simulacao;
