package synapse.api.core.logging;

import java.io.IOException;

import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;

import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

/**
 * O MDC é {@code ThreadLocal} e o Tomcat reaproveita threads: sem esta limpeza, um escopo
 * não fechado faria a próxima requisição logar o {@code job_id} da anterior.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class CorrelationFilter implements Filter {

	private final CorrelationContext contextoCorrelacao;

	public CorrelationFilter(CorrelationContext contextoCorrelacao) {
		this.contextoCorrelacao = contextoCorrelacao;
	}

	@Override
	public void doFilter(ServletRequest requisicao, ServletResponse resposta, FilterChain cadeiaFiltros)
			throws ServletException, IOException {
		try {
			cadeiaFiltros.doFilter(requisicao, resposta);
		}
		finally {
			this.contextoCorrelacao.limpar();
		}
	}

}
