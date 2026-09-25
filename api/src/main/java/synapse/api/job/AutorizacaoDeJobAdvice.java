package synapse.api.job;

import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
class AutorizacaoDeJobAdvice {

	@ExceptionHandler({ SemPermissaoNoJobException.class, AccessDeniedException.class })
	ResponseEntity<ErroDto> semPermissao() {
		return ResponseEntity.status(HttpStatus.FORBIDDEN)
			.contentType(MediaType.APPLICATION_JSON)
			.body(new ErroDto("sem_permissao", "Você não tem permissão para esta ação."));
	}

}
