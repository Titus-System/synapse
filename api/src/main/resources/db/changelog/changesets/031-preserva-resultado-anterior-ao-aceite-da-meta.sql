-- liquibase formatted sql

-- changeset synapse:031-preserva-resultado-anterior-ao-aceite-da-meta
ALTER TABLE sugestoes_meta_venda
    ADD COLUMN resultado_anterior_id uuid,
    ADD CONSTRAINT fk_sugestoes_meta_venda_resultado_anterior_id
        FOREIGN KEY (resultado_anterior_id) REFERENCES resultados_simulacao (id);

GRANT UPDATE (resultado_anterior_id) ON sugestoes_meta_venda TO ${usuario_api};

-- O legado só é recuperável sem ambiguidade quando há um único original de sucesso.
UPDATE sugestoes_meta_venda m
SET resultado_anterior_id = (
    SELECT original.id
    FROM simulacoes s
    JOIN resultados_simulacao original
      ON original.job_id = s.job_id AND original.codigo_gerado_id = s.codigo_gerado_id
    WHERE s.job_id = m.job_id AND s.regra_id = m.regra_id AND s.resultado_id = m.resultado_id
      AND original.proposito = 'simulacao' AND original.status = 'sucesso'
      AND original.criado_em <= m.aceita_em
)
WHERE m.aceita_em IS NOT NULL
  AND 1 = (
    SELECT count(*)
    FROM simulacoes s
    JOIN resultados_simulacao original
      ON original.job_id = s.job_id AND original.codigo_gerado_id = s.codigo_gerado_id
    WHERE s.job_id = m.job_id AND s.regra_id = m.regra_id AND s.resultado_id = m.resultado_id
      AND original.proposito = 'simulacao' AND original.status = 'sucesso'
      AND original.criado_em <= m.aceita_em
  );

-- rollback ALTER TABLE sugestoes_meta_venda DROP COLUMN resultado_anterior_id;
