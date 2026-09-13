package synapse.api.core.persistence;

import liquibase.Liquibase;

/**
 * Os nomes que o changelog espera receber por parâmetro. Em produção eles vêm do
 * ambiente, via {@code spring.liquibase.parameters}; aqui são fixos, porque o que os
 * testes afirmam é a permissão, não de onde o nome veio.
 */
final class UsuariosDeBanco {

	static final String API = "synapse_api";

	static final String CODEGEN = "synapse_codegen";

	static final String WORKER = "synapse_worker";

	private UsuariosDeBanco() {
	}

	/**
	 * Sem isto o {@code ${usuario_api}} chega literal ao Postgres e vira erro de sintaxe:
	 * o {@code SpringLiquibase} injeta os parâmetros na subida, a API Java do Liquibase
	 * não injeta nada sozinha.
	 */
	static void parametrosEm(Liquibase liquibase) {
		liquibase.getChangeLogParameters().set("usuario_api", API);
		liquibase.getChangeLogParameters().set("usuario_codegen", CODEGEN);
		liquibase.getChangeLogParameters().set("usuario_worker", WORKER);
	}

}
