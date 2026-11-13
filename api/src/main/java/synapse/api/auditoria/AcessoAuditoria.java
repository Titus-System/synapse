package synapse.api.auditoria;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.context.annotation.Configuration;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.stereotype.Component;
import org.springframework.web.cors.CorsUtils;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.security.UsuarioAtual;

@Configuration
class AcessoAuditoriaConfig implements WebMvcConfigurer {

	private final AcessoAuditoriaInterceptor interceptor;

	AcessoAuditoriaConfig(AcessoAuditoriaInterceptor interceptor) {
		this.interceptor = interceptor;
	}

	@Override
	public void addInterceptors(InterceptorRegistry registry) {
		registry.addInterceptor(this.interceptor).addPathPatterns("/auditoria/**");
	}

}

/**
 * Política das rotas de auditoria: só o papel de auditor passa, sem conferir posse. Roda
 * antes de interpretar os parâmetros e de ler qualquer dado, então uma recusa nunca chega
 * ao controller. Caminho sem rota segue para o 404 do Spring.
 */
@Component
class AcessoAuditoriaInterceptor implements HandlerInterceptor {

	static final String ACESSO = "acessoAutorizadoAAuditoria";

	private static final Logger log = LoggerFactory.getLogger(AcessoAuditoriaInterceptor.class);

	private final UsuarioAtual usuarioAtual;

	private final CorrelationContext correlacao;

	AcessoAuditoriaInterceptor(UsuarioAtual usuarioAtual, CorrelationContext correlacao) {
		this.usuarioAtual = usuarioAtual;
		this.correlacao = correlacao;
	}

	@Override
	public boolean preHandle(HttpServletRequest requisicao, HttpServletResponse resposta, Object handler) {
		if (CorsUtils.isPreFlightRequest(requisicao) || !(handler instanceof HandlerMethod)) {
			return true;
		}
		AcessoDoUsuario acesso;
		try {
			acesso = this.usuarioAtual.obter();
		}
		catch (AccessDeniedException ex) {
			// A mensagem do UsuarioAtual fala do token e da conta; fica fora do log.
			log.atWarn().addKeyValue("motivo", "identidade_recusada").log("acesso à auditoria recusado");
			throw new SemPermissaoNaAuditoriaException();
		}
		if (acesso.papel() != PapelDoUsuario.AUDITOR) {
			try (var escopo = this.correlacao.abrir(null, acesso.usuarioId().toString())) {
				log.atWarn().addKeyValue("motivo", "papel_sem_acesso").log("acesso à auditoria recusado");
			}
			throw new SemPermissaoNaAuditoriaException();
		}
		requisicao.setAttribute(ACESSO, acesso);
		return true;
	}

}
