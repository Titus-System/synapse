package synapse.api.job;

import java.io.IOException;
import java.io.InputStream;
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
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;

import org.springframework.amqp.core.AmqpAdmin;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.core.QueueInformation;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * Sobe a aplicação inteira contra um Postgres e um RabbitMQ reais (as mesmas imagens do
 * compose) e publica na fila {@code etapa-alterada} como o codegen publicaria, para
 * confirmar o comportamento observável ponta a ponta: da fila ao stream SSE. O
 * comportamento interno de {@link EtapaAlteradaConsumidor} isolado de rede está coberto
 * por asserções mais finas caso um teste unitário seja necessário no futuro; hoje a fatia
 * inteira é pequena o bastante para caber num teste de integração só.
 */
@EnabledIf("dockerIsAvailable")
class EtapaAlteradaConsumidorTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "44444444-4444-4444-8444-444444444444";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	private static int porta;

	private static EmissoresSse emissoresSse;

	private static RabbitTemplate rabbitTemplate;

	private static AmqpAdmin amqpAdmin;

	private final List<StreamCliente> abertos = new ArrayList<>();

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
					"--app.sse.heartbeat=200ms");

		porta = Integer.parseInt(Objects.requireNonNull(contexto.getEnvironment().getProperty("local.server.port")));
		emissoresSse = contexto.getBean(EmissoresSse.class);
		rabbitTemplate = contexto.getBean(RabbitTemplate.class);
		amqpAdmin = contexto.getBean(AmqpAdmin.class);

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

	@AfterEach
	void fecharStreamsAbertosEConferirQueNaoVazou() {
		for (StreamCliente cliente : this.abertos) {
			cliente.fechar();
		}
		this.abertos.clear();
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(emissoresSse.conexoesAtivas()).isZero());
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
	}

	// --- Cenários -----------------------------------------------------------------

	@Test
	void publicarNaFilaFazOEventoChegarAoClienteSseInscritoNaqueleJob() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "geracao_codigo", "iniciada");

		String bloco = cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));
		assertThat(bloco).contains("\"etapa\":\"geracao_codigo\"").contains("\"status\":\"iniciada\"");
	}

	@Test
	void oConsumoDoEventoNaoAlteraOStatusNemGeraTransicao() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "delegacao_worker", "iniciada");
		cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));

		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(contarTransicoes(jobId)).isZero();
	}

	@Test
	void entrarEmDelegacaoWorkerLevaOJobDeGerandoRegraASimulandoEAnunciaOEstado() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "delegacao_worker", "iniciada");

		String blocoEstado = cliente.aguardarBloco("\"status_anterior\":\"gerando_regra\"", Duration.ofSeconds(10));
		assertThat(blocoEstado).contains("\"status\":\"simulando\"");
		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(destinosDasTransicoes(jobId)).containsExactly("simulando");
		assertThat(cliente.conteudo().indexOf("event:etapa"))
			.isLessThan(cliente.conteudo().indexOf("\"status_anterior\""));
	}

	@Test
	void aMesmaEtapaEntregueDuasVezesProduzUmaUnicaTransicao() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);

		publicar(jobId, "delegacao_worker", "iniciada");
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("simulando"));
		publicar(jobId, "delegacao_worker", "iniciada");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
		assertThat(destinosDasTransicoes(jobId)).containsExactly("simulando");
	}

	@Test
	void statusErroLevaOJobDeGerandoRegraAErroFechaOStreamEGravaOMotivo() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "geracao_codigo", "erro");

		String blocoEstado = cliente.aguardarBloco("\"status_anterior\":\"gerando_regra\"", Duration.ofSeconds(10));
		assertThat(blocoEstado).contains("\"status\":\"erro\"").contains("\"motivo\"");
		cliente.aguardarFimDoStream(Duration.ofSeconds(10));
		assertThat(cliente.conteudo().indexOf("event:etapa"))
			.isLessThan(cliente.conteudo().indexOf("\"status_anterior\""));
		assertThat(statusPersistido(jobId)).isEqualTo("erro");
		assertThat(motivoDaUltimaTransicao(jobId)).isEqualTo("erro_geracao_codigo");
	}

	@Test
	void statusErroForaDeGerandoRegraSoRepassaAEtapa() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "geracao_codigo", "erro");
		cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));

		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(contarTransicoes(jobId)).isZero();
		assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(1);
	}

	@Test
	void etapaDeJobDesconhecidoEDescartadaSemDerrubarOConsumidor() throws Exception {
		publicar(UUID.randomUUID(), "delegacao_worker", "iniciada");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
		assertThat(infoDaFilaDeEtapaAlterada().getConsumerCount()).isGreaterThan(0);

		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);
		publicar(jobId, "delegacao_worker", "iniciada");
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("simulando"));
	}

	@Test
	void eventoDeJobSemClienteConectadoEConsumidoSemErro() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);

		publicar(jobId, "geracao_codigo", "iniciada");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
		assertThat(emissoresSse.conexoesAtivas()).isZero();
	}

	@Test
	void etapaForaDoVocabularioEDescartadaSemChegarAoCliente() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "etapa_inventada", "iniciada");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
		assertThat(infoDaFilaDeEtapaAlterada().getConsumerCount()).isGreaterThan(0);
		assertThat(cliente.conteudo()).doesNotContain("event:etapa");
	}

	@Test
	void jsonMalformadoEDescartadoSemDerrubarOConsumidor() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);

		Message mensagemInvalida = MessageBuilder.withBody("isto não é json".getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setType(RabbitTopologyConfig.ETAPA_ALTERADA)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.ETAPA_ALTERADA, mensagemInvalida);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());

		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		publicar(jobId, "geracao_codigo", "iniciada");
		String bloco = cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));
		assertThat(bloco).contains("\"etapa\":\"geracao_codigo\"");
	}

	// --- Apoio ----------------------------------------------------------------------

	private static void publicar(UUID jobId, String etapa, String status) {
		String corpo = """
				{"job_id":"%s","etapa":"%s","status":"%s"}
				""".formatted(jobId, etapa, status).strip();
		Message mensagem = MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setCorrelationId(jobId.toString())
			.setType(RabbitTopologyConfig.ETAPA_ALTERADA)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.ETAPA_ALTERADA, mensagem);
	}

	private static URI uri(UUID jobId) {
		return URI.create("http://localhost:" + porta + "/jobs/" + jobId + "/events");
	}

	private StreamCliente conectar(UUID jobId) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest.newBuilder(uri(jobId)).GET().build();
		HttpResponse<InputStream> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofInputStream());
		StreamCliente cliente = new StreamCliente(resposta);
		this.abertos.add(cliente);
		return cliente;
	}

	private static UUID criarJob(JobStatus status) throws SQLException {
		UUID jobId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO jobs (id, status, usuario_id, competencias, orcamento, criado_em)
					VALUES ('%s', '%s', '%s', '{2025-08}', 1000, now())
					""".formatted(jobId, status.paraColuna(), USUARIO_ID));
		}
		return jobId;
	}

	private static String statusPersistido(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement.executeQuery("SELECT status FROM jobs WHERE id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getString("status");
		}
	}

	private static int contarTransicoes(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement
					.executeQuery("SELECT count(*) FROM job_transicoes WHERE job_id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getInt(1);
		}
	}

	private static List<String> destinosDasTransicoes(UUID jobId) throws SQLException {
		List<String> destinos = new ArrayList<>();
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement
					.executeQuery("SELECT status_novo FROM job_transicoes WHERE job_id = '%s' ORDER BY ocorrido_em"
						.formatted(jobId))) {
			while (rs.next()) {
				destinos.add(Objects.requireNonNull(rs.getString("status_novo")));
			}
		}
		return destinos;
	}

	private static @Nullable String motivoDaUltimaTransicao(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement.executeQuery(
						"SELECT motivo FROM job_transicoes WHERE job_id = '%s' ORDER BY ocorrido_em DESC LIMIT 1"
							.formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getString("motivo");
		}
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static QueueInformation infoDaFilaDeEtapaAlterada() {
		return Objects.requireNonNull(amqpAdmin.getQueueInfo(RabbitTopologyConfig.ETAPA_ALTERADA),
				"fila " + RabbitTopologyConfig.ETAPA_ALTERADA + " não encontrada");
	}

}
