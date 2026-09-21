package synapse.api.core.logging;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.pattern.ThrowableProxyConverter;
import ch.qos.logback.classic.spi.LoggingEvent;
import ch.qos.logback.classic.spi.ThrowableProxy;
import org.junit.jupiter.api.Test;
import org.slf4j.event.KeyValuePair;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

import org.springframework.boot.logging.structured.StructuredLoggingJsonMembersCustomizer;
import org.springframework.mock.env.MockEnvironment;

import static org.assertj.core.api.Assertions.assertThat;

/** Prende o envelope, que é contrato entre serviços. */
class JsonLogFormatterTests {

	private static final StructuredLoggingJsonMembersCustomizer.Builder<Object> NO_CUSTOMIZERS = new StructuredLoggingJsonMembersCustomizer.Builder<>() {

		@Override
		public StructuredLoggingJsonMembersCustomizer.Builder<Object> nested(boolean nested) {
			return this;
		}

		@Override
		public StructuredLoggingJsonMembersCustomizer<Object> build() {
			return (members) -> {
			};
		}

	};

	private final ObjectMapper objectMapper = new ObjectMapper();

	private final MockEnvironment environment = new MockEnvironment().withProperty("app.environment", "development")
		.withProperty("app.service.name", "synapse-api")
		.withProperty("app.service.public-url", "http://localhost:8080")
		.withProperty("app.service.version", "0.0.1-SNAPSHOT")
		.withProperty("app.observability.log-level", "INFO")
		.withProperty("app.observability.trace-sample-rate", "1.0")
		.withProperty("app.observability.otlp-endpoint", "http://localhost:4318")
		.withProperty("app.observability.host", "hal")
		.withProperty("app.postgres.host", "localhost")
		.withProperty("app.postgres.port", "5432")
		.withProperty("app.postgres.user", "postgres")
		.withProperty("app.postgres.password", "postgres")
		.withProperty("app.postgres.database", "api_db");

	@Test
	void incluiAIdentidadeEALocalizacaoDoCodigoEmTodaLinha() {
		Map<String, Object> log = format(event());
		assertThat(log).containsEntry("level", "INFO")
			.containsEntry("message", "job accepted")
			.containsEntry("service.name", "synapse-api")
			.containsEntry("environment", "development")
			.containsEntry("service.version", "0.0.1-SNAPSHOT")
			.containsEntry("host.name", "hal")
			.containsEntry("logger", "synapse.api.job.JobService")
			.containsEntry("code", Map.of("module", "JobService", "function", "accept", "line", 42));
	}

	@Test
	void formatsTheTimestampTheWayThePythonServiceDoes() {
		assertThat(format(event())).hasEntrySatisfying("timestamp",
				(timestamp) -> assertThat(timestamp).asString().startsWith("2026-09-05T22:27:40").endsWith("+00:00"));
	}

	@Test
	void levelUsesOpenTelemetryShortNames() {
		assertThat(format(event(Level.WARN))).containsEntry("level", "WARN");
	}

	@Test
	void attachesCorrelationFieldsFromTheContext() {
		LoggingEvent event = event(Level.INFO, Map.of("traceId", "99816320ef13842d20d2ae5b108e6d37", "spanId",
				"22cd8c4626502cca", CorrelationContext.JOB_ID_KEY, "job-42", CorrelationContext.USER_ID_KEY, "user-7"));
		assertThat(format(event)).containsEntry("trace_id", "99816320ef13842d20d2ae5b108e6d37")
			.containsEntry("span_id", "22cd8c4626502cca")
			.containsEntry("job_id", "job-42")
			.containsEntry("user_id", "user-7");
	}

	@Test
	void omitsCorrelationFieldsWhenEmptyRatherThanEmittingNull() {
		assertThat(format(event())).doesNotContainKeys("trace_id", "span_id", "job_id", "user_id", "extra",
				"exception");
	}

	@Test
	void putsKeyValuePairsUnderExtra() {
		LoggingEvent event = event();
		event.setKeyValuePairs(List.of(new KeyValuePair("exit_code", 0), new KeyValuePair("duration_ms", 1432)));
		assertThat(format(event)).containsEntry("extra", Map.of("exit_code", 0, "duration_ms", 1432));
	}

	@Test
	void carriesTheStackTraceInException() {
		LoggingEvent event = event();
		event.setThrowableProxy(new ThrowableProxy(new IllegalStateException("sandbox timed out")));
		assertThat(format(event)).hasEntrySatisfying("exception",
				(exception) -> assertThat(exception).asString().contains("IllegalStateException: sandbox timed out"));
	}

	private LoggingEvent event() {
		return event(Level.INFO);
	}

	private LoggingEvent event(Level level) {
		// Um evento real sempre tem um mapa de MDC; o construído à mão nesses testes não
		// está ligado a um LoggerContext de onde herdá-lo.
		return event(level, Map.of());
	}

	private LoggingEvent event(Level level, Map<String, String> mdc) {
		LoggingEvent event = new LoggingEvent();
		event.setInstant(Instant.parse("2026-09-05T22:27:40.761838Z"));
		event.setLevel(level);
		event.setMessage("job accepted");
		event.setLoggerName("synapse.api.job.JobService");
		event.setMDCPropertyMap(mdc);
		event.setCallerData(new StackTraceElement[] {
				new StackTraceElement("synapse.api.job.JobService", "accept", "JobService.java", 42) });
		return event;
	}

	private Map<String, Object> format(LoggingEvent event) {
		ThrowableProxyConverter throwableProxyConverter = new ThrowableProxyConverter();
		throwableProxyConverter.start();
		String json = new JsonLogFormatter(this.environment, null, throwableProxyConverter, NO_CUSTOMIZERS)
			.format(event);
		return this.objectMapper.readValue(json, new TypeReference<>() {
		});
	}

}
