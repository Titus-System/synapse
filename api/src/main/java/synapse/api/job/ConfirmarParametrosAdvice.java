package synapse.api.job;

import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = ConfirmarParametrosController.class)
class ConfirmarParametrosAdvice {

	@ExceptionHandler(ConfirmarParametrosException.class)
	ResponseEntity<ErroCriarJobDto> tratar(ConfirmarParametrosException ex) {
		return ResponseEntity.status(ex.status()).body(ex.erro());
	}

	@ExceptionHandler(HttpMessageNotReadableException.class)
	ResponseEntity<ErroCriarJobDto> corpoInvalido() {
		return tratar(ConfirmarParametrosException.requisicao("O corpo deve conter um objeto JSON válido."));
	}

	@ExceptionHandler(TransicaoDeStatusInvalidaException.class)
	ResponseEntity<ErroCriarJobDto> estadoInvalido() {
		return tratar(ConfirmarParametrosException.estadoInvalido());
	}

	@ExceptionHandler(JobNaoEncontradoException.class)
	ResponseEntity<ErroDto> jobNaoEncontrado() {
		return ResponseEntity.status(HttpStatus.NOT_FOUND)
			.body(new ErroDto("job_nao_encontrado", "Job não encontrado."));
	}

	@ExceptionHandler(DataAccessException.class)
	ResponseEntity<Void> falhaDePersistencia() {
		return ResponseEntity.internalServerError().build();
	}

}
