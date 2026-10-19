-- liquibase formatted sql

-- changeset synapse:019-adiciona-nome-em-jobs
ALTER TABLE jobs ADD COLUMN nome text;
-- rollback ALTER TABLE jobs DROP COLUMN nome;
