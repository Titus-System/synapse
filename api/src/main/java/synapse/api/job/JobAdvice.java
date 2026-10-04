package synapse.api.job;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.HandlerMapping;

@RestControllerAdvice(assignableTypes = JobController.class)
class JobAdvice {

	@ExceptionHandler(CriarJobException.class)
	ResponseEntity<ErroCriarJobDto> tratar(CriarJobException ex, HttpServletRequest request) {
		exigirOperacao(request, ex, OperacaoJob.CRIAR);
		return ResponseEntity.status(ex.status()).body(ex.erro());
	}

	@ExceptionHandler(ConfirmarParametrosException.class)
	ResponseEntity<ErroCriarJobDto> tratar(ConfirmarParametrosException ex, HttpServletRequest request) {
		exigirOperacao(request, ex, OperacaoJob.CONFIRMAR_PARAMETROS);
		return ResponseEntity.status(ex.status()).body(ex.erro());
	}

	@ExceptionHandler(ExecutarAcaoException.class)
	ResponseEntity<ErroDto> tratar(ExecutarAcaoException ex, HttpServletRequest request) {
		exigirOperacao(request, ex, OperacaoJob.EXECUTAR_ACAO);
		return ResponseEntity.status(ex.status()).body(ex.erro());
	}

	@ExceptionHandler(ReprocessarJobException.class)
	ResponseEntity<ErroDto> tratar(ReprocessarJobException ex, HttpServletRequest request) {
		exigirOperacao(request, ex, OperacaoJob.REPROCESSAR);
		return ResponseEntity.status(ex.status()).body(ex.erro());
	}

	@ExceptionHandler(ListarJobsException.class)
	ResponseEntity<ErroDto> parametroInvalido(ListarJobsException ex, HttpServletRequest request) {
		exigirOperacao(request, ex, OperacaoJob.LISTAR);
		return ResponseEntity.badRequest().body(new ErroDto("requisicao_invalida", ex.mensagem()));
	}

	@ExceptionHandler(MethodArgumentTypeMismatchException.class)
	ResponseEntity<ErroDto> parametroNaoInteiro(MethodArgumentTypeMismatchException ex, HttpServletRequest request) {
		exigirOperacao(request, ex, OperacaoJob.LISTAR);
		return parametroInvalido(
				"tamanho".equals(ex.getName()) ? ListarJobsException.tamanho() : ListarJobsException.pagina(), request);
	}

	@ExceptionHandler(HttpMessageNotReadableException.class)
	ResponseEntity<?> corpoInvalido(HttpMessageNotReadableException ex, HttpServletRequest request) {
		String mensagem = "O corpo deve conter um objeto JSON válido.";
		return switch (operacao(request, ex)) {
			case CRIAR -> tratar(CriarJobException.requisicao(mensagem), request);
			case CONFIRMAR_PARAMETROS -> tratar(ConfirmarParametrosException.requisicao(mensagem), request);
			case EXECUTAR_ACAO -> tratar(ExecutarAcaoException.requisicao(mensagem), request);
			case REPROCESSAR -> tratar(ReprocessarJobException.requisicao(mensagem), request);
			case LISTAR, CONSULTAR, ACOMPANHAR -> throw ex;
		};
	}

	@ExceptionHandler(TransicaoDeStatusInvalidaException.class)
	ResponseEntity<ErroCriarJobDto> estadoInvalido(TransicaoDeStatusInvalidaException ex, HttpServletRequest request) {
		exigirOperacao(request, ex, OperacaoJob.CONFIRMAR_PARAMETROS);
		return tratar(ConfirmarParametrosException.estadoInvalido(), request);
	}

	@ExceptionHandler(JobNaoEncontradoException.class)
	ResponseEntity<ErroDto> jobNaoEncontrado(JobNaoEncontradoException ex, HttpServletRequest request) {
		var resposta = switch (operacao(request, ex)) {
			case CRIAR, LISTAR -> throw ex;
			// O erro do stream deve ser JSON mesmo com Accept: text/event-stream.
			case ACOMPANHAR -> ResponseEntity.status(HttpStatus.NOT_FOUND).contentType(MediaType.APPLICATION_JSON);
			case CONSULTAR, CONFIRMAR_PARAMETROS, EXECUTAR_ACAO, REPROCESSAR ->
				ResponseEntity.status(HttpStatus.NOT_FOUND);
		};
		return resposta.body(new ErroDto("job_nao_encontrado", "Job não encontrado."));
	}

	@ExceptionHandler(DataAccessException.class)
	ResponseEntity<Void> falhaDePersistencia(DataAccessException ex, HttpServletRequest request) {
		return switch (operacao(request, ex)) {
			case CONSULTAR -> throw ex;
			case CRIAR, LISTAR, ACOMPANHAR, CONFIRMAR_PARAMETROS, EXECUTAR_ACAO, REPROCESSAR ->
				ResponseEntity.internalServerError().build();
		};
	}

	private static void exigirOperacao(HttpServletRequest request, RuntimeException ex, OperacaoJob esperada) {
		if (operacao(request, ex) != esperada) {
			// Relançar preserva a resolução do Spring fora do escopo deste tratamento.
			throw ex;
		}
	}

	private static OperacaoJob operacao(HttpServletRequest request, RuntimeException ex) {
		if (request.getAttribute(HandlerMapping.BEST_MATCHING_HANDLER_ATTRIBUTE) instanceof HandlerMethod metodo) {
			AutorizarJob politica = metodo.getMethodAnnotation(AutorizarJob.class);
			if (politica != null) {
				return politica.value();
			}
		}
		throw ex;
	}

}
