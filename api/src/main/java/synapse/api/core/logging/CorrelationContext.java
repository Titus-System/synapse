package synapse.api.core.logging;

import org.jspecify.annotations.Nullable;
import org.slf4j.MDC;

import org.springframework.util.StringUtils;

/**
 * Defina no ponto de entrada e todo log daquele fluxo herda os valores. {@code trace_id}
 * e {@code span_id} não estão aqui: vêm do span ativo do OpenTelemetry.
 *
 * <pre>{@code
 * try (var scope = CorrelationContext.open(payload.jobId(), payload.userId())) {
 *     log.info("job accepted"); // job_id e user_id anexados automaticamente
 * }
 * }</pre>
 */
public final class CorrelationContext {

	public static final String JOB_ID_KEY = "job_id";

	public static final String USER_ID_KEY = "user_id";

	private CorrelationContext() {
	}

	/** Restaura os valores anteriores ao fechar; ignora argumento vazio. */
	public static Scope open(@Nullable String jobId, @Nullable String userId) {
		return new Scope(replace(JOB_ID_KEY, jobId), replace(USER_ID_KEY, userId));
	}

	/** Remove os campos de correlação sem tocar no que o tracing pôs no MDC. */
	public static void clear() {
		MDC.remove(JOB_ID_KEY);
		MDC.remove(USER_ID_KEY);
	}

	private static @Nullable String replace(String key, @Nullable String value) {
		String previous = MDC.get(key);
		if (StringUtils.hasLength(value)) {
			MDC.put(key, value);
		}
		return previous;
	}

	private static void restore(String key, @Nullable String previous) {
		if (previous != null) {
			MDC.put(key, previous);
		}
		else {
			MDC.remove(key);
		}
	}

	public record Scope(@Nullable String previousJobId, @Nullable String previousUserId) implements AutoCloseable {

		@Override
		public void close() {
			restore(JOB_ID_KEY, this.previousJobId);
			restore(USER_ID_KEY, this.previousUserId);
		}

	}

}
