-- liquibase formatted sql

-- changeset synapse:022-cria-trabalhos-transcricao
CREATE TABLE trabalhos_transcricao (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    submissao_id uuid NOT NULL,
    finalidade text NOT NULL,
    estado text NOT NULL,
    tentativas int NOT NULL DEFAULT 0,
    reservado_ate timestamptz,
    proxima_tentativa_em timestamptz,
    criado_em timestamptz NOT NULL,
    atualizado_em timestamptz NOT NULL,
    CONSTRAINT fk_trabalhos_transcricao_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_trabalhos_transcricao_submissao_id FOREIGN KEY (submissao_id) REFERENCES submissoes (id),
    CONSTRAINT uq_trabalhos_transcricao_submissao_id UNIQUE (submissao_id)
);

GRANT SELECT, INSERT, UPDATE ON trabalhos_transcricao TO ${usuario_api};

-- rollback DROP TABLE trabalhos_transcricao;
