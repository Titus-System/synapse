-- psql lê as senhas do ambiente do container, sem valores versionados.
\getenv senha_api SYNAPSE_API_DB_PASSWORD
\getenv senha_codegen SYNAPSE_CODEGEN_DB_PASSWORD
\getenv senha_worker SYNAPSE_WORKER_DB_PASSWORD
CREATE ROLE synapse_api LOGIN PASSWORD :'senha_api';
CREATE ROLE synapse_codegen LOGIN PASSWORD :'senha_codegen';
CREATE ROLE synapse_worker LOGIN PASSWORD :'senha_worker';
