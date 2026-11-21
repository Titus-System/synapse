-- liquibase formatted sql

-- changeset synapse:032-adiciona-resultado-em-trilhas-auditoria
-- O resultado sobre o qual a etapa agiu, vindo de no-concluido. Formato e semântica em
-- docs/database/modelo-dados.dbml.
--
-- Sem backfill: as linhas gravadas antes da coluna ficam com o valor nulo. A permissão da
-- api é de tabela (changeset 013) e já alcança a coluna nova; codegen e worker não acessam
-- a tabela.
ALTER TABLE trilhas_auditoria
    ADD COLUMN resultado_id uuid,
    ADD CONSTRAINT fk_trilhas_auditoria_resultado_id
        FOREIGN KEY (resultado_id) REFERENCES resultados_simulacao (id);

CREATE INDEX idx_trilhas_auditoria_resultado_id ON trilhas_auditoria (resultado_id);
-- rollback ALTER TABLE trilhas_auditoria DROP COLUMN resultado_id;
