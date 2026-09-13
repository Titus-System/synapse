-- liquibase formatted sql

-- changeset synapse:001-cria-usuarios
CREATE TABLE usuarios (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    login text NOT NULL,
    senha_hash text NOT NULL,
    nome text NOT NULL,
    papel text NOT NULL,
    ativo boolean NOT NULL DEFAULT true,
    criado_em timestamptz NOT NULL,
    atualizado_em timestamptz,
    ultimo_login_em timestamptz
);

CREATE UNIQUE INDEX uq_usuarios_login ON usuarios (login);
-- rollback DROP TABLE usuarios;
