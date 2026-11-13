package synapse.api.auditoria;

/** O papel da sessão não é o de auditor. */
class SemPermissaoNaAuditoriaException extends RuntimeException {

}

class JobNaoEncontradoNaAuditoriaException extends RuntimeException {

}

/** A mensagem é a exposta ao cliente, a mesma de {@code GET /jobs}. */
class RequisicaoInvalidaNaAuditoriaException extends RuntimeException {

	private RequisicaoInvalidaNaAuditoriaException(String mensagem) {
		super(mensagem);
	}

	static RequisicaoInvalidaNaAuditoriaException pagina() {
		return new RequisicaoInvalidaNaAuditoriaException(
				"O parâmetro pagina precisa ser um inteiro maior ou igual a zero.");
	}

	static RequisicaoInvalidaNaAuditoriaException tamanho() {
		return new RequisicaoInvalidaNaAuditoriaException("O parâmetro tamanho precisa ser um inteiro entre 1 e 100.");
	}

	static RequisicaoInvalidaNaAuditoriaException idDoJob() {
		return new RequisicaoInvalidaNaAuditoriaException("O identificador do job precisa ser um UUID.");
	}

}
