package synapse.api.core.logging;

import io.micrometer.tracing.Span;
import io.micrometer.tracing.Tracer;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Se o Micrometer renomear estas chaves, {@code trace_id} e {@code span_id} sumiriam do
 * envelope em silêncio.
 */
@SpringBootTest
@TestPropertySource(
		properties = { "management.tracing.export.otlp.enabled=false", "management.tracing.sampling.probability=1.0" })
class TracingCorrelationTests {

	@Autowired
	private Tracer tracer;

	@Test
	void spanIdsReachTheMdcUnderTheKeysTheFormatterReads() {
		Span span = this.tracer.nextSpan().name("test").start();
		try (var ignored = this.tracer.withSpan(span)) {
			assertThat(MDC.get("traceId")).hasSize(32);
			assertThat(MDC.get("spanId")).hasSize(16);
		}
		finally {
			span.end();
		}
		assertThat(MDC.get("traceId")).isNull();
	}

}
