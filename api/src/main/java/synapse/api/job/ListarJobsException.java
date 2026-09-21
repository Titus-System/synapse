package synapse.api.job;

/** Parâmetro de paginação de {@code GET /jobs} fora do que o contrato aceita. */
class ListarJobsException extends RuntimeException {

	private final String mensagem;

	private ListarJobsException(String mensagem) {
		super(mensagem);
		this.mensagem = mensagem;
	}

	static ListarJobsException pagina() {
		return new ListarJobsException("O parâmetro pagina precisa ser um inteiro maior ou igual a zero.");
	}

	static ListarJobsException tamanho() {
		return new ListarJobsException("O parâmetro tamanho precisa ser um inteiro entre 1 e 100.");
	}

	String mensagem() {
		return this.mensagem;
	}

}
