package synapse.api.job;

import java.util.Map;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.stereotype.Component;
import org.springframework.web.cors.CorsUtils;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.HandlerMapping;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.UsuarioAtual;

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
