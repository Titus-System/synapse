-- liquibase formatted sql

-- changeset synapse:002-cria-submissoes
CREATE TABLE submissoes (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    usuario_id uuid NOT NULL,
    tipo text NOT NULL,
    conteudo jsonb,
    binario bytea,
    formato text,
    transcricao text,
    transcrito_em timestamptz,
    criado_em timestamptz NOT NULL,
    CONSTRAINT fk_submissoes_usuario_id FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
);

GRANT SELECT, INSERT, UPDATE ON submissoes TO ${usuario_api};
GRANT SELECT ON submissoes TO ${usuario_codegen};
-- rollback DROP TABLE submissoes;
