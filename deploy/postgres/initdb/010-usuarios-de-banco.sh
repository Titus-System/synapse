#!/bin/bash
# Cria os usuários de banco dos serviços antes de a API rodar 
# porque a API não pode carregar as senhas em arquivo versionado.
#
# A senha vem do .env e o changeset encontra os usuários prontos.
#
# Roda uma única vez, na inicialização do cluster, e só com o volume de dados vazio.
# Num volume já existente este script não roda: ver docs/instalacao.md.
#
# Não toca no usuário dono do schema (POSTGRES_USER), que a própria imagem cria.
set -euo pipefail

criar_usuario() {
    local usuario="$1"
    local senha="$2"

    if [ -z "$senha" ]; then
        echo "initdb: senha vazia para $usuario - o serviço não vai conseguir conectar" >&2
        exit 1
    fi

    # psql -v com quote_literal/quote_ident: a senha nunca entra por interpolação de
    # shell na string SQL.
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -v usuario="$usuario" -v senha="$senha" <<-'EOSQL'
		SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'usuario', :'senha')
		\gexec
	EOSQL
}

criar_usuario "${SYNAPSE_API_DB_USER:-synapse_api}" "${SYNAPSE_API_DB_PASSWORD:-}"
criar_usuario "${SYNAPSE_CODEGEN_DB_USER:-synapse_codegen}" "${SYNAPSE_CODEGEN_DB_PASSWORD:-}"
criar_usuario "${SYNAPSE_WORKER_DB_USER:-synapse_worker}" "${SYNAPSE_WORKER_DB_PASSWORD:-}"

echo "initdb: usuários de banco criados. As permissões vêm nos changesets da api."
