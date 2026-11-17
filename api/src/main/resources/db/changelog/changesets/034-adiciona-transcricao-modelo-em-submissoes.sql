-- liquibase formatted sql

-- changeset synapse:034-adiciona-transcricao-modelo-em-submissoes
ALTER TABLE submissoes ADD COLUMN transcricao_modelo jsonb;

-- rollback ALTER TABLE submissoes DROP COLUMN transcricao_modelo;
