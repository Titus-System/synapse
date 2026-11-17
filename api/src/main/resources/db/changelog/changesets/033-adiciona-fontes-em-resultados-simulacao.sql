-- liquibase formatted sql

-- changeset synapse:033-adiciona-fontes-em-resultados-simulacao
ALTER TABLE resultados_simulacao ADD COLUMN fontes jsonb;

-- rollback ALTER TABLE resultados_simulacao DROP COLUMN fontes;
