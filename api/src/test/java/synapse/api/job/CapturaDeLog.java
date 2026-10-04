package synapse.api.job;

import java.util.List;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.pattern.ThrowableProxyConverter;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import org.slf4j.LoggerFactory;

import org.springframework.boot.logging.structured.StructuredLoggingJsonMembersCustomizer;
import org.springframework.mock.env.MockEnvironment;

import synapse.api.core.logging.JsonLogFormatter;

/**
 * Captura o que uma classe de produção loga e o serializa com o {@link JsonLogFormatter}
 * real, para que o teste confira o envelope que sai de verdade - e não só a chamada ao
 * logger. O MDC é copiado na captura: ele é lido de forma preguiçosa e o escopo de
 * correlação já terá fechado quando o teste olhar o evento.
 */
final class CapturaDeLog implements AutoCloseable {

	private static final StructuredLoggingJsonMembersCustomizer.Builder<Object> SEM_CUSTOMIZACAO = new StructuredLoggingJsonMembersCustomizer.Builder<>() {

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

	private final Logger logger;

	private final ListAppender<ILoggingEvent> appender = new ListAppender<>() {

		@Override
		protected void append(ILoggingEvent evento) {
			evento.prepareForDeferredProcessing();
			super.append(evento);
		}

	};

	CapturaDeLog(Class<?> classe) {
		this(classe.getName());
	}

	CapturaDeLog(String nome) {
		this.logger = (Logger) LoggerFactory.getLogger(nome);
		this.appender.setContext(this.logger.getLoggerContext());
		this.appender.start();
		this.logger.addAppender(this.appender);
	}

	List<ILoggingEvent> eventos() {
		return List.copyOf(this.appender.list);
	}

	/** A linha JSON que o serviço emitiria para o evento. */
	static String emJson(ILoggingEvent evento) {
		MockEnvironment ambiente = new MockEnvironment().withProperty("app.environment", "development")
			.withProperty("app.service.name", "synapse-api")
			.withProperty("app.service.public-url", "http://localhost:8080")
			.withProperty("app.service.version", "0.0.1-SNAPSHOT")
			.withProperty("app.observability.log-level", "INFO")
			.withProperty("app.observability.trace-sample-rate", "1.0")
			.withProperty("app.observability.otlp-endpoint", "http://localhost:4318")
			.withProperty("app.observability.host", "teste")
			.withProperty("app.postgres.host", "localhost")
			.withProperty("app.postgres.port", "5432")
			.withProperty("app.postgres.user", "postgres")
			.withProperty("app.postgres.password", "postgres")
			.withProperty("app.postgres.database", "api_db");
		ThrowableProxyConverter conversor = new ThrowableProxyConverter();
		conversor.start();
		return new JsonLogFormatter(ambiente, null, conversor, SEM_CUSTOMIZACAO).format(evento);
	}

	@Override
	public void close() {
		this.logger.detachAppender(this.appender);
		this.appender.stop();
	}

}
