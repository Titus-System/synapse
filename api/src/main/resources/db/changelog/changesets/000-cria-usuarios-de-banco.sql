-- liquibase formatted sql

-- changeset synapse:000-cria-usuarios-de-banco splitStatements:false
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${usuario_api}') THEN
        CREATE ROLE ${usuario_api} LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${usuario_codegen}') THEN
        CREATE ROLE ${usuario_codegen} LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${usuario_worker}') THEN
        CREATE ROLE ${usuario_worker} LOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO ${usuario_api};
GRANT USAGE ON SCHEMA public TO ${usuario_codegen};
GRANT USAGE ON SCHEMA public TO ${usuario_worker};

-- LangGraph precisa de acesso de CREATE para criar as tabelas de checkpoint
GRANT CREATE ON SCHEMA public TO ${usuario_codegen};

-- rollback REVOKE ALL ON SCHEMA public FROM ${usuario_api};
-- rollback REVOKE ALL ON SCHEMA public FROM ${usuario_codegen};
-- rollback REVOKE ALL ON SCHEMA public FROM ${usuario_worker};
-- rollback DROP ROLE IF EXISTS ${usuario_api};
-- rollback DROP ROLE IF EXISTS ${usuario_codegen};
-- rollback DROP ROLE IF EXISTS ${usuario_worker};
