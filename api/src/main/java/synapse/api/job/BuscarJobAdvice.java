package synapse.api.job;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = BuscarJobController.class)
class BuscarJobAdvice {

	@ExceptionHandler(JobNaoEncontradoException.class)
	ResponseEntity<ErroDto> jobNaoEncontrado() {
		return ResponseEntity.status(HttpStatus.NOT_FOUND)
			.body(new ErroDto("job_nao_encontrado", "Job não encontrado."));
	}

}
