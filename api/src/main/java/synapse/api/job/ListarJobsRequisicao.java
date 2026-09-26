package synapse.api.job;

record ListarJobsRequisicao(int pagina, int tamanho) {

	static final int TAMANHO_MAXIMO = 100;

	ListarJobsRequisicao {
		if (pagina < 0) {
			throw ListarJobsException.pagina();
		}
		if (tamanho < 1 || tamanho > TAMANHO_MAXIMO) {
			throw ListarJobsException.tamanho();
		}
	}

	long deslocamento() {
		return (long) this.pagina * this.tamanho;
	}

}
