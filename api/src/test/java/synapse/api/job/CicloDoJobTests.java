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

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
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
import org.springframework.http.HttpStatus;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * O ciclo completo do job da Sprint 1, com a api fazendo o papel de si mesma e o teste
 * fazendo o papel de codegen e worker - os dois lados que a T-046 (trilha de auditoria) e
 * o gatilho de {@code gerando_regra → simulando} ({@link EtapaAlteradaService}) deixavam
 * sem exercício ponta a ponta: {@code POST /jobs} → confirmação → {@code etapa-alterada}
 * → {@code no-concluido} → {@code simulacao-concluida} → {@code GET /jobs/{id}} com o
 * relatório preenchido → {@code POST /jobs/{id}/actions}.
 */
@EnabledIf("dockerIsAvailable")
class CicloDoJobTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "77777777-7777-4777-8777-777777777777";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = new JsonMapper();

	private static final String FORMULARIO = """
			{"origem":"formulario","competencias":["2025-08"],"orcamento":485000,
			 "conteudo":{"nucleo":{"vigencia":{"inicio":"2025-08","fim":"2025-08"},
			 "loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.03},"texto_livre":null}}
			""";

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	private static int porta;

	private static EmissoresSse emissoresSse;

	private static RabbitTemplate rabbitTemplate;

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
	void fecharStreamsAbertos() {
		for (StreamCliente cliente : this.abertos) {
			cliente.fechar();
		}
		this.abertos.clear();
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(emissoresSse.conexoesAtivas()).isZero());
	}

	@Test
	void daSubmissaoAoRelatorioELiberacao() throws Exception {
		// 1. POST /jobs: o job nasce em aguardando_confirmacao_parametros.
		JsonNode jobCriado = post("/jobs", FORMULARIO, 201);
		UUID jobId = UUID.fromString(jobCriado.path("id").asString());
		assertThat(jobCriado.path("status").asString()).isEqualTo("aguardando_confirmacao_parametros");

		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		// 2. POST /jobs/{id}/parameters: confirma o núcleo tal como enviado, vai a
		// gerando_regra.
		String parametros = """
				{"regra":{"nucleo":{"vigencia":{"inicio":"2025-08","fim":"2025-08"},
				 "loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.03},"especificacoes":[]}}
				""";
		JsonNode confirmado = post("/jobs/" + jobId + "/parameters", parametros, 202);
		UUID regraId = UUID.fromString(confirmado.path("regra").path("id").asString());
		assertThat(confirmado.path("status").asString()).isEqualTo("gerando_regra");

		// 3. codegen: publica etapa-alterada(delegacao_worker, iniciada) - leva a
		// simulando.
		publicarEtapaAlterada(jobId, "delegacao_worker", "iniciada");
		cliente.aguardarBloco("\"status\":\"simulando\"", Duration.ofSeconds(10));

		// 4. codegen: grava o código (como o worker leria) e publica no-concluido do nó
		// geracao_codigo - cria a linha em simulacoes.
		UUID codigoGeradoId = criarCodigoGerado(jobId, regraId);
		publicarNoConcluido(UUID.randomUUID(), jobId, "geracao_codigo", regraId, codigoGeradoId);
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(simulacaoPorCodigoGerado(codigoGeradoId)).isNotNull());

		// 5. worker: grava o resultado e publica simulacao-concluida - leva a
		// aguardando_decisao_usuario.
		UUID resultadoId = criarResultado(jobId, codigoGeradoId);
		publicarSimulacaoConcluida(jobId, resultadoId, "sucesso", "viavel");

		String blocoResultado = cliente.aguardarBloco("event:resultado", Duration.ofSeconds(10));
		assertThat(blocoResultado).contains("\"status\":\"sucesso\"").contains("\"veredito\":\"viavel\"");
		cliente.aguardarBloco("\"status\":\"aguardando_decisao_usuario\"", Duration.ofSeconds(10));

		// 6. GET /jobs/{id}: o relatório vem preenchido - é o que a T-046 fecha.
		JsonNode job = get("/jobs/" + jobId);
		assertThat(job.path("status").asString()).isEqualTo("aguardando_decisao_usuario");
		assertThat(job.path("simulacao").path("status").asString()).isEqualTo("sucesso");
		assertThat(job.path("simulacao").path("veredito").asString()).isEqualTo("viavel");
		assertThat(job.path("simulacao").path("resultado").path("totais").path("baseline").decimalValue())
			.isEqualByComparingTo("480312.00");

		// 7. POST /jobs/{id}/actions: confirmar_liberar - o destino é terminal e fecha o
		// stream.
		JsonNode acao = post("/jobs/" + jobId + "/actions", """
				{"acao":"confirmar_liberar"}
				""", 200);
		assertThat(acao.path("status").asString()).isEqualTo("liberado");
		cliente.aguardarFimDoStream(Duration.ofSeconds(10));
	}

	// --- Apoio ----------------------------------------------------------------------

	private static JsonNode post(String caminho, String corpo, int statusEsperado)
			throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest.newBuilder(uri(caminho))
			.header("Content-Type", "application/json")
			.POST(HttpRequest.BodyPublishers.ofString(corpo))
			.build();
		HttpResponse<String> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).as("corpo da resposta: %s", resposta.body()).isEqualTo(statusEsperado);
		return JSON.readTree(resposta.body());
	}

	private static JsonNode get(String caminho) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest.newBuilder(uri(caminho)).GET().build();
		HttpResponse<String> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(HttpStatus.OK.value());
		return JSON.readTree(resposta.body());
	}

	private static URI uri(String caminho) {
		return URI.create("http://localhost:" + porta + caminho);
	}

	private StreamCliente conectar(UUID jobId) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest.newBuilder(uri("/jobs/" + jobId + "/events")).GET().build();
		HttpResponse<InputStream> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofInputStream());
		StreamCliente cliente = new StreamCliente(resposta);
		this.abertos.add(cliente);
		return cliente;
	}

	private static void publicarEtapaAlterada(UUID jobId, String etapa, String status) {
		String corpo = """
				{"job_id":"%s","etapa":"%s","status":"%s"}
				""".formatted(jobId, etapa, status).strip();
		enviar(corpo, RabbitTopologyConfig.ETAPA_ALTERADA, "");
	}

	private static void publicarNoConcluido(UUID eventoId, UUID jobId, String no, UUID regraId, UUID codigoGeradoId) {
		String corpo = """
				{"evento_id":"%s","job_id":"%s","no":"%s","concluido_em":"2025-08-15T10:00:00Z",
				 "conclusao":{"resumo":"código gerado","elementos_implementados":["nucleo.percentual"]},
				 "regra_id":"%s","codigo_gerado_id":"%s"}
				""".formatted(eventoId, jobId, no, regraId, codigoGeradoId).strip();
		enviar(corpo, RabbitTopologyConfig.NO_CONCLUIDO, "");
	}

	private static void publicarSimulacaoConcluida(UUID jobId, UUID resultadoId, String status, String veredito) {
		String corpo = """
				{"job_id":"%s","resultado_id":"%s","status":"%s","veredito":"%s"}
				""".formatted(jobId, resultadoId, status, veredito).strip();
		enviar(corpo, "", RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE);
	}

	private static void enviar(String corpo, String fila, String exchange) {
		Message mensagem = MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.build();
		if (!exchange.isEmpty()) {
			rabbitTemplate.send(exchange, "", mensagem);
		}
		else {
			rabbitTemplate.send("", fila, mensagem);
		}
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
							INSERT INTO resultados_simulacao (id, job_id, codigo_gerado_id, status, veredito, totais, assercoes, decomposicao, criado_em)
							VALUES ('%s', '%s', '%s', 'sucesso', 'viavel',
								'{"baseline":480312.00,"simulado":492100.00,"diferenca_abs":11788.00,"diferenca_pct":0.0245,"orcamento":485000.00}'::jsonb,
								'[]'::jsonb,
								'{"elemento":{},"loja":{},"marca":{},"cargo":{},"competencia":{"2025-08":11788.00}}'::jsonb,
								now())
							"""
						.formatted(resultadoId, jobId, codigoGeradoId));
		}
		return resultadoId;
	}

	private static @org.jspecify.annotations.Nullable UUID simulacaoPorCodigoGerado(UUID codigoGeradoId)
			throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement.executeQuery(
						"SELECT id FROM simulacoes WHERE codigo_gerado_id = '%s'".formatted(codigoGeradoId))) {
			return rs.next() ? rs.getObject("id", UUID.class) : null;
		}
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

}
