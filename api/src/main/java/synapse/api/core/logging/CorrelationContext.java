package synapse.api.core.logging;

import org.jspecify.annotations.Nullable;
import org.slf4j.MDC;

import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

/**
 * Defina no ponto de entrada e todo log daquele fluxo herda os valores. {@code trace_id}
 * e {@code span_id} não estão aqui: vêm do span ativo do OpenTelemetry.
 *
 * <pre>{@code
 * try (var escopo = contextoCorrelacao.abrir(payload.jobId(), payload.userId())) {
 *     log.info("job accepted"); // job_id e user_id anexados automaticamente
 * }
 * }</pre>
 */
@Component
public class CorrelationContext {

	public static final String JOB_ID_KEY = "job_id";

	public static final String USER_ID_KEY = "user_id";

	/** Restaura os valores anteriores ao fechar; ignora argumento vazio. */
	public Escopo abrir(@Nullable String identificadorJob, @Nullable String identificadorUsuario) {
		return new Escopo(substituir(JOB_ID_KEY, identificadorJob), substituir(USER_ID_KEY, identificadorUsuario));
	}

	/** Remove os campos de correlação sem tocar no que o tracing pôs no MDC. */
	public void limpar() {
		MDC.remove(JOB_ID_KEY);
		MDC.remove(USER_ID_KEY);
	}

	private @Nullable String substituir(String chave, @Nullable String valor) {
		String anterior = MDC.get(chave);
		if (StringUtils.hasLength(valor)) {
			MDC.put(chave, valor);
		}
		return anterior;
	}

	private void restaurar(String chave, @Nullable String anterior) {
		if (anterior != null) {
			MDC.put(chave, anterior);
		}
		else {
			MDC.remove(chave);
		}
	}

	public final class Escopo implements AutoCloseable {

		private final @Nullable String identificadorJobAnterior;

		private final @Nullable String identificadorUsuarioAnterior;

		private Escopo(@Nullable String identificadorJobAnterior, @Nullable String identificadorUsuarioAnterior) {
			this.identificadorJobAnterior = identificadorJobAnterior;
			this.identificadorUsuarioAnterior = identificadorUsuarioAnterior;
		}

		@Override
		public void close() {
			restaurar(JOB_ID_KEY, this.identificadorJobAnterior);
			restaurar(USER_ID_KEY, this.identificadorUsuarioAnterior);
		}

	}

}
