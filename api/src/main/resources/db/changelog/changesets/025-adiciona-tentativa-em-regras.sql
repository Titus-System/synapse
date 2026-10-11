-- liquibase formatted sql

-- changeset synapse:025-adiciona-tentativa-em-regras
-- O número da tentativa de taxa nova que o codegen informou em sugestao-adaptacao-proposta,
-- gravado com a versão que a proposta cria. Formato e semântica em
-- docs/database/modelo-dados.dbml.
--
-- Nula nas demais origens e nas versões de sugestão gravadas antes da coluna, que eram
-- tentativa única: sem backfill, porque o número que o codegen teria informado não foi
-- guardado. A faixa repete a do contrato do evento.
ALTER TABLE regras ADD COLUMN tentativa smallint;
ALTER TABLE regras ADD CONSTRAINT ck_regras_tentativa CHECK (tentativa BETWEEN 1 AND 3);
-- rollback ALTER TABLE regras DROP COLUMN tentativa;
