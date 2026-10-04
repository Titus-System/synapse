package synapse.api.job;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.time.Instant;
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
import tools.jackson.databind.json.JsonMapper;

import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
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
 * Sobe a aplicação contra um Postgres e um RabbitMQ reais e leva um job a um estado
 * terminal pelos dois caminhos que existem: a ação do usuário, por HTTP, e a falha que
 * chega do codegen, por {@code etapa-alterada}. Nos dois, {@code job-encerrado} tem de
 * chegar à fila com o id e o instante da transição terminal gravada. A gravação na mesma
 * transação, o rollback e a reentrega estão em {@link MaquinaDeEstadosDoJobTests}; aqui,
 * o caminho pelo outbox até o broker.
 */
@EnabledIf("dockerIsAvailable")
class JobEncerradoPublicacaoTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "66666666-6666-4666-8666-666666666666";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = new JsonMapper();

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

	@Test
	void cancelarPeloHttpPublicaOEncerramentoComOIdEOInstanteDaTransicao() throws Exception {
		UUID jobId = criarJobAguardandoDecisao();

		HttpResponse<String> resposta = HTTP
			.send(HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/jobs/" + jobId + "/actions"))
				.header("Content-Type", "application/json")
				.POST(HttpRequest.BodyPublishers.ofString("{\"acao\":\"cancelar\"}"))
				.build(), HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(200);

		JsonNode evento = encerramentoPublicado(jobId);
		assertThat(evento.path("status").asString()).isEqualTo("cancelado");
		assertThat(rabbitTemplate.receive(RabbitTopologyConfig.JOB_ENCERRADO)).as("nenhuma segunda cópia na fila")
			.isNull();
	}

	@Test
	void falhaNaGeracaoPublicaOEncerramentoEmErro() throws Exception {
		HttpResponse<String> resposta = HTTP
			.send(HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/jobs"))
				.header("Content-Type", "application/json")
				.POST(HttpRequest.BodyPublishers.ofString(CriarJobControllerTests.FORMULARIO))
				.build(), HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(201);
		UUID jobId = UUID.fromString(JSON.readTree(resposta.body()).path("id").asString());

		publicarEtapaComErro(jobId);

		JsonNode evento = encerramentoPublicado(jobId);
		assertThat(evento.path("status").asString()).isEqualTo("erro");
	}

	// --- Apoio ----------------------------------------------------------------------

	/**
	 * Espera o evento do job na fila e confere o que vale para qualquer encerramento: o
	 * contrato, a referência à transição terminal e o instante dela, o mesmo de
	 * {@code finalizado_em}.
	 */
	private static JsonNode encerramentoPublicado(UUID jobId) throws Exception {
		AtomicReference<Message> recebida = new AtomicReference<>();
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
			recebida.compareAndSet(null, rabbitTemplate.receive(RabbitTopologyConfig.JOB_ENCERRADO));
			assertThat(recebida.get()).isNotNull();
		});
		Message mensagem = Objects.requireNonNull(recebida.get());
		MessageProperties propriedades = mensagem.getMessageProperties();
		assertThat(propriedades.getType()).isEqualTo(RabbitTopologyConfig.JOB_ENCERRADO);
		assertThat(propriedades.getCorrelationId()).isEqualTo(jobId.toString());
		assertThat(propriedades.getReceivedDeliveryMode()).isEqualTo(MessageDeliveryMode.PERSISTENT);

		String corpo = new String(mensagem.getBody(), StandardCharsets.UTF_8);
		ContratoDeEvento.validar("job-encerrado", corpo);
		JsonNode evento = JSON.readTree(corpo);
		assertThat(evento.path("job_id").asString()).isEqualTo(jobId.toString());
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT t.id, t.ocorrido_em, j.finalizado_em
						FROM job_transicoes t JOIN jobs j ON j.id = t.job_id
						WHERE t.job_id = '%s' AND t.status_novo = j.status
						""".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			assertThat(evento.path("evento_id").asString()).isEqualTo(rs.getString("id"));
			Instant encerradoEm = Instant.parse(evento.path("encerrado_em").asString());
			assertThat(encerradoEm).isEqualTo(rs.getTimestamp("ocorrido_em").toInstant())
				.isEqualTo(rs.getTimestamp("finalizado_em").toInstant());
		}
		return evento;
	}

	private static UUID criarJobAguardandoDecisao() throws SQLException {
		UUID jobId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO jobs (id, status, usuario_id, competencias, orcamento, criado_em)
					VALUES ('%s', 'aguardando_decisao_usuario', '%s', '{2025-11}', 500000, now())
					""".formatted(jobId, USUARIO_ID));
			statement.execute("""
					INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
					VALUES ('%s', 1, 'confirmacao_usuario',
					        '{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"loja":["13"],"marca":["10"],
					          "cargo":["100"],"percentual":0.02}'::jsonb, '[]'::jsonb, 'hash', now())
					""".formatted(jobId));
			statement.execute("""
					INSERT INTO job_transicoes (job_id, status_anterior, status_novo, ocorrido_em, ator)
					VALUES ('%s', NULL, 'aguardando_decisao_usuario', now(), 'sistema')
					""".formatted(jobId));
		}
		return jobId;
	}

	private static void publicarEtapaComErro(UUID jobId) {
		String corpo = """
				{"job_id":"%s","etapa":"geracao_codigo","status":"erro"}
				""".formatted(jobId).strip();
		Message mensagem = MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setCorrelationId(jobId.toString())
			.setType(RabbitTopologyConfig.ETAPA_ALTERADA)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.ETAPA_ALTERADA, mensagem);
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

}
