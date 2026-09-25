package synapse.api.job;

enum OperacaoJob {

	CRIAR, LISTAR, CONSULTAR, ACOMPANHAR, CONFIRMAR_PARAMETROS, EXECUTAR_ACAO, REPROCESSAR;

	boolean exigePosse() {
		return switch (this) {
			case CRIAR, LISTAR -> false;
			case CONSULTAR, ACOMPANHAR, CONFIRMAR_PARAMETROS, EXECUTAR_ACAO, REPROCESSAR -> true;
		};
	}

}
