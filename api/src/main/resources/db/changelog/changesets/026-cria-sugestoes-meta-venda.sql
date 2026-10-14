-- liquibase formatted sql

-- changeset synapse:026-cria-sugestoes-meta-venda
-- Uma conclusão de busca por versão; aceita_em preserva a deduplicação após aceitar.
-- Nenhum artefato do worker é alterado: a aceitação muda a referência em simulacoes.
CREATE TABLE sugestoes_meta_venda (
    job_id uuid NOT NULL,
    regra_id uuid NOT NULL,
    resultado_id uuid,
    motivo_sem_solucao text,
    criada_em timestamptz NOT NULL DEFAULT now(),
    aceita_em timestamptz,
    CONSTRAINT pk_sugestoes_meta_venda PRIMARY KEY (job_id, regra_id),
    CONSTRAINT fk_sugestoes_meta_venda_job_id FOREIGN KEY (job_id) REFERENCES jobs (id),
    CONSTRAINT fk_sugestoes_meta_venda_regra_id FOREIGN KEY (regra_id) REFERENCES regras (id),
    CONSTRAINT fk_sugestoes_meta_venda_resultado_id FOREIGN KEY (resultado_id) REFERENCES resultados_simulacao (id),
    CONSTRAINT ck_sugestoes_meta_venda_desfecho CHECK (num_nonnulls(resultado_id, motivo_sem_solucao) = 1),
    CONSTRAINT ck_sugestoes_meta_venda_aceitacao CHECK (aceita_em IS NULL OR resultado_id IS NOT NULL)
);

GRANT SELECT, INSERT ON sugestoes_meta_venda TO ${usuario_api};
GRANT UPDATE (aceita_em) ON sugestoes_meta_venda TO ${usuario_api};
-- rollback DROP TABLE sugestoes_meta_venda;
