-- liquibase formatted sql

-- changeset synapse:014-cria-outbox-events
CREATE TABLE outbox_events (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    tipo text NOT NULL,
    payload jsonb NOT NULL,
    criado_em timestamptz NOT NULL,
    publicado_em timestamptz,
    tentativas int NOT NULL DEFAULT 0,
    CONSTRAINT fk_outbox_events_job_id FOREIGN KEY (job_id) REFERENCES jobs (id)
);

-- Parcial: o poller só lê o que ainda não foi publicado, e o índice não carrega o
-- histórico já enviado.
CREATE INDEX idx_outbox_events_criado_em_pendentes ON outbox_events (criado_em)
    WHERE publicado_em IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON outbox_events TO ${usuario_api};
-- rollback DROP TABLE outbox_events;
