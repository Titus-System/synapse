-- liquibase formatted sql

-- changeset synapse:029-preserva-proposta-nao-aplicada
ALTER TABLE rodadas_correcao ADD COLUMN proposta_nao_aplicada jsonb;

-- rollback ALTER TABLE rodadas_correcao DROP COLUMN proposta_nao_aplicada;
