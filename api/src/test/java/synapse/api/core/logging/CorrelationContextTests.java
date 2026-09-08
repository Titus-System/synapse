package synapse.api.core.logging;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;

import static org.assertj.core.api.Assertions.assertThat;

class CorrelationContextTests {

	@AfterEach
	void clearMdc() {
		MDC.clear();
	}

	@Test
	void opensAndClosesAScope() {
		try (var scope = CorrelationContext.open("job-42", "user-7")) {
			assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isEqualTo("job-42");
			assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isEqualTo("user-7");
		}
		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
	}

	@Test
	void restoresTheEnclosingScopeOnClose() {
		try (var outer = CorrelationContext.open("job-1", "user-1")) {
			try (var inner = CorrelationContext.open("job-2", "user-2")) {
				assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isEqualTo("job-2");
			}
			assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isEqualTo("job-1");
			assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isEqualTo("user-1");
		}
	}

	@Test
	void ignoresEmptyValuesInsteadOfWritingBlanks() {
		try (var scope = CorrelationContext.open("job-42", null)) {
			assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isEqualTo("job-42");
			assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
		}
	}

	@Test
	void clearLeavesTracingFieldsAlone() {
		MDC.put("traceId", "99816320ef13842d20d2ae5b108e6d37");
		CorrelationContext.open("job-42", "user-7");

		CorrelationContext.clear();

		assertThat(MDC.get(CorrelationContext.JOB_ID_KEY)).isNull();
		assertThat(MDC.get(CorrelationContext.USER_ID_KEY)).isNull();
		assertThat(MDC.get("traceId")).isEqualTo("99816320ef13842d20d2ae5b108e6d37");
	}

}
