package synapse.api.submissoes;

import java.io.ByteArrayOutputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;

import com.sun.net.httpserver.HttpServer;
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
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.job.ContratoDeEvento;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * A correção por voz até a fila que o codegen consome, contra um Postgres e um RabbitMQ
 * reais e com o outbox ligado: nada é publicado enquanto o áudio não é transcrito, e
 * depois sai um único {@code correcao-submetida} conforme ao contrato. O provedor de
 * transcrição é um servidor HTTP local que responde como o Deepgram.
 */
@EnabledIf("dockerDisponivel")
class CorrecaoPorVozPublicacaoTests {

	private static final UUID USUARIO = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final UUID JOB = UUID.fromString("11111111-1111-4111-8111-111111111111");

	private static final UUID REGRA = UUID.fromString("22222222-2222-4222-8222-222222222222");

	private static final UUID RODADA = UUID.fromString("33333333-3333-4333-8333-333333333333");

	private static final String TEXTO = "Correção privada falada: o percentual é de dois e meio.";

	private static final JsonMapper JSON = new JsonMapper();

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static HttpServer provedor;

	private static ConfigurableApplicationContext contexto;

	private static JdbcTemplate dono;

	private static String base;

	static boolean dockerDisponivel() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void iniciar() throws Exception {
		provedor = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
		provedor.setExecutor(Executors.newCachedThreadPool());
		provedor.createContext("/v1/listen", exchange -> {
			exchange.getRequestBody().readAllBytes();
			byte[] corpo = ("{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":\"" + TEXTO + "\"}]}]}}")
				.getBytes(StandardCharsets.UTF_8);
			exchange.getResponseHeaders().add("Content-Type", "application/json");
			exchange.sendResponseHeaders(200, corpo.length);
			try (var saida = exchange.getResponseBody()) {
				saida.write(corpo);
			}
		});
		provedor.start();
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		rabbitmq = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		rabbitmq.start();
		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.keycloak.enabled=false", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
					"--app.postgres.password=senha-de-teste", "--app.rabbitmq.host=" + rabbitmq.getHost(),
					"--app.rabbitmq.port=" + rabbitmq.getAmqpPort(),
					"--app.rabbitmq.user=" + rabbitmq.getAdminUsername(),
					"--app.rabbitmq.password=" + rabbitmq.getAdminPassword(),
					"--management.health.rabbit.enabled=false", "--management.health.db.enabled=false",
					"--app.outbox.poll-interval=200ms", "--app.transcription.api-key=chave-ficticia-do-teste",
					"--app.transcription.base-url=http://127.0.0.1:" + provedor.getAddress().getPort(),
					"--app.transcription.connect-timeout-ms=1000", "--app.transcription.read-timeout-ms=5000",
					"--app.transcription.processor.enabled=false",
					"--app.transcription.processor.reservation-timeout=30s");
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		base = "http://localhost:" + contexto.getEnvironment().getProperty("local.server.port");
	}

	@AfterAll
	static void encerrar() {
		if (contexto != null) {
			contexto.close();
		}
		if (postgres != null) {
			postgres.stop();
		}
		if (rabbitmq != null) {
			rabbitmq.stop();
		}
		if (provedor != null) {
			provedor.stop(0);
		}
	}

	@Test
	void correcaoPorVozChegaAFilaDoCodegenSoDepoisDaTranscricao() throws Exception {
		dono.update(
				"INSERT INTO usuarios (id, login, nome, papel, criado_em) VALUES (?, 'rh', 'RH', 'profissional_rh', now())",
				USUARIO);
		dono.update(
				"INSERT INTO jobs (id, usuario_id, status, competencias, orcamento, criado_em) VALUES (?, ?, 'aguardando_confirmacao_parametros', ARRAY['2025-11'], 485000.12, now())",
				JOB, USUARIO);
		dono.update(
				"INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em) VALUES (?, ?, 1, 'extracao', '{}', '[]', ?, now())",
				REGRA, JOB, "a".repeat(64));
		dono.update(
				"INSERT INTO rodadas_correcao (id, job_id, regra_analisada_id, conflitos, estado, criada_em, atualizada_em) VALUES (?, ?, ?, '[{\"elementos\":[\"nucleo.percentual\"],\"motivo\":\"percentual ausente\"}]'::jsonb, 'pendente', now(), now())",
				RODADA, JOB, REGRA);
		RabbitTemplate rabbit = contexto.getBean(RabbitTemplate.class);

		var resposta = enviarVoz();
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(201);
		UUID submissao = UUID.fromString(JSON.readTree(resposta.body()).path("id").asString());
		assertThat(rabbit.receive(RabbitTopologyConfig.CORRECAO_SUBMETIDA, 1500))
			.as("nada é publicado antes da transcrição")
			.isNull();

		contexto.getBean(ProcessadorTranscricao.class).processarPendentes();

		AtomicReference<Message> recebida = new AtomicReference<>();
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
			recebida.compareAndSet(null, rabbit.receive(RabbitTopologyConfig.CORRECAO_SUBMETIDA));
			assertThat(recebida.get()).isNotNull();
		});
		Message mensagem = Objects.requireNonNull(recebida.get());
		MessageProperties propriedades = mensagem.getMessageProperties();
		assertThat(propriedades.getType()).isEqualTo(RabbitTopologyConfig.CORRECAO_SUBMETIDA);
		assertThat(propriedades.getCorrelationId()).isEqualTo(JOB.toString());
		assertThat(propriedades.getContentType()).isEqualTo(MessageProperties.CONTENT_TYPE_JSON);
		assertThat(propriedades.getReceivedDeliveryMode()).isEqualTo(MessageDeliveryMode.PERSISTENT);
		assertThat(propriedades.getMessageId()).isEqualTo(dono.queryForObject(
				"SELECT id::text FROM outbox_events WHERE job_id = ? AND tipo = 'correcao-submetida'", String.class,
				JOB));
		String corpo = new String(mensagem.getBody(), StandardCharsets.UTF_8);
		ContratoDeEvento.validar("correcao-submetida", corpo);
		assertThat(corpo).doesNotContain(TEXTO, "texto", "transcricao");
		JsonNode evento = JSON.readTree(corpo);
		assertThat(evento.path("job_id").asString()).isEqualTo(JOB.toString());
		assertThat(evento.path("regra_origem_id").asString()).isEqualTo(REGRA.toString());
		assertThat(evento.path("submissao_id").asString()).isEqualTo(submissao.toString());
		assertThat(evento.path("competencias").toString()).isEqualTo("[\"2025-11\"]");
		assertThat(dono.queryForObject("SELECT transcricao FROM submissoes WHERE id = ?", String.class, submissao))
			.as("o codegen lê o texto pela submissão")
			.isEqualTo(TEXTO);
		assertThat(dono.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, RODADA))
			.isEqualTo("em_reextracao");
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(dono.queryForObject(
					"SELECT publicado_em IS NOT NULL FROM outbox_events WHERE job_id = ? AND tipo = 'correcao-submetida'",
					Boolean.class, JOB))
				.isTrue());
		assertThat(rabbit.receive(RabbitTopologyConfig.CORRECAO_SUBMETIDA, 1000)).as("nenhuma segunda cópia na fila")
			.isNull();
	}

	private static HttpResponse<String> enviarVoz() throws Exception {
		String limite = "----t238";
		var corpo = new ByteArrayOutputStream();
		corpo.write(("--" + limite + "\r\nContent-Disposition: form-data; name=\"parametros\"\r\n"
				+ "Content-Type: application/json\r\n\r\n{\"finalidade\":\"correcao\",\"tipo\":\"voz\",\"job_id\":\""
				+ JOB + "\"}\r\n")
			.getBytes(StandardCharsets.UTF_8));
		corpo.write(("--" + limite + "\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"correcao.wav\"\r\n"
				+ "Content-Type: audio/wav\r\n\r\n")
			.getBytes(StandardCharsets.UTF_8));
		corpo.write(wav());
		corpo.write(("\r\n--" + limite + "--\r\n").getBytes(StandardCharsets.UTF_8));
		return HTTP.send(HttpRequest.newBuilder(URI.create(base + "/submissoes"))
			.header("Content-Type", "multipart/form-data; boundary=" + limite)
			.POST(HttpRequest.BodyPublishers.ofByteArray(corpo.toByteArray()))
			.build(), HttpResponse.BodyHandlers.ofString());
	}

	private static byte[] wav() {
		int dados = 8000 * 2;
		var buffer = ByteBuffer.allocate(44 + dados).order(ByteOrder.LITTLE_ENDIAN);
		buffer.put("RIFF".getBytes(StandardCharsets.US_ASCII)).putInt(36 + dados);
		buffer.put("WAVEfmt ".getBytes(StandardCharsets.US_ASCII)).putInt(16);
		buffer.putShort((short) 1).putShort((short) 1).putInt(8000).putInt(8000 * 2);
		buffer.putShort((short) 2).putShort((short) 16);
		buffer.put("data".getBytes(StandardCharsets.US_ASCII)).putInt(dados);
		return buffer.array();
	}

}
