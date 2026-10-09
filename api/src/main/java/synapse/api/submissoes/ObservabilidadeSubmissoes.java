package synapse.api.submissoes;

import java.io.IOException;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
class ObservabilidadeSubmissoes extends OncePerRequestFilter {

	private static final Logger log = LoggerFactory.getLogger(ObservabilidadeSubmissoes.class);

	private final AppMetrics metrics;

	private final CorrelationContext correlacao;

	ObservabilidadeSubmissoes(AppMetrics metrics, CorrelationContext correlacao) {
		this.metrics = metrics;
		this.correlacao = correlacao;
	}

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) {
		return !"POST".equals(request.getMethod()) || !"/submissoes".equals(request.getServletPath());
	}

	@Override
	protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
			throws ServletException, IOException {
		String contentType = request.getContentType();
		String tipo = contentType != null && contentType.regionMatches(true, 0, "multipart/", 0, 10) ? "voz" : "texto";
		boolean falhou = true;
		try {
			chain.doFilter(request, response);
			falhou = false;
		}
		finally {
			String resultado = falhou ? "falha_interna" : resultado(response.getStatus());
			this.metrics.submissaoCriacao(tipo, resultado).increment();
			try (var escopo = this.correlacao.abrir(atributo(request, "submissao.job"),
					atributo(request, "submissao.usuario"))) {
				var evento = "falha_interna".equals(resultado) ? log.atError() : log.atInfo();
				evento = evento.addKeyValue("tipo", tipo).addKeyValue("resultado", resultado);
				if ("voz".equals(tipo)) {
					evento = evento.addKeyValue("formato", atributo(request, "submissao.formato"))
						.addKeyValue("faixa_tamanho", resultado.equals("audio_muito_grande") ? "acima_5_mb"
								: atributo(request, "submissao.faixa"));
				}
				evento.log("aceita".equals(resultado) ? "submissão e job criados" : "submissão recusada");
			}
		}
	}

	private static String resultado(int status) {
		return switch (status) {
			case 201 -> "aceita";
			case 400, 415 -> "requisicao_invalida";
			case 401 -> "nao_autenticado";
			case 403 -> "sem_permissao";
			case 409 -> "estado_invalido";
			case 413 -> "audio_muito_grande";
			case 422 -> "audio_invalido";
			default -> "falha_interna";
		};
	}

	private static @Nullable String atributo(HttpServletRequest request, String nome) {
		return request.getAttribute(nome) instanceof String valor ? valor : null;
	}

}
