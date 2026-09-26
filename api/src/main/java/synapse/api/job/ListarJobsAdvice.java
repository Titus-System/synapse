package synapse.api.job;

import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@RestControllerAdvice(assignableTypes = ListarJobsController.class)
class ListarJobsAdvice {

	@ExceptionHandler(ListarJobsException.class)
	ResponseEntity<ErroDto> parametroInvalido(ListarJobsException ex) {
		return ResponseEntity.badRequest().body(new ErroDto("requisicao_invalida", ex.mensagem()));
	}

	@ExceptionHandler(MethodArgumentTypeMismatchException.class)
	ResponseEntity<ErroDto> parametroNaoInteiro(MethodArgumentTypeMismatchException ex) {
		return parametroInvalido(
				"tamanho".equals(ex.getName()) ? ListarJobsException.tamanho() : ListarJobsException.pagina());
	}

	@ExceptionHandler(DataAccessException.class)
	ResponseEntity<Void> falhaDePersistencia() {
		return ResponseEntity.internalServerError().build();
	}

}
