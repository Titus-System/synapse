package synapse.api.job;

import org.springframework.http.HttpStatus;

class ReprocessarJobException extends RuntimeException {

	private final HttpStatus status;

	private final ErroDto erro;

	private ReprocessarJobException(HttpStatus status, String codigo, String mensagem) {
		super(mensagem);
		this.status = status;
		this.erro = new ErroDto(codigo, mensagem);
	}

	static ReprocessarJobException requisicao(String mensagem) {
		return new ReprocessarJobException(HttpStatus.BAD_REQUEST, "requisicao_invalida", mensagem);
	}

	static ReprocessarJobException estadoInvalido() {
		return new ReprocessarJobException(HttpStatus.CONFLICT, "estado_invalido",
				"Somente um job arquivado pode ser reprocessado.");
	}

	static ReprocessarJobException semRegra() {
		return new ReprocessarJobException(HttpStatus.CONFLICT, "estado_invalido",
				"O job arquivado não possui uma regra formada para reprocessamento.");
	}

	HttpStatus status() {
		return this.status;
	}

	ErroDto erro() {
		return this.erro;
	}

}
