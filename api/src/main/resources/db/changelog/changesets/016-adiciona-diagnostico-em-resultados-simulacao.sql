-- liquibase formatted sql

-- changeset synapse:016-adiciona-diagnostico-em-resultados-simulacao
ALTER TABLE resultados_simulacao ADD COLUMN diagnostico jsonb;
-- rollback ALTER TABLE resultados_simulacao DROP COLUMN diagnostico;
