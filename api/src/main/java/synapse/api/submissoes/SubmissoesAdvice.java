package synapse.api.submissoes;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;

import synapse.api.job.JobsDeSubmissoes;

@RestControllerAdvice(assignableTypes = SubmissoesController.class)
@Order(-1)
class SubmissoesAdvice {

	@ExceptionHandler(SubmissaoException.class)
	ResponseEntity<ErroSubmissao> recusa(SubmissaoException ex) {
		return ResponseEntity.status(ex.status()).body(new ErroSubmissao(ex.codigo(), ex.getMessage()));
	}

	@ExceptionHandler({ JobsDeSubmissoes.ParametrosInvalidos.class, HttpMessageNotReadableException.class,
			MissingServletRequestPartException.class })
	ResponseEntity<ErroSubmissao> requisicaoInvalida() {
		return recusa(SubmissaoException.requisicao("Informe os campos e as partes obrigatórios com valores válidos."));
	}

	@ExceptionHandler(AccessDeniedException.class)
	ResponseEntity<ErroSubmissao> semPermissao() {
		return ResponseEntity.status(403)
			.body(new ErroSubmissao("sem_permissao", "Você não tem permissão para esta ação."));
	}

	@ExceptionHandler(DataAccessException.class)
	ResponseEntity<Void> persistencia() {
		return ResponseEntity.internalServerError().build();
	}

}

@RestControllerAdvice
@Order(-2)
class LimiteMultipartAdvice {

	@ExceptionHandler(MaxUploadSizeExceededException.class)
	ResponseEntity<ErroSubmissao> limite(MaxUploadSizeExceededException ex, HttpServletRequest request) {
		if (!"/submissoes".equals(request.getServletPath())) {
			throw ex;
		}
		var erro = SubmissaoException.audioMuitoGrande();
		return ResponseEntity.status(erro.status()).body(new ErroSubmissao(erro.codigo(), erro.getMessage()));
	}

}

record ErroSubmissao(String codigo, String mensagem) {
}
