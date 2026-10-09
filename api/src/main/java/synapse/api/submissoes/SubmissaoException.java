package synapse.api.submissoes;

import org.springframework.http.HttpStatus;

class SubmissaoException extends RuntimeException {

	private final HttpStatus status;

	private final String codigo;

	SubmissaoException(HttpStatus status, String codigo, String mensagem) {
		super(mensagem);
		this.status = status;
		this.codigo = codigo;
	}

	static SubmissaoException requisicao(String mensagem) {
		return new SubmissaoException(HttpStatus.BAD_REQUEST, "requisicao_invalida", mensagem);
	}

	static SubmissaoException audioInvalido() {
		return new SubmissaoException(HttpStatus.UNPROCESSABLE_CONTENT, "audio_invalido",
				"Não foi possível usar a gravação. Grave o áudio de novo.");
	}

	static SubmissaoException audioMuitoGrande() {
		return new SubmissaoException(HttpStatus.CONTENT_TOO_LARGE, "audio_muito_grande",
				"A gravação passa do tamanho máximo de 5 MB.");
	}

	HttpStatus status() {
		return this.status;
	}

	String codigo() {
		return this.codigo;
	}

	@Override
	public String getMessage() {
		return java.util.Objects.requireNonNull(super.getMessage());
	}

}
