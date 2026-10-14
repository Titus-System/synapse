-- liquibase formatted sql

-- changeset synapse:027-adiciona-resposta-invalida-na-transcricao
ALTER TABLE trabalhos_transcricao ADD COLUMN resposta_invalida boolean NOT NULL DEFAULT false;
-- SELECT, INSERT e UPDATE da api já são concedidos sobre a tabela inteira (023).
-- rollback ALTER TABLE trabalhos_transcricao DROP COLUMN resposta_invalida;
