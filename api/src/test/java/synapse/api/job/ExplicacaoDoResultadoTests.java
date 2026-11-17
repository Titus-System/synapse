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
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.time.Instant;
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

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;
import static org.awaitility.Awaitility.await;

/**
 * A etapa de explicação ponta a ponta contra um Postgres e um RabbitMQ reais (T-318): o
 * {@code no-concluido} publicado como o codegen o publicaria liga ou não a flag de baixa
 * rastreabilidade, a narrativa conferida aparece em {@code GET /jobs/{id}} e a tela é
 * avisada pelo stream, sem o texto.
 */
@EnabledIf("dockerIsAvailable")
class ExplicacaoDoResultadoTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "77777777-7777-4777-8777-777777777777";

	private static final String TEXTO = "A simulação aplicou a regra e ficou acima do orçamento informado.";

	private static final String NUCLEO = """
			{"vigencia":{"inicio":"2025-08","fim":"2025-08"},"loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.02}
			"""
		.strip();

	private static final String TOTAIS = """
			{"baseline":480312.00,"simulado":492100.00,"diferenca_abs":11788.00,"diferenca_pct":0.0245,"orcamento":485000.00}
			"""
		.strip();

	/** A decomposição que o worker sempre grava num resultado de sucesso. */
	private static final String DECOMPOSICAO = """
			{"elemento":{"nucleo.percentual":11788.00},"loja":{"13":11788.00},"marca":{"10":11788.00},
			 "cargo":{"100":11788.00},"competencia":{"2025-08":11788.00}}
			""".strip();

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
		rabbitmq = new RabbitMQContainer("rabbitmq:3.13-management-alpine").withStartupTimeout(Duration.ofMinutes(2));
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
	void fecharStreamsEConferirQueAFilaEsvaziou() {
		for (StreamCliente cliente : this.abertos) {
			cliente.fechar();
		}
		this.abertos.clear();
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(emissoresSse.conexoesAtivas()).isZero());
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getMessageCount()).isZero());
	}

	// --- Cenários -----------------------------------------------------------------

	@Test
	void explicacaoConferidaDeixaAFlagFalsaApareceNaConsultaEAvisaATelaSemOTexto() throws Exception {
		Simulada simulada = simulacaoComResultado();
		UUID explicacaoId = criarExplicacao(simulada.resultadoId(), TEXTO, true);
		StreamCliente cliente = conectar(simulada.jobId());
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		double conferidas = desfechos("conferida");

		publicar(UUID.randomUUID(), simulada, "conferida", explicacaoId);

		String bloco = cliente.aguardarBloco("event:explicacao", Duration.ofSeconds(10));
		JsonNode evento = ClienteDoJob.dadosDoBloco(bloco);
		ContratoDeEvento.validarEventoDoStream("explicacao", evento.toString());
		assertThat(evento.path("simulacao_id").asString()).isEqualTo(simulada.simulacaoId().toString());
		assertThat(evento.path("disponivel").asBoolean()).isTrue();
		assertThat(bloco).doesNotContain(TEXTO);
		JsonNode simulacao = ClienteDoJob.consultar(porta, simulada.jobId()).path("simulacao");
		assertThat(simulacao.path("flag_baixa_rastreabilidade").asBoolean()).isFalse();
		assertThat(simulacao.path("explicacao").path("texto").asString()).isEqualTo(TEXTO);
		assertThat(simulacao.path("explicacao").path("criada_em").asString()).isNotBlank();
		assertThat(desfechos("conferida")).isEqualTo(conferidas + 1);
		assertThat(flagDaSimulacao(simulada.simulacaoId())).isFalse();
	}

	@Test
	void explicacaoReprovadaLigaAFlagNaoApareceNaConsultaEAvisaIndisponivel() throws Exception {
		Simulada simulada = simulacaoComResultado();
		UUID explicacaoId = criarExplicacao(simulada.resultadoId(), TEXTO, false);
		StreamCliente cliente = conectar(simulada.jobId());
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		double reprovadas = desfechos("reprovada");

		publicar(UUID.randomUUID(), simulada, "reprovada", explicacaoId);

		JsonNode evento = ClienteDoJob.dadosDoBloco(cliente.aguardarBloco("event:explicacao", Duration.ofSeconds(10)));
		ContratoDeEvento.validarEventoDoStream("explicacao", evento.toString());
		assertThat(evento.path("disponivel").asBoolean()).isFalse();
		JsonNode corpo = ClienteDoJob.consultar(porta, simulada.jobId());
		assertThat(corpo.path("simulacao").path("flag_baixa_rastreabilidade").asBoolean()).isTrue();
		assertThat(corpo.path("simulacao").has("explicacao")).isFalse();
		assertThat(corpo.toString()).doesNotContain(TEXTO);
		assertThat(desfechos("reprovada")).isEqualTo(reprovadas + 1);
		assertThat(flagDaSimulacao(simulada.simulacaoId())).isTrue();
	}

	@Test
	void eventoSemExplicacaoIdLigaAFlagEAvisaIndisponivel() throws Exception {
		Simulada simulada = simulacaoComResultado();
		StreamCliente cliente = conectar(simulada.jobId());
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		double ausentes = desfechos("ausente");

		publicar(UUID.randomUUID(), simulada, "provedor_indisponivel", null);

		JsonNode evento = ClienteDoJob.dadosDoBloco(cliente.aguardarBloco("event:explicacao", Duration.ofSeconds(10)));
		assertThat(evento.path("disponivel").asBoolean()).isFalse();
		JsonNode simulacao = ClienteDoJob.consultar(porta, simulada.jobId()).path("simulacao");
		assertThat(simulacao.path("flag_baixa_rastreabilidade").asBoolean()).isTrue();
		assertThat(simulacao.has("explicacao")).isFalse();
		assertThat(desfechos("ausente")).isEqualTo(ausentes + 1);
	}

	@Test
	void aReentregaDoMesmoEventoNaoEmiteSegundoAvisoNemContaSegundoDesfecho() throws Exception {
		Simulada simulada = simulacaoComResultado();
		UUID explicacaoId = criarExplicacao(simulada.resultadoId(), TEXTO, false);
		UUID eventoId = UUID.randomUUID();
		StreamCliente cliente = conectar(simulada.jobId());
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		double reprovadas = desfechos("reprovada");
		double duplicados = consumos("duplicado");

		publicar(eventoId, simulada, "reprovada", explicacaoId);
		cliente.aguardarBloco("event:explicacao", Duration.ofSeconds(10));
		publicar(eventoId, simulada, "reprovada", explicacaoId);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(consumos("duplicado")).isEqualTo(duplicados + 1));
		assertThat(cliente.contarOcorrencias("event:explicacao")).isEqualTo(1);
		assertThat(desfechos("reprovada")).isEqualTo(reprovadas + 1);
		assertThat(linhasDaTrilha(simulada.jobId())).isEqualTo(1);
	}

	@Test
	void depoisDoAceiteDaMetaAConsultaNaoTrazAExplicacaoDoResultadoAnterior() throws Exception {
		Simulada simulada = simulacaoComResultado();
		UUID explicacaoId = criarExplicacao(simulada.resultadoId(), TEXTO, true);
		publicar(UUID.randomUUID(), simulada, "conferida", explicacaoId);
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(linhasDaTrilha(simulada.jobId())).isEqualTo(1));
		assertThat(ClienteDoJob.consultar(porta, simulada.jobId())
			.path("simulacao")
			.path("explicacao")
			.path("texto")
			.asString()).isEqualTo(TEXTO);

		// O aceite da meta aponta a simulação para a candidata da busca, que não tem
		// narrativa.
		UUID candidata = criarResultado(simulada.jobId(), simulada.codigoId(), "busca_meta");
		apontarSimulacaoPara(simulada.simulacaoId(), candidata);

		JsonNode simulacao = ClienteDoJob.consultar(porta, simulada.jobId()).path("simulacao");
		assertThat(simulacao.path("resultado").isMissingNode()).isFalse();
		assertThat(simulacao.has("explicacao")).isFalse();
	}

	/**
	 * Pela fila, a mensagem volta para a fila como as falhas de banco (skill
	 * consumidores); o serviço é chamado direto para não deixar a mensagem em loop.
	 */
	@Test
	void simulacaoInexistenteDesfazATrilhaEPropagaAFalha() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID codigoId = criarCodigoGerado(jobId, regraId);
		UUID resultadoId = criarResultado(jobId, codigoId, "simulacao");
		UUID eventoId = UUID.randomUUID();
		JobEventosService servico = contexto.getBean(JobEventosService.class);
		NoConcluidoDto evento = new NoConcluidoDto(eventoId, jobId, "explicacao", Instant.parse("2025-11-28T14:32:10Z"),
				new JsonMapper().readTree("{\"resumo\":\"x\",\"desfecho_explicacao\":\"provedor_indisponivel\"}"),
				regraId, null, null, null, null, resultadoId);

		assertThatExceptionOfType(SimulacaoDaExplicacaoInexistenteException.class)
			.isThrownBy(() -> servico.registrarExplicacao(jobId, eventoId, evento));
		assertThat(linhasDaTrilha(jobId)).isZero();
	}

	@Test
	void aSaidaDeMetricsTrazOContadorDoDesfechoDepoisDoFluxo() throws Exception {
		Simulada simulada = simulacaoComResultado();
		publicar(UUID.randomUUID(), simulada, "provedor_indisponivel", null);
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(linhasDaTrilha(simulada.jobId())).isEqualTo(1));

		HttpResponse<String> resposta = HTTP.send(
				HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/metrics")).GET().build(),
				HttpResponse.BodyHandlers.ofString());

		assertThat(resposta.statusCode()).isEqualTo(200);
		List<String> amostras = resposta.body()
			.lines()
			.filter((linha) -> linha.startsWith("explicacao_registrada_total{")
					&& linha.contains("desfecho=\"ausente\""))
			.toList();
		assertThat(amostras).hasSize(1);
		assertThat(Double.parseDouble(amostras.getFirst().substring(amostras.getFirst().lastIndexOf(' ') + 1)))
			.isEqualTo(desfechos("ausente"))
			.isPositive();
		assertThat(resposta.body()).doesNotContain(TEXTO);
	}

	// --- Fixtures -----------------------------------------------------------------

	private record Simulada(UUID jobId, UUID regraId, UUID codigoId, UUID resultadoId, UUID simulacaoId) {
	}

	/**
	 * O que a api já tem quando a explicação chega: a simulação criada com o código
	 * gerado e amarrada ao resultado que o worker gravou.
	 */
	private static Simulada simulacaoComResultado() throws SQLException {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID codigoId = criarCodigoGerado(jobId, regraId);
		UUID resultadoId = criarResultado(jobId, codigoId, "simulacao");
		UUID simulacaoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO simulacoes (id, criado_em, regra_id, job_id, codigo_gerado_id, resultado_id)
					VALUES ('%s', now(), '%s', '%s', '%s', '%s')
					""".formatted(simulacaoId, regraId, jobId, codigoId, resultadoId));
		}
		return new Simulada(jobId, regraId, codigoId, resultadoId, simulacaoId);
	}

	private static void publicar(UUID eventoId, Simulada simulada, String desfecho, @Nullable UUID explicacaoId)
			throws IOException {
		String referenciaDaExplicacao = (explicacaoId != null) ? ",\"explicacao_id\":\"%s\"".formatted(explicacaoId)
				: "";
		String corpo = """
				{"evento_id":"%s","job_id":"%s","no":"explicacao","concluido_em":"2025-11-24T15:30:01Z",
				 "conclusao":{"resumo":"x","desfecho_explicacao":"%s"},"regra_id":"%s","resultado_id":"%s"%s}
				"""
			.formatted(eventoId, simulada.jobId(), desfecho, simulada.regraId(), simulada.resultadoId(),
					referenciaDaExplicacao)
			.strip();
		ContratoDeEvento.validar("no-concluido", corpo);
		Message mensagem = MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setType(RabbitTopologyConfig.NO_CONCLUIDO)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.NO_CONCLUIDO, mensagem);
	}

	private StreamCliente conectar(UUID jobId) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest
			.newBuilder(URI.create("http://localhost:" + porta + "/jobs/" + jobId + "/events"))
			.GET()
			.build();
		HttpResponse<InputStream> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofInputStream());
		StreamCliente cliente = new StreamCliente(resposta);
		this.abertos.add(cliente);
		return cliente;
	}

	private static UUID criarJob() throws SQLException {
		UUID jobId = UUID.randomUUID();
		UUID submissaoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO submissoes (id, usuario_id, tipo, conteudo, criado_em)
					VALUES ('%s', '%s', 'formulario', '{}'::jsonb, now())
					""".formatted(submissaoId, USUARIO_ID));
			statement.execute("""
					INSERT INTO jobs (id, status, usuario_id, submissao_id, competencias, orcamento, criado_em)
					VALUES ('%s', 'simulacao_inviavel', '%s', '%s', '{2025-08}', 485000, now())
					""".formatted(jobId, USUARIO_ID, submissaoId));
		}
		return jobId;
	}

	private static UUID criarRegra(UUID jobId) throws SQLException {
		UUID regraId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
					VALUES ('%s', '%s', 1, 'confirmacao_usuario', '%s'::jsonb, '[]'::jsonb, '%s', now())
					""".formatted(regraId, jobId, NUCLEO, "0".repeat(64)));
		}
		return regraId;
	}

	// prompts, codigos_gerados, resultados_simulacao e explicacoes só o codegen e o
	// worker
	// escrevem em produção (AGENTS.md); a fixture usa o usuário dono para simular o que
	// eles
	// já teriam gravado.
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

	private static UUID criarResultado(UUID jobId, UUID codigoGeradoId, String proposito) throws SQLException {
		UUID resultadoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute(
					"""
							INSERT INTO resultados_simulacao (id, job_id, codigo_gerado_id, status, veredito, totais, assercoes, decomposicao, proposito, criado_em)
							VALUES ('%s', '%s', '%s', 'sucesso', 'inviavel', '%s'::jsonb, '[]'::jsonb, '%s'::jsonb, '%s', now())
							"""
						.formatted(resultadoId, jobId, codigoGeradoId, TOTAIS, DECOMPOSICAO, proposito));
		}
		return resultadoId;
	}

	private static UUID criarExplicacao(UUID resultadoId, String texto, boolean conferida) throws SQLException {
		UUID explicacaoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO explicacoes (id, resultado_id, texto, aderencia_conferida, criado_em)
					VALUES ('%s', '%s', '%s', %s, now())
					""".formatted(explicacaoId, resultadoId, texto, conferida));
		}
		return explicacaoId;
	}

	private static void apontarSimulacaoPara(UUID simulacaoId, UUID resultadoId) throws SQLException {
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute(
					"UPDATE simulacoes SET resultado_id = '%s' WHERE id = '%s'".formatted(resultadoId, simulacaoId));
		}
	}

	private static boolean flagDaSimulacao(UUID simulacaoId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery(
						"SELECT flag_baixa_rastreabilidade FROM simulacoes WHERE id = '%s'".formatted(simulacaoId))) {
			assertThat(rs.next()).isTrue();
			return rs.getBoolean(1);
		}
	}

	private static int linhasDaTrilha(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT count(*) FROM trilhas_auditoria WHERE job_id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getInt(1);
		}
	}

	private static double desfechos(String desfecho) {
		var contador = contexto.getBean(io.micrometer.core.instrument.MeterRegistry.class)
			.find("explicacao.registrada")
			.tag("desfecho", desfecho)
			.counter();
		return (contador != null) ? contador.count() : 0;
	}

	private static double consumos(String resultado) {
		var contador = contexto.getBean(io.micrometer.core.instrument.MeterRegistry.class)
			.find("no.concluido.consumo")
			.tag("resultado", resultado)
			.counter();
		return (contador != null) ? contador.count() : 0;
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static QueueInformation infoDaFila(String nome) {
		return Objects.requireNonNull(amqpAdmin.getQueueInfo(nome), "fila " + nome + " não encontrada");
	}

}
