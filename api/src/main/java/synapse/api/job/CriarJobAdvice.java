package synapse.api.job;

import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = CriarJobController.class)
class CriarJobAdvice {

	@ExceptionHandler(CriarJobException.class)
	ResponseEntity<ErroCriarJobDto> tratar(CriarJobException ex) {
		return ResponseEntity.status(ex.status()).body(ex.erro());
	}

	@ExceptionHandler(HttpMessageNotReadableException.class)
	ResponseEntity<ErroCriarJobDto> corpoInvalido() {
		return tratar(CriarJobException.requisicao("O corpo deve conter um objeto JSON válido."));
	}

	@ExceptionHandler(DataAccessException.class)
	ResponseEntity<Void> falhaDePersistencia() {
		return ResponseEntity.internalServerError().build();
	}

}
