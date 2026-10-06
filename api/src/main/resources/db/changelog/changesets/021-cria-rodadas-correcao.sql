-- liquibase formatted sql

-- changeset synapse:021-cria-rodadas-correcao
CREATE TABLE rodadas_correcao (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    regra_analisada_id uuid NOT NULL,
    conflitos jsonb NOT NULL,
    estado text NOT NULL,
    submissao_correcao_id uuid,
    regra_resultante_id uuid,
    rodada_anterior_id uuid,
    criada_em timestamptz NOT NULL,
    atualizada_em timestamptz NOT NULL,
    CONSTRAINT fk_rodadas_correcao_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_rodadas_correcao_regra_analisada_id FOREIGN KEY (regra_analisada_id) REFERENCES regras (id),
    CONSTRAINT fk_rodadas_correcao_submissao_correcao_id FOREIGN KEY (submissao_correcao_id) REFERENCES submissoes (id),
    CONSTRAINT fk_rodadas_correcao_regra_resultante_id FOREIGN KEY (regra_resultante_id) REFERENCES regras (id),
    CONSTRAINT fk_rodadas_correcao_rodada_anterior_id FOREIGN KEY (rodada_anterior_id) REFERENCES rodadas_correcao (id)
);

CREATE UNIQUE INDEX uq_rodadas_correcao_rodada_anterior_id ON rodadas_correcao (rodada_anterior_id)
WHERE rodada_anterior_id IS NOT NULL;

CREATE UNIQUE INDEX uq_rodadas_correcao_job_id_aberta ON rodadas_correcao (job_id)
WHERE estado IN ('pendente', 'em_reextracao');

GRANT SELECT, INSERT, UPDATE ON rodadas_correcao TO ${usuario_api};
GRANT SELECT ON rodadas_correcao TO ${usuario_codegen};
-- rollback DROP TABLE rodadas_correcao;
