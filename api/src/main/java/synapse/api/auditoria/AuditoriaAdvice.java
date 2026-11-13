package synapse.api.auditoria;

import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@RestControllerAdvice(basePackageClasses = AuditoriaAdvice.class)
@Order(Ordered.HIGHEST_PRECEDENCE)
class AuditoriaAdvice {

	@ExceptionHandler(SemPermissaoNaAuditoriaException.class)
	ResponseEntity<ErroAuditoriaDto> semPermissao() {
		return erro(HttpStatus.FORBIDDEN, "sem_permissao", "Você não tem permissão para esta ação.");
	}

	@ExceptionHandler(JobNaoEncontradoNaAuditoriaException.class)
	ResponseEntity<ErroAuditoriaDto> jobNaoEncontrado() {
		return erro(HttpStatus.NOT_FOUND, "job_nao_encontrado", "Job não encontrado.");
	}

	@ExceptionHandler(RequisicaoInvalidaNaAuditoriaException.class)
	ResponseEntity<ErroAuditoriaDto> requisicaoInvalida(RequisicaoInvalidaNaAuditoriaException ex) {
		return erro(HttpStatus.BAD_REQUEST, "requisicao_invalida", String.valueOf(ex.getMessage()));
	}

	@ExceptionHandler(MethodArgumentTypeMismatchException.class)
	ResponseEntity<ErroAuditoriaDto> parametroComTipoInvalido(MethodArgumentTypeMismatchException ex) {
		return requisicaoInvalida(switch (ex.getName()) {
			case "id" -> RequisicaoInvalidaNaAuditoriaException.idDoJob();
			case "tamanho" -> RequisicaoInvalidaNaAuditoriaException.tamanho();
			default -> RequisicaoInvalidaNaAuditoriaException.pagina();
		});
	}

	/** O corpo vazio não expõe a mensagem do driver. */
	@ExceptionHandler(DataAccessException.class)
	ResponseEntity<Void> falhaDePersistencia() {
		return ResponseEntity.internalServerError().build();
	}

	private static ResponseEntity<ErroAuditoriaDto> erro(HttpStatus status, String codigo, String mensagem) {
		return ResponseEntity.status(status)
			.contentType(MediaType.APPLICATION_JSON)
			.body(new ErroAuditoriaDto(codigo, mensagem));
	}

}
