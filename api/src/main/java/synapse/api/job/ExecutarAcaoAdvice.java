package synapse.api.job;

import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = ExecutarAcaoController.class)
class ExecutarAcaoAdvice {

	@ExceptionHandler(ExecutarAcaoException.class)
	ResponseEntity<ErroDto> tratar(ExecutarAcaoException ex) {
		return ResponseEntity.status(ex.status()).body(ex.erro());
	}

	@ExceptionHandler(JobNaoEncontradoException.class)
	ResponseEntity<ErroDto> jobNaoEncontrado() {
		return ResponseEntity.status(HttpStatus.NOT_FOUND)
			.body(new ErroDto("job_nao_encontrado", "Job não encontrado."));
	}

	@ExceptionHandler(HttpMessageNotReadableException.class)
	ResponseEntity<ErroDto> corpoInvalido() {
		return tratar(ExecutarAcaoException.requisicao("O corpo deve conter um objeto JSON válido."));
	}

	@ExceptionHandler(DataAccessException.class)
	ResponseEntity<Void> falhaDePersistencia() {
		return ResponseEntity.internalServerError().build();
	}

}
