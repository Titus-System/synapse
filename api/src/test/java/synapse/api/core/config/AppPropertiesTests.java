package synapse.api.core.config;

import org.junit.jupiter.api.Test;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class AppPropertiesTests {

	@Autowired
	private AppProperties properties;

	@Test
	void isInjectable() {
		assertThat(this.properties).isNotNull();
		assertThat(this.properties.environment()).isEqualTo("development");
	}

	@Test
	void carriesTheServiceIdentity() {
		assertThat(this.properties.service().name()).isEqualTo("synapse-api");
		assertThat(this.properties.service().version()).isEqualTo("0.0.1-SNAPSHOT");
		assertThat(this.properties.service().publicUrl()).isEqualTo("http://localhost:8080");
	}

	@Test
	void carriesTheObservabilitySettings() {
		AppProperties.Observability observability = this.properties.observability();
		assertThat(observability.logLevel()).isEqualTo("INFO");
		assertThat(observability.traceSampleRate()).isEqualTo(1.0);
		assertThat(observability.otlpEndpoint()).isEqualTo("http://localhost:4318");
		assertThat(observability.host()).isNotBlank();
	}

	@Test
	void carriesThePostgresSettingsAndBuildsTheJdbcUrl() {
		AppProperties.Postgres postgres = this.properties.postgres();
		assertThat(postgres.host()).isEqualTo("localhost");
		assertThat(postgres.port()).isEqualTo(5432);
		assertThat(postgres.user()).isEqualTo("postgres");
		assertThat(postgres.jdbcUrl()).isEqualTo("jdbc:postgresql://localhost:5432/api_db");
	}

	@Test
	void fallsBackToTheMachineHostnameWhenHostIsBlank() {
		assertThat(new AppProperties.Observability("INFO", 1.0, "http://localhost:4318", "").host()).isNotBlank();
	}

}
