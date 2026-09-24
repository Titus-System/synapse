package synapse.api.job;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
class AutorizacaoDeJobAdvice {

	@ExceptionHandler(SemPermissaoNoJobException.class)
	ResponseEntity<ErroDto> semPermissao() {
		return ResponseEntity.status(HttpStatus.FORBIDDEN)
			.body(new ErroDto("sem_permissao", "Você não tem acesso a este job."));
	}

}
