package synapse.api.auditoria;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.AcessoDoUsuario;

@RestControllerAdvice(basePackageClasses = AuditoriaAdvice.class)
@Order(Ordered.HIGHEST_PRECEDENCE)
class AuditoriaAdvice {

	private static final Logger log = LoggerFactory.getLogger(AuditoriaAdvice.class);

	private final CorrelationContext correlacao;

	AuditoriaAdvice(CorrelationContext correlacao) {
		this.correlacao = correlacao;
	}

	@ExceptionHandler(SemPermissaoNaAuditoriaException.class)
	ResponseEntity<ErroAuditoriaDto> semPermissao() {
		return erro(HttpStatus.FORBIDDEN, "sem_permissao", "Você não tem permissão para esta ação.");
	}

	@ExceptionHandler(JobNaoEncontradoNaAuditoriaException.class)
	ResponseEntity<ErroAuditoriaDto> jobNaoEncontrado() {
		return erro(HttpStatus.NOT_FOUND, "job_nao_encontrado", "Job não encontrado.");
	}

	@ExceptionHandler(EntradaNaoEncontradaNaAuditoriaException.class)
	ResponseEntity<ErroAuditoriaDto> entradaNaoEncontrada() {
		return erro(HttpStatus.NOT_FOUND, "entrada_nao_encontrada", "Entrada por voz não encontrada neste job.");
	}

	@ExceptionHandler(RequisicaoInvalidaNaAuditoriaException.class)
	ResponseEntity<ErroAuditoriaDto> requisicaoInvalida(RequisicaoInvalidaNaAuditoriaException ex) {
		return erro(HttpStatus.BAD_REQUEST, "requisicao_invalida", String.valueOf(ex.getMessage()));
	}

	/**
	 * O Spring recusa o tipo antes do controller, que então não registra o desfecho. O
	 * log leva só o nome do parâmetro, nunca o valor recebido, com a operação e a
	 * mensagem que o método do controller usaria.
	 */
	@ExceptionHandler(MethodArgumentTypeMismatchException.class)
	ResponseEntity<ErroAuditoriaDto> parametroComTipoInvalido(MethodArgumentTypeMismatchException ex,
			HttpServletRequest requisicao) {
		Desfecho desfecho = switch (ex.getParameter().getExecutable().getName()) {
			case "consultar" -> new Desfecho("consultar_job_auditoria", "consulta de auditoria encerrada");
			case "obterAudio" -> new Desfecho("obter_audio_auditoria", "entrega de áudio da auditoria encerrada");
			default -> new Desfecho("listar_jobs_auditoria", "listagem de auditoria encerrada");
		};
		String usuario = requisicao.getAttribute(AcessoAuditoriaInterceptor.ACESSO) instanceof AcessoDoUsuario acesso
				? acesso.usuarioId().toString() : null;
		try (var escopo = this.correlacao.abrir(null, usuario)) {
			log.atWarn()
				.addKeyValue("operacao", desfecho.operacao())
				.addKeyValue("resultado", "requisicao_invalida")
				.addKeyValue("parametro", ex.getName())
				.log(desfecho.mensagem());
		}
		return requisicaoInvalida(switch (ex.getName()) {
			case "id" -> RequisicaoInvalidaNaAuditoriaException.idDoJob();
			case "entradaId" -> RequisicaoInvalidaNaAuditoriaException.idDaEntrada();
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

	private record Desfecho(String operacao, String mensagem) {
	}

}
