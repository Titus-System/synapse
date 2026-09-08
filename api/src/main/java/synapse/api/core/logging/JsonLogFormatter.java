package synapse.api.core.logging;

import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeFormatterBuilder;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

import ch.qos.logback.classic.pattern.ThrowableProxyConverter;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.classic.spi.IThrowableProxy;
import ch.qos.logback.classic.spi.ThrowableProxy;
import org.jspecify.annotations.Nullable;
import org.slf4j.event.KeyValuePair;

import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.boot.json.JsonWriter;
import org.springframework.boot.logging.StackTracePrinter;
import org.springframework.boot.logging.structured.JsonWriterStructuredLogFormatter;
import org.springframework.boot.logging.structured.StructuredLoggingJsonMembersCustomizer;
import org.springframework.core.env.Environment;
import org.springframework.util.ClassUtils;

import synapse.api.core.config.AppProperties;

/**
 * Envelope de log compartilhado entre os serviços do sistema: mudar um campo de topo aqui
 * exige mudar os outros serviços junto. Ligado em {@code logback-spring.xml}.
 */
public class JsonLogFormatter extends JsonWriterStructuredLogFormatter<ILoggingEvent> {

	/** Offset explícito {@code +00:00}, e não {@code Z}. */
	private static final DateTimeFormatter TIMESTAMP = new DateTimeFormatterBuilder()
		.append(DateTimeFormatter.ISO_LOCAL_DATE_TIME)
		.appendOffset("+HH:MM", "+00:00")
		.toFormatter()
		.withZone(ZoneOffset.UTC);

	private static final String TRACE_ID_MDC_KEY = "traceId";

	private static final String SPAN_ID_MDC_KEY = "spanId";

	public JsonLogFormatter(Environment environment, @Nullable StackTracePrinter stackTracePrinter,
			ThrowableProxyConverter throwableProxyConverter,
			StructuredLoggingJsonMembersCustomizer.Builder<?> customizerBuilder) {
		super((members) -> jsonMembers(bind(environment),
				new StackTraceExtractor(stackTracePrinter, throwableProxyConverter), members),
				customizerBuilder.build());
	}

	/** Este formatter nasce antes do contexto Spring, então não há bean para injetar. */
	private static AppProperties bind(Environment environment) {
		return Binder.get(environment)
			.bind("app", AppProperties.class)
			.orElseThrow(() -> new IllegalStateException("bloco `app` ausente em application.yaml"));
	}

	private static void jsonMembers(AppProperties properties, StackTraceExtractor stackTrace,
			JsonWriter.Members<ILoggingEvent> members) {
		members.add("timestamp", (event) -> TIMESTAMP.format(event.getInstant()));
		members.add("level", (event) -> event.getLevel().toString());
		members.add("message", ILoggingEvent::getFormattedMessage);

		members.add("service", properties.service().name()).whenHasLength();
		members.add("environment", properties.environment()).whenHasLength();
		members.add("version", properties.service().version()).whenHasLength();
		members.add("host", properties.observability().host()).whenHasLength();

		members.add("logger", ILoggingEvent::getLoggerName);
		members.add("module", (event) -> callerData(event, (caller) -> ClassUtils.getShortName(caller.getClassName())))
			.whenHasLength();
		members.add("function", (event) -> callerData(event, StackTraceElement::getMethodName)).whenHasLength();
		members.add("line", (event) -> callerData(event, StackTraceElement::getLineNumber)).whenNotNull();

		members.add("trace_id", (event) -> event.getMDCPropertyMap().get(TRACE_ID_MDC_KEY)).whenHasLength();
		members.add("span_id", (event) -> event.getMDCPropertyMap().get(SPAN_ID_MDC_KEY)).whenHasLength();
		members.add("job_id", (event) -> event.getMDCPropertyMap().get(CorrelationContext.JOB_ID_KEY)).whenHasLength();
		members.add("user_id", (event) -> event.getMDCPropertyMap().get(CorrelationContext.USER_ID_KEY))
			.whenHasLength();

		members.add("extra", JsonLogFormatter::extra).whenNotEmpty();
		members.add("exception", stackTrace::extract).whenHasLength();
	}

	/** Dado estruturado de uma chamada, vindo do {@code addKeyValue} do SLF4J. */
	private static Map<String, Object> extra(ILoggingEvent event) {
		List<KeyValuePair> pairs = event.getKeyValuePairs();
		if (pairs == null || pairs.isEmpty()) {
			return Map.of();
		}
		Map<String, Object> extra = new LinkedHashMap<>(pairs.size());
		for (KeyValuePair pair : pairs) {
			extra.put(pair.key, pair.value);
		}
		return extra;
	}

	/** Vem vazio sem o {@code includeCallerData} do {@code logback-spring.xml}. */
	private static <T> @Nullable T callerData(ILoggingEvent event, Function<StackTraceElement, T> extractor) {
		StackTraceElement[] callerData = event.getCallerData();
		return (callerData != null && callerData.length > 0) ? extractor.apply(callerData[0]) : null;
	}

	/** O {@code Extractor} equivalente do Boot é package-private. */
	private record StackTraceExtractor(@Nullable StackTracePrinter printer, ThrowableProxyConverter converter) {

		String extract(ILoggingEvent event) {
			IThrowableProxy throwableProxy = event.getThrowableProxy();
			if (throwableProxy == null) {
				return "";
			}
			if (this.printer != null && throwableProxy instanceof ThrowableProxy proxy) {
				return this.printer.printStackTraceToString(proxy.getThrowable());
			}
			return this.converter.convert(event);
		}

	}

}
