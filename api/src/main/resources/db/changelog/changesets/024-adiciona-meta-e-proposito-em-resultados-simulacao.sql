-- liquibase formatted sql

-- changeset synapse:024-adiciona-meta-e-proposito-em-resultados-simulacao
-- O que o worker passa a gravar no resultado de cada execução: a meta de venda em que ela
-- foi simulada e o propósito recebido em executar-codigo. Formato e semântica em
-- docs/database/modelo-dados.dbml.
--
-- meta_venda não tem restrição de faixa no banco: o contrato do comando a exige
-- estritamente positiva, e é o worker que a valida antes de gravar. proposito nasce com o
-- default 'simulacao', o valor quando o comando não traz o campo, e cobre sem backfill as
-- linhas gravadas antes da coluna, que são todas simulações do job.
--
-- A permissão do worker é de tabela (changeset 010) e por isso já alcança as colunas
-- novas, sem GRANT adicional: no Postgres, um privilégio concedido na tabela vale para as
-- colunas acrescentadas depois. PermissoesDeBancoTests confere o INSERT das duas.
ALTER TABLE resultados_simulacao ADD COLUMN meta_venda numeric;
ALTER TABLE resultados_simulacao ADD COLUMN proposito text NOT NULL DEFAULT 'simulacao';
-- rollback ALTER TABLE resultados_simulacao DROP COLUMN proposito;
-- rollback ALTER TABLE resultados_simulacao DROP COLUMN meta_venda;
