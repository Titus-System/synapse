package synapse.api.job;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;

import org.springframework.http.HttpStatus;

class CriarJobException extends RuntimeException {

	private final HttpStatus status;

	private final ErroCriarJobDto erro;

	private CriarJobException(HttpStatus status, String codigo, String mensagem, List<ElementoErroDto> elementos) {
		super(mensagem);
		this.status = status;
		this.erro = new ErroCriarJobDto(codigo, mensagem, elementos);
	}

	static CriarJobException requisicao(String mensagem) {
		return new CriarJobException(HttpStatus.BAD_REQUEST, "requisicao_invalida", mensagem, List.of());
	}

	static CriarJobException nucleoIncompleto(List<ElementoErroDto> elementos) {
		return new CriarJobException(HttpStatus.UNPROCESSABLE_CONTENT, "nucleo_incompleto",
				"Preencha os campos obrigatórios do núcleo da regra.", elementos);
	}

	static CriarJobException campoInvalido(String campo, String motivo) {
		return new CriarJobException(HttpStatus.BAD_REQUEST, "requisicao_invalida", motivo,
				List.of(new ElementoErroDto("nucleo." + campo, motivo)));
	}

	static CriarJobException semUsuarioAtivo() {
		return new CriarJobException(HttpStatus.SERVICE_UNAVAILABLE, "usuario_ativo_indisponivel",
				"Nenhum usuário ativo disponível para criar o job.", List.of());
	}

	HttpStatus status() {
		return this.status;
	}

	ErroCriarJobDto erro() {
		return this.erro;
	}

}

record ErroCriarJobDto(String codigo, String mensagem,
		@JsonInclude(JsonInclude.Include.NON_EMPTY) List<ElementoErroDto> elementos) {
}

record ElementoErroDto(String ref, String motivo) {
}
