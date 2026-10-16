package synapse.api.job;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.jspecify.annotations.Nullable;

import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.stereotype.Component;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.cors.CorsUtils;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.HandlerMapping;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.security.UsuarioAtual;

@Configuration
class AutorizacaoJobsConfig implements WebMvcConfigurer {

	private final AutorizacaoJobsInterceptor interceptor;

	AutorizacaoJobsConfig(AutorizacaoJobsInterceptor interceptor) {
		this.interceptor = interceptor;
	}

	@Override
	public void addInterceptors(InterceptorRegistry registry) {
		registry.addInterceptor(this.interceptor).addPathPatterns("/jobs", "/jobs/**");
	}

}

@Component
class AutorizacaoJobsInterceptor implements HandlerInterceptor {

	static final String ACESSO = "acessoAutorizadoAoJob";

	private final UsuarioAtual usuarioAtual;

	private final AutorizadorDeJob autorizador;

	AutorizacaoJobsInterceptor(UsuarioAtual usuarioAtual, AutorizadorDeJob autorizador) {
		this.usuarioAtual = usuarioAtual;
		this.autorizador = autorizador;
	}

	@Override
	public boolean preHandle(HttpServletRequest requisicao, HttpServletResponse resposta, Object handler) {
		if (CorsUtils.isPreFlightRequest(requisicao)) {
			return true;
		}
		if (!(handler instanceof HandlerMethod metodo)) {
			throw new SemPermissaoNoJobException();
		}
		AutorizarJob politica = metodo.getMethodAnnotation(AutorizarJob.class);
		if (politica == null) {
			throw new SemPermissaoNoJobException();
		}
		AcessoDoUsuario acesso = this.usuarioAtual.obter();
		Object variaveis = requisicao.getAttribute(HandlerMapping.URI_TEMPLATE_VARIABLES_ATTRIBUTE);
		UUID jobId = null;
		if (politica.value().exigePosse() && variaveis instanceof Map<?, ?> mapa
				&& mapa.get("id") instanceof String id) {
			try {
				jobId = UUID.fromString(id);
			}
			catch (IllegalArgumentException ex) {
				throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
			}
		}
		this.autorizador.exigir(politica.value(), jobId, acesso);
		requisicao.setAttribute(ACESSO, acesso);
		return true;
	}

}

@Service
class AutorizadorDeJob {

	private final JobRepository repository;

	AutorizadorDeJob(JobRepository repository) {
		this.repository = repository;
	}

	void exigir(OperacaoJob operacao, @Nullable UUID jobId, AcessoDoUsuario acesso) {
		boolean permitido = switch (operacao) {
			case CRIAR, LISTAR, CONSULTAR, ACOMPANHAR, CONFIRMAR_PARAMETROS, EXECUTAR_ACAO, REPROCESSAR ->
				acesso.papel() == PapelDoUsuario.PROFISSIONAL_RH;
		};
		if (!permitido) {
			throw new SemPermissaoNoJobException();
		}
		if (!operacao.exigePosse()) {
			return;
		}
		if (jobId == null) {
			throw new SemPermissaoNoJobException();
		}
		List<UUID> donos = this.repository.buscarProprietario(jobId);
		if (donos.isEmpty()) {
			throw new JobNaoEncontradoException(jobId);
		}
		if (!acesso.usuarioId().equals(donos.getFirst())) {
			throw new SemPermissaoNoJobException();
		}
	}

}

@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.METHOD)
@interface AutorizarJob {

	OperacaoJob value();

}

enum OperacaoJob {

	CRIAR, LISTAR, CONSULTAR, ACOMPANHAR, CONFIRMAR_PARAMETROS, EXECUTAR_ACAO, REPROCESSAR;

	boolean exigePosse() {
		return switch (this) {
			case CRIAR, LISTAR -> false;
			case CONSULTAR, ACOMPANHAR, CONFIRMAR_PARAMETROS, EXECUTAR_ACAO, REPROCESSAR -> true;
		};
	}

}

@RestControllerAdvice
class AutorizacaoDeJobAdvice {

	@ExceptionHandler({ SemPermissaoNoJobException.class, AccessDeniedException.class })
	ResponseEntity<ErroDto> semPermissao() {
		return ResponseEntity.status(HttpStatus.FORBIDDEN)
			.contentType(MediaType.APPLICATION_JSON)
			.body(new ErroDto("sem_permissao", "Você não tem permissão para esta ação."));
	}

}
