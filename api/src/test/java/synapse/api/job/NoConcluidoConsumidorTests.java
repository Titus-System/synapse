package synapse.api.job;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
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

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * Sobe a aplicação inteira contra um Postgres e um RabbitMQ reais e publica na fila
 * {@code no-concluido} como o codegen publicaria, para confirmar a gravação da trilha de
 * auditoria e da linha de {@code simulacoes} (T-046).
 */
@EnabledIf("dockerIsAvailable")
class NoConcluidoConsumidorTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "66666666-6666-4666-8666-666666666666";

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	private static RabbitTemplate rabbitTemplate;

	private static AmqpAdmin amqpAdmin;

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
					"--management.health.rabbit.enabled=false", "--management.health.db.enabled=false");

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
	void confirmarQueAFilaEsvaziou() {
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getMessageCount()).isZero());
	}

	// --- Cenários -----------------------------------------------------------------

	@Test
	void noDeGeracaoDeCodigoGravaATrilhaEASimulacao() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID codigoGeradoId = criarCodigoGerado(jobId, regraId);
		UUID eventoId = UUID.randomUUID();

		publicar(eventoId, jobId, "geracao_codigo", regraId, codigoGeradoId, null, null);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(simulacaoPorCodigoGerado(codigoGeradoId)).isNotNull());
		UUID simulacaoId = Objects.requireNonNull(simulacaoPorCodigoGerado(codigoGeradoId));
		assertThat(trilhaUnica(jobId).simulacaoId()).isEqualTo(simulacaoId);
		assertThat(trilhaUnica(jobId).no()).isEqualTo("geracao_codigo");
	}

	@Test
	void aMesmaMensagemEntregueDuasVezesGravaUmaUnicaLinha() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID codigoGeradoId = criarCodigoGerado(jobId, regraId);
		UUID eventoId = UUID.randomUUID();

		publicar(eventoId, jobId, "geracao_codigo", regraId, codigoGeradoId, null, null);
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(contarTrilhas(jobId)).isEqualTo(1));
		publicar(eventoId, jobId, "geracao_codigo", regraId, codigoGeradoId, null, null);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getMessageCount()).isZero());
		assertThat(contarTrilhas(jobId)).isEqualTo(1);
	}

	@Test
	void umNoPosteriorLigaNaSimulacaoJaCriada() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID codigoGeradoId = criarCodigoGerado(jobId, regraId);
		publicar(UUID.randomUUID(), jobId, "geracao_codigo", regraId, codigoGeradoId, null, null);
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(simulacaoPorCodigoGerado(codigoGeradoId)).isNotNull());
		UUID simulacaoId = Objects.requireNonNull(simulacaoPorCodigoGerado(codigoGeradoId));

		publicar(UUID.randomUUID(), jobId, "interpretacao_resultado", null, null, simulacaoId, null);

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(contarTrilhas(jobId)).isEqualTo(2));
		List<Trilha> trilhas = trilhas(jobId);
		Trilha interpretacao = trilhas.stream()
			.filter((t) -> t.no().equals("interpretacao_resultado"))
			.findFirst()
			.orElseThrow();
		assertThat(interpretacao.simulacaoId()).isEqualTo(simulacaoId);
	}

	@Test
	void umResultadoJaGravadoAntesDoNoDeGeracaoDeCodigoEAmarradoDeImediato() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID codigoGeradoId = criarCodigoGerado(jobId, regraId);
		UUID resultadoId = criarResultado(jobId, codigoGeradoId);

		publicar(UUID.randomUUID(), jobId, "geracao_codigo", regraId, codigoGeradoId, null, null);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(resultadoDaSimulacao(codigoGeradoId)).isEqualTo(resultadoId));
	}

	@Test
	void noDeConfirmacaoEDescartadoSemGravarNadaDeNovo() throws Exception {
		UUID jobId = criarJob();

		publicar(UUID.randomUUID(), jobId, "confirmacao", null, null, null, null);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getMessageCount()).isZero());
		assertThat(contarTrilhas(jobId)).isZero();
	}

	@Test
	void noDeJobDesconhecidoEDescartadoSemDerrubarOConsumidor() throws Exception {
		publicar(UUID.randomUUID(), UUID.randomUUID(), "decisao", null, null, null, null);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getMessageCount()).isZero());
		assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getConsumerCount()).isGreaterThan(0);

		UUID jobId = criarJob();
		publicar(UUID.randomUUID(), jobId, "decisao", null, null, null, null);
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(contarTrilhas(jobId)).isEqualTo(1));
	}

	@Test
	void noForaDoVocabularioEDescartadoSemDerrubarOConsumidor() throws Exception {
		UUID jobId = criarJob();

		publicar(UUID.randomUUID(), jobId, "no_inventado", null, null, null, null);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getMessageCount()).isZero());
		assertThat(contarTrilhas(jobId)).isZero();
	}

	@Test
	void semResumoNaConclusaoEDescartadoSemDerrubarOConsumidor() throws Exception {
		UUID jobId = criarJob();
		String corpo = """
				{"evento_id":"%s","job_id":"%s","no":"decisao","concluido_em":"2025-11-28T14:32:10Z","conclusao":{}}
				""".formatted(UUID.randomUUID(), jobId).strip();
		enviarCorpo(corpo);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getMessageCount()).isZero());
		assertThat(contarTrilhas(jobId)).isZero();
	}

	@Test
	void jsonMalformadoEDescartadoSemDerrubarOConsumidor() throws Exception {
		Message mensagemInvalida = MessageBuilder.withBody("isto não é json".getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setType(RabbitTopologyConfig.NO_CONCLUIDO)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.NO_CONCLUIDO, mensagemInvalida);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getMessageCount()).isZero());

		UUID jobId = criarJob();
		publicar(UUID.randomUUID(), jobId, "decisao", null, null, null, null);
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(contarTrilhas(jobId)).isEqualTo(1));
	}

	// --- Apoio ----------------------------------------------------------------------

	private record Trilha(String no, @Nullable UUID simulacaoId) {
	}

	private static void publicar(UUID eventoId, UUID jobId, String no, @Nullable UUID regraId,
			@Nullable UUID codigoGeradoId, @Nullable UUID simulacaoId, @Nullable UUID promptId) {
		StringBuilder corpo = new StringBuilder(
				"{\"evento_id\":\"%s\",\"job_id\":\"%s\",\"no\":\"%s\",".formatted(eventoId, jobId, no));
		corpo.append("\"concluido_em\":\"2025-11-28T14:32:10Z\",\"conclusao\":{\"resumo\":\"x\"}");
		if (regraId != null) {
			corpo.append(",\"regra_id\":\"").append(regraId).append('"');
		}
		if (codigoGeradoId != null) {
			corpo.append(",\"codigo_gerado_id\":\"").append(codigoGeradoId).append('"');
		}
		if (simulacaoId != null) {
			corpo.append(",\"simulacao_id\":\"").append(simulacaoId).append('"');
		}
		if (promptId != null) {
			corpo.append(",\"prompt_id\":\"").append(promptId).append('"');
		}
		corpo.append('}');
		enviarCorpo(corpo.toString());
	}

	private static void enviarCorpo(String corpo) {
		Message mensagem = MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setType(RabbitTopologyConfig.NO_CONCLUIDO)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.NO_CONCLUIDO, mensagem);
	}

	private static UUID criarJob() throws SQLException {
		UUID jobId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO jobs (id, status, usuario_id, competencias, orcamento, criado_em)
					VALUES ('%s', 'gerando_regra', '%s', '{2025-08}', 1000, now())
					""".formatted(jobId, USUARIO_ID));
		}
		return jobId;
	}

	private static UUID criarRegra(UUID jobId) throws SQLException {
		UUID regraId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
					VALUES ('%s', '%s', 1, 'confirmacao_usuario', '{}'::jsonb, '[]'::jsonb, '%s', now())
					""".formatted(regraId, jobId, "0".repeat(64)));
		}
		return regraId;
	}

	// prompts, codigos_gerados e resultados_simulacao só o codegen/worker escrevem em
	// produção (AGENTS.md); a fixture usa o usuário dono para simular o que eles já
	// teriam gravado.
	private static UUID criarCodigoGerado(UUID jobId, UUID regraId) throws SQLException {
		UUID promptId = UUID.randomUUID();
		UUID codigoGeradoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
					VALUES ('%s', '%s', 'geracao_codigo', 'x', '{}'::jsonb, now())
					""".formatted(promptId, jobId));
			statement.execute("""
					INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
					VALUES ('%s', '%s', '%s', 'python', 'x', '%s', now())
					""".formatted(codigoGeradoId, jobId, regraId, promptId));
		}
		return codigoGeradoId;
	}

	private static UUID criarResultado(UUID jobId, UUID codigoGeradoId) throws SQLException {
		UUID resultadoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute(
					"""
							INSERT INTO resultados_simulacao (id, job_id, codigo_gerado_id, status, veredito, assercoes, criado_em)
							VALUES ('%s', '%s', '%s', 'sucesso', 'viavel', '[]'::jsonb, now())
							"""
						.formatted(resultadoId, jobId, codigoGeradoId));
		}
		return resultadoId;
	}

	private static @Nullable UUID simulacaoPorCodigoGerado(UUID codigoGeradoId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery(
						"SELECT id FROM simulacoes WHERE codigo_gerado_id = '%s'".formatted(codigoGeradoId))) {
			return rs.next() ? rs.getObject("id", UUID.class) : null;
		}
	}

	private static @Nullable UUID resultadoDaSimulacao(UUID codigoGeradoId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT resultado_id FROM simulacoes WHERE codigo_gerado_id = '%s'"
						.formatted(codigoGeradoId))) {
			assertThat(rs.next()).isTrue();
			return rs.getObject("resultado_id", UUID.class);
		}
	}

	private static List<Trilha> trilhas(UUID jobId) throws SQLException {
		List<Trilha> trilhas = new ArrayList<>();
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery(
						"SELECT no, simulacao_id FROM trilhas_auditoria WHERE job_id = '%s' ORDER BY concluido_em"
							.formatted(jobId))) {
			while (rs.next()) {
				trilhas.add(new Trilha(Objects.requireNonNull(rs.getString("no")),
						rs.getObject("simulacao_id", UUID.class)));
			}
		}
		return trilhas;
	}

	private static Trilha trilhaUnica(UUID jobId) throws SQLException {
		List<Trilha> trilhas = trilhas(jobId);
		assertThat(trilhas).hasSize(1);
		return trilhas.getFirst();
	}

	private static int contarTrilhas(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT count(*) FROM trilhas_auditoria WHERE job_id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getInt(1);
		}
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static QueueInformation infoDaFila(String nome) {
		return Objects.requireNonNull(amqpAdmin.getQueueInfo(nome), "fila " + nome + " não encontrada");
	}

}
