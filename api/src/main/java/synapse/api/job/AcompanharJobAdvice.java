package synapse.api.job;

import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * O cliente conecta com {@code Accept: text/event-stream}; sem {@code contentType}
 * explícito a negociação de conteúdo recusaria o corpo JSON de erro por não casar com o
 * {@code Accept} da requisição.
 */
@RestControllerAdvice(assignableTypes = AcompanharJobController.class)
class AcompanharJobAdvice {

	@ExceptionHandler(JobNaoEncontradoException.class)
	ResponseEntity<ErroDto> jobNaoEncontrado() {
		return ResponseEntity.status(HttpStatus.NOT_FOUND)
			.contentType(MediaType.APPLICATION_JSON)
			.body(new ErroDto("job_nao_encontrado", "Job não encontrado."));
	}

	@ExceptionHandler(DataAccessException.class)
	ResponseEntity<Void> falhaDePersistencia() {
		return ResponseEntity.internalServerError().build();
	}

}
