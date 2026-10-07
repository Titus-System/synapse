package synapse.api.job;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import ch.qos.logback.classic.spi.ILoggingEvent;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

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
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.support.SqlArrayValue;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * {@code regra-extraida} pelo caminho real: a aplicação inteira contra RabbitMQ e
 * PostgreSQL. A mensagem publicada na fila vira a versão raiz do job, o
 * {@code regra-submetida} sai pelo outbox até a fila do codegen, e a métrica do consumo
 * aparece em {@code /metrics} distinguindo a gravação da reentrega e do descarte.
 */
@EnabledIf("dockerIsAvailable")
class RegraExtraidaFimAFimTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final UUID USUARIO_ID = UUID.fromString("77777777-7777-4777-8777-777777777777");

	private static final String TEXTO_DA_REGRA = "dobrar a comissão dos vendedores da marca 10 no aniversário da loja";

	private static final String REPRESENTACAO = """
			{"nucleo":{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"marca":["10"],"cargo":["100"]},
			 "especificacoes":[{"ref":"elem.1","construto":"generico","descricao":"dobrar no aniversário da loja"}]}
			""";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = new JsonMapper();

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	private static int porta;

	private static RabbitTemplate rabbitTemplate;

	private static AmqpAdmin amqpAdmin;

	private static JdbcTemplate dono;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void subirAplicacao() {
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
		amqpAdmin = contexto.getBean(AmqpAdmin.class);
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE " + USUARIO_API + " WITH PASSWORD '" + SENHA + "'");
		dono.update("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES (?, 'rh-t202-e2e', 'x', 'RH', 'profissional_rh', now())
				""", USUARIO_ID);
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
	void extracaoPublicadaReabreOCicloEOConsumoApareceNasMetricasENosLogs() throws Exception {
		Job job = criarJobDeTexto();
		UUID jobId = job.id();
		UUID submissaoId = job.submissaoId();
		UUID extracaoId = criarExtracao(jobId, submissaoId);
		String evento = """
				{"job_id":"%s","submissao_id":"%s","extracao_id":"%s"}
				""".formatted(jobId, submissaoId, extracaoId).strip();

		List<ILoggingEvent> logs;
		try (CapturaDeLog captura = new CapturaDeLog(RegraExtraidaConsumidor.class)) {
			publicar(evento);
			await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> assertThat(versoes(jobId)).isEqualTo(1));
			logs = captura.eventos();
		}
		UUID regraId = Objects
			.requireNonNull(dono.queryForObject("SELECT id FROM regras WHERE job_id = ?", UUID.class, jobId));

		Message submetida = receberRegraSubmetida();
		String payload = new String(submetida.getBody(), StandardCharsets.UTF_8);
		ContratoDeEvento.validar("regra-submetida", payload);
		JsonNode corpo = JSON.readTree(payload);
		assertThat(corpo.path("job_id").asString()).isEqualTo(jobId.toString());
		assertThat(corpo.path("origem").asString()).isEqualTo("texto");
		assertThat(corpo.path("regra_id").asString()).isEqualTo(regraId.toString());
		assertThat(corpo.path("submissao_id").asString()).isEqualTo(submissaoId.toString());
		assertThat(submetida.getMessageProperties().getCorrelationId()).isEqualTo(jobId.toString());

		assertThat(logs).extracting(ILoggingEvent::getFormattedMessage)
			.containsSubsequence("consumo de regra-extraida iniciado",
					"regra-extraida persistida; ciclo do codegen reaberto");
		for (ILoggingEvent registro : logs) {
			String linha = CapturaDeLog.emJson(registro);
			ContratoDeEvento.validarLog(linha);
			assertThat(JSON.readTree(linha).path("job_id").asString()).isEqualTo(jobId.toString());
			assertThat(linha).doesNotContain("aniversário", "dobrar", "elem.1", "\"marca\"", "nucleo");
		}
		assertThat(CapturaDeLog.emJson(logs.getLast())).contains("\"regra_id\":\"" + regraId + "\"");

		publicar(evento);
		publicar("""
				{"job_id":"%s","submissao_id":"%s"}
				""".formatted(jobId, submissaoId).strip());
		publicar("isto não é json");
		await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
			String metricas = metricas();
			assertThat(metricas)
				.containsPattern("regra_extraida_consumo_total\\{motivo=\"nenhum\",resultado=\"persistida\"\\} 1\\.0")
				.containsPattern("regra_extraida_consumo_total\\{motivo=\"reentrega\",resultado=\"duplicada\"\\} 1\\.0")
				.containsPattern(
						"regra_extraida_consumo_total\\{motivo=\"evento_invalido\",resultado=\"descartada\"\\} 1\\.0")
				.containsPattern("regra_extraida_consumo_duracao_seconds_count\\{resultado=\"persistida\"\\} 1");
			assertThat(filaRegraExtraida().getMessageCount()).isZero();
		});

		assertThat(versoes(jobId)).isEqualTo(1);
		assertThat(
				dono.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ? AND tipo = 'regra-submetida'",
						Integer.class, jobId))
			.isEqualTo(1);
		assertThat(rabbitTemplate.receive(RabbitTopologyConfig.REGRA_SUBMETIDA, 1000)).isNull();
		assertThat(dono.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId))
			.isEqualTo("gerando_regra");
	}

	// --- Apoio ------------------------------------------------------------------------

	private record Job(UUID id, UUID submissaoId) {
	}

	private static Job criarJobDeTexto() {
		UUID submissaoId = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em)
				VALUES (?, 'texto', ?, now()) RETURNING id
				""", UUID.class, USUARIO_ID, TEXTO_DA_REGRA));
		UUID jobId = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES ('gerando_regra', ?, ?, ?, 485000, now()) RETURNING id
				""", UUID.class, USUARIO_ID, submissaoId, new SqlArrayValue("text", List.of("2025-11").toArray())));
		return new Job(jobId, submissaoId);
	}

	/** O que o codegen grava antes de publicar: prompt, resposta e a extração. */
	private static UUID criarExtracao(UUID jobId, UUID submissaoId) {
		UUID prompt = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
				VALUES (?, 'extracao_parametros', 'fixture', '{}'::jsonb, now()) RETURNING id
				""", UUID.class, jobId));
		UUID resposta = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO respostas_modelo (job_id, prompt_id, conteudo, criado_em)
				VALUES (?, ?, 'fixture', now()) RETURNING id
				""", UUID.class, jobId, prompt));
		return Objects.requireNonNull(dono.queryForObject(
				"""
						INSERT INTO extracoes_regras (job_id, submissao_id, resposta_id, representacao, rebaixamentos, criado_em)
						VALUES (?, ?, ?, ?::jsonb, '[]'::jsonb, now()) RETURNING id
						""",
				UUID.class, jobId, submissaoId, resposta, REPRESENTACAO));
	}

	private static void publicar(String corpo) {
		Message mensagem = MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setType(RabbitTopologyConfig.REGRA_EXTRAIDA)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.REGRA_EXTRAIDA, mensagem);
	}

	private static Message receberRegraSubmetida() {
		AtomicReference<Message> recebida = new AtomicReference<>();
		await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
			recebida.compareAndSet(null, rabbitTemplate.receive(RabbitTopologyConfig.REGRA_SUBMETIDA));
			assertThat(recebida.get()).isNotNull();
		});
		return Objects.requireNonNull(recebida.get());
	}

	private static String metricas() throws Exception {
		HttpResponse<String> resposta = HTTP.send(
				HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/metrics")).GET().build(),
				HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(200);
		return resposta.body();
	}

	private static QueueInformation filaRegraExtraida() {
		return Objects.requireNonNull(amqpAdmin.getQueueInfo(RabbitTopologyConfig.REGRA_EXTRAIDA));
	}

	private static int versoes(UUID jobId) {
		return Objects
			.requireNonNull(dono.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Integer.class, jobId));
	}

}
