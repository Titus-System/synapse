package synapse.api.job;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * Sobe a aplicação inteira contra um Postgres e um RabbitMQ reais (as mesmas imagens do
 * compose), faz {@code POST /jobs} de verdade e confirma que {@code regra-submetida}
 * chega à fila - o mesmo formato de teste que {@code EtapaAlteradaConsumidorTests} usa no
 * sentido contrário (da fila ao SSE). O mecanismo do outbox em si (falha de publicação,
 * ordem, concorrência, {@code SKIP LOCKED}) está coberto por {@code OutboxTests}; aqui só
 * o caminho feliz fim a fim, que é o que os critérios de aceitação da T-040 pedem.
 */
@EnabledIf("dockerIsAvailable")
class RegraSubmetidaPublicacaoTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "66666666-6666-4666-8666-666666666666";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	private static int porta;

	private static RabbitTemplate rabbitTemplate;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void subirAplicacao() throws Exception {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		rabbitmq = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		rabbitmq.start();

		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=" + USUARIO_API,
					"--app.postgres.password=" + SENHA, "--app.rabbitmq.host=" + rabbitmq.getHost(),
					"--app.rabbitmq.port=" + rabbitmq.getAmqpPort(),
					"--app.rabbitmq.user=" + rabbitmq.getAdminUsername(),
					"--app.rabbitmq.password=" + rabbitmq.getAdminPassword(),
					"--management.health.rabbit.enabled=false", "--management.health.db.enabled=false",
					"--app.outbox.poll-interval=200ms");

		porta = Integer.parseInt(Objects.requireNonNull(contexto.getEnvironment().getProperty("local.server.port")));
		rabbitTemplate = contexto.getBean(RabbitTemplate.class);

		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("ALTER ROLE " + USUARIO_API + " WITH PASSWORD '" + SENHA + "'");
			statement.execute("""
					INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
					VALUES ('%s', 'rh', 'x', 'RH', 'profissional_rh', now())
					""".formatted(USUARIO_ID));
		}
	}

	@AfterAll
	static void derrubarTudo() {
		if (contexto != null) {
			contexto.close();
		}
		if (postgres != null) {
			postgres.stop();
		}
		if (rabbitmq != null) {
			rabbitmq.stop();
		}
	}

	// --- Cenário --------------------------------------------------------------------

	@Test
	void postJobsPublicaRegraSubmetidaNaFilaComOPayloadConformeAoContrato() throws Exception {
		HttpRequest requisicao = HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/jobs"))
			.header("Content-Type", "application/json")
			.POST(HttpRequest.BodyPublishers.ofString(CriarJobControllerTests.FORMULARIO))
			.build();
		HttpResponse<String> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(201);
		JsonNode job = JSON.readTree(resposta.body());
		UUID jobId = UUID.fromString(job.path("id").asString());
		UUID submissaoId = UUID.fromString(job.path("submissao_id").asString());
		UUID regraId = UUID.fromString(job.path("regra").path("id").asString());

		AtomicReference<Message> recebida = new AtomicReference<>();
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
			recebida.compareAndSet(null, rabbitTemplate.receive(RabbitTopologyConfig.REGRA_SUBMETIDA));
			assertThat(recebida.get()).isNotNull();
		});
		Message mensagem = Objects.requireNonNull(recebida.get());

		MessageProperties propriedades = mensagem.getMessageProperties();
		assertThat(propriedades.getType()).isEqualTo(RabbitTopologyConfig.REGRA_SUBMETIDA);
		assertThat(propriedades.getCorrelationId()).isEqualTo(jobId.toString());
		assertThat(propriedades.getContentType()).isEqualTo(MessageProperties.CONTENT_TYPE_JSON);
		assertThat(propriedades.getReceivedDeliveryMode()).isEqualTo(MessageDeliveryMode.PERSISTENT);
		assertThat(propriedades.getMessageId()).isEqualTo(idDoEventoNoOutbox(jobId));

		String corpoPublicado = new String(mensagem.getBody(), StandardCharsets.UTF_8);
		ContratoDeEvento.validar("regra-submetida", corpoPublicado);
		JsonNode payload = JSON.readTree(corpoPublicado);
		assertThat(payload.path("orcamento").isNumber()).isTrue();
		assertThat(payload.path("orcamento").decimalValue()).isEqualByComparingTo("485000.1234567890123456789");
		assertThat(payload.path("job_id").asString()).isEqualTo(jobId.toString());
		assertThat(payload.path("origem").asString()).isEqualTo("formulario");
		assertThat(payload.path("competencias").valueStream().map(JsonNode::asString).toList())
			.containsExactly("2025-11");
		assertThat(payload.path("submissao_id").asString()).isEqualTo(submissaoId.toString());
		assertThat(payload.path("regra_id").asString()).isEqualTo(regraId.toString());

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(publicadoEm(jobId)).isTrue());
		assertThat(rabbitTemplate.receive(RabbitTopologyConfig.REGRA_SUBMETIDA)).as("nenhuma segunda cópia na fila")
			.isNull();
	}

	// --- Apoio ----------------------------------------------------------------------

	private static String idDoEventoNoOutbox(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement.executeQuery("SELECT id FROM outbox_events WHERE job_id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getString("id");
		}
	}

	private static Boolean publicadoEm(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement
					.executeQuery("SELECT publicado_em FROM outbox_events WHERE job_id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getTimestamp("publicado_em") != null;
		}
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

}
