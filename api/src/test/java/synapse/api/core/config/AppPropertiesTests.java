package synapse.api.core.config;

import java.time.Duration;

import org.junit.jupiter.api.Test;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@ActiveProfiles("test")
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

	/** Uma origem só, no default: a lista é separada por vírgula, não um valor único. */
	@Test
	void carriesTheCorsAllowedOrigins() {
		assertThat(this.properties.cors().allowedOrigins()).containsExactly("http://localhost:5173");
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
		assertThat(postgres.user()).isEqualTo("synapse_api");
		assertThat(postgres.jdbcUrl()).isEqualTo("jdbc:postgresql://localhost:5432/synapse_db");
	}

	/**
	 * O usuário de runtime e o dono do schema são credenciais distintas. Se um dia
	 * coincidirem por default, a aplicação passa a operar com permissão de estrutura e os
	 * GRANT das migrations deixam de delimitar qualquer coisa.
	 */
	@Test
	void separatesTheRuntimeUserFromTheSchemaOwner() {
		AppProperties.Postgres postgres = this.properties.postgres();
		assertThat(postgres.owner().user()).isEqualTo("postgres");
		assertThat(postgres.user()).isNotEqualTo(postgres.owner().user());
	}

	@Test
	void carriesTheOtherServicesDatabaseUsers() {
		AppProperties.Postgres.Roles roles = this.properties.postgres().roles();
		assertThat(roles.codegen()).isEqualTo("synapse_codegen");
		assertThat(roles.worker()).isEqualTo("synapse_worker");
	}

	@Test
	void carriesTheRabbitmqSettings() {
		AppProperties.Rabbitmq rabbitmq = this.properties.rabbitmq();
		assertThat(rabbitmq.host()).isEqualTo("localhost");
		assertThat(rabbitmq.port()).isEqualTo(5672);
		assertThat(rabbitmq.user()).isEqualTo("guest");
		assertThat(rabbitmq.password()).isEqualTo("guest");
		assertThat(rabbitmq.vhost()).isEqualTo("/");
	}

	@Test
	void fallsBackToTheMachineHostnameWhenHostIsBlank() {
		assertThat(new AppProperties.Observability("INFO", 1.0, "http://localhost:4318", "").host()).isNotBlank();
	}

	@Test
	void carriesTheSseSettings() {
		AppProperties.Sse sse = this.properties.sse();
		assertThat(sse.heartbeat()).isEqualTo(Duration.ofSeconds(15));
		assertThat(sse.timeout()).isEqualTo(Duration.ofMinutes(30));
	}

	/**
	 * O perfil de teste desliga o poller; o intervalo é o default do application.yaml.
	 */
	@Test
	void carriesTheOutboxSettings() {
		AppProperties.Outbox outbox = this.properties.outbox();
		assertThat(outbox.enabled()).isFalse();
		assertThat(outbox.pollInterval()).isEqualTo(Duration.ofSeconds(1));
	}

}
