-- liquibase formatted sql

-- changeset synapse:021-adiciona-linhas-em-resultados-simulacao
ALTER TABLE resultados_simulacao ADD COLUMN linhas jsonb;
-- rollback ALTER TABLE resultados_simulacao DROP COLUMN linhas;
