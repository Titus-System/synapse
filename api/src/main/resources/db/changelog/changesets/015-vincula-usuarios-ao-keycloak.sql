-- liquibase formatted sql

-- changeset synapse:015-vincula-usuarios-ao-keycloak
ALTER TABLE usuarios ALTER COLUMN senha_hash DROP NOT NULL;
ALTER TABLE usuarios ADD COLUMN keycloak_sub text;
CREATE UNIQUE INDEX uq_usuarios_keycloak_sub ON usuarios (keycloak_sub) WHERE keycloak_sub IS NOT NULL;
-- rollback DROP INDEX uq_usuarios_keycloak_sub;
-- rollback ALTER TABLE usuarios DROP COLUMN keycloak_sub;
-- rollback ALTER TABLE usuarios ALTER COLUMN senha_hash SET NOT NULL;
