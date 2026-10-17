-- liquibase formatted sql

-- changeset synapse:028-adiciona-representacao-em-regras
ALTER TABLE regras ADD COLUMN representacao jsonb;
ALTER TABLE regras ADD CONSTRAINT ck_regras_representacao_coerente CHECK (
    representacao IS NULL OR (
        jsonb_typeof(representacao) = 'object'
        AND jsonb_exists(representacao, 'nucleo')
        AND jsonb_exists(representacao, 'especificacoes')
        AND representacao -> 'nucleo' = nucleo
        AND representacao -> 'especificacoes' = especificacoes
    )
);

-- rollback ALTER TABLE regras DROP CONSTRAINT ck_regras_representacao_coerente;
-- rollback ALTER TABLE regras DROP COLUMN representacao;
