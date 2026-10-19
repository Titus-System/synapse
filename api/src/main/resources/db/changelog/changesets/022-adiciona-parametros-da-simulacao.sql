-- liquibase formatted sql

-- changeset synapse:022-adiciona-parametros-da-simulacao
-- Os parâmetros da simulação que o usuário diz no texto ou no áudio: orçamento, meta de
-- venda e período. Formato das colunas jsonb em
-- contracts/domain/parametros-simulacao.schema.json.
--
-- jobs.orcamento deixa de ser obrigatório porque o job de texto ou voz nasce sem ele e só
-- o recebe se a extração o trouxer; sem orçamento, a simulação é feita sem a verificação
-- de orçamento. Nenhuma coluna de valor tem restrição de faixa: o valor é gravado como foi
-- dito, inclusive inválido, e é a validação de domínio que o aponta como conflito.
--
-- O default de extracoes_regras.parametros mantém válido o INSERT de uma versão do codegen
-- anterior à coluna. As permissões de codegen e worker são de tabela (changesets 006 e
-- 020) e por isso já alcançam as colunas novas, sem GRANT adicional: no Postgres, um
-- privilégio concedido na tabela vale para as colunas acrescentadas depois.
--
-- O rollback devolve o NOT NULL e falha se algum job já estiver sem orçamento: o valor que
-- ele teria não existe, e preencher 0 trocaria "sem orçamento" por "orçamento zero", que é
-- inviabilidade. Desfazer exige decidir o que fazer com esses jobs.
ALTER TABLE jobs ALTER COLUMN orcamento DROP NOT NULL;
ALTER TABLE jobs ADD COLUMN meta_venda numeric;
ALTER TABLE extracoes_regras ADD COLUMN parametros jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE regras ADD COLUMN parametros jsonb;
-- rollback ALTER TABLE regras DROP COLUMN parametros;
-- rollback ALTER TABLE extracoes_regras DROP COLUMN parametros;
-- rollback ALTER TABLE jobs DROP COLUMN meta_venda;
-- rollback ALTER TABLE jobs ALTER COLUMN orcamento SET NOT NULL;
