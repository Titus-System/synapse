-- liquibase formatted sql

-- changeset synapse:011-cria-explicacoes
CREATE TABLE explicacoes (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    resultado_id uuid NOT NULL,
    texto text NOT NULL,
    aderencia_conferida boolean NOT NULL,
    criado_em timestamptz NOT NULL,
    CONSTRAINT fk_explicacoes_resultado_id FOREIGN KEY (resultado_id) REFERENCES resultados_simulacao (id)
);

CREATE UNIQUE INDEX uq_explicacoes_resultado_id ON explicacoes (resultado_id);
-- rollback DROP TABLE explicacoes;
