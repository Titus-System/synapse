package synapse.api.core.metrics;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.web.servlet.client.RestTestClient;

import static org.assertj.core.api.Assertions.assertThat;

/** Um erro de configuração devolveria os endpoints ao /actuator sem falhar o boot. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class MetricsEndpointTests {

	@LocalServerPort
	private int port;

	private RestTestClient client;

	@BeforeEach
	void bindToServer() {
		this.client = RestTestClient.bindToServer().baseUrl("http://localhost:" + this.port).build();
	}

	@Test
	void servesThePrometheusScrapeAtMetrics() {
		this.client.get()
			.uri("/metrics")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> assertThat(body).contains("jvm_memory_used_bytes")
				.contains("http_server_requests_seconds"));
	}

	@Test
	void servesHealthAtTheActuatorPath() {
		this.client.get()
			.uri("/actuator/health")
			.exchange()
			.expectStatus()
			.isOk()
			.expectBody(String.class)
			.value((body) -> assertThat(body).contains("\"status\":\"UP\""));
	}

	@Test
	void doesNotExposeHealthAtTheRootPath() {
		this.client.get().uri("/health").exchange().expectStatus().isNotFound();
	}

}
