package synapse.api.job;

import java.util.List;

import org.springframework.http.HttpStatus;

class ConfirmarParametrosException extends RuntimeException {

	private final HttpStatus status;

	private final ErroCriarJobDto erro;

	private ConfirmarParametrosException(HttpStatus status, String codigo, String mensagem,
			List<ElementoErroDto> elementos) {
		super(mensagem);
		this.status = status;
		this.erro = new ErroCriarJobDto(codigo, mensagem, elementos);
	}

	static ConfirmarParametrosException requisicao(String mensagem) {
		return new ConfirmarParametrosException(HttpStatus.BAD_REQUEST, "requisicao_invalida", mensagem, List.of());
	}

	static ConfirmarParametrosException nucleoIncompleto(List<ElementoErroDto> elementos) {
		return new ConfirmarParametrosException(HttpStatus.UNPROCESSABLE_CONTENT, "nucleo_incompleto",
				"Preencha os campos obrigatórios do núcleo da regra.", elementos);
	}

	static ConfirmarParametrosException campoInvalido(String campo, String motivo) {
		return new ConfirmarParametrosException(HttpStatus.BAD_REQUEST, "requisicao_invalida", motivo,
				List.of(new ElementoErroDto("nucleo." + campo, motivo)));
	}

	static ConfirmarParametrosException estadoInvalido() {
		return new ConfirmarParametrosException(HttpStatus.CONFLICT, "estado_invalido",
				"Este job não está aguardando confirmação de parâmetros.", List.of());
	}

	HttpStatus status() {
		return this.status;
	}

	ErroCriarJobDto erro() {
		return this.erro;
	}

}
