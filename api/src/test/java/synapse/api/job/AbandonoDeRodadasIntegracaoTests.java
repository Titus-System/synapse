package synapse.api.job;

import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import synapse.api.ApiApplication;
import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * Sobe a aplicação inteira contra Postgres e RabbitMQ reais e encerra jobs que têm uma
 * rodada aberta: só a aberta vira {@code abandonada}, na transação da ação, e uma
 * {@code correcao-proposta} que chega depois é descartada pelo consumidor.
 */
@EnabledIf("dockerIsAvailable")
class AbandonoDeRodadasIntegracaoTests {

	private static final String MENSAGEM = "rodadas abertas abandonadas pelo encerramento do job";

	private static final String CONFLITOS = """
			[{"elementos":["nucleo.percentual"],"motivo":"segredo conflito T225"}]
			""";

	private static final String PARAMETROS = """
			{"orcamento":485000,"competencias":["2025-11"]}
			""";

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbit;

	private static ConfigurableApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static UUID usuario;

	private static int porta;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void preparar() {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		rabbit = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		rabbit.start();
		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
					"--app.postgres.password=senha-de-teste", "--app.rabbitmq.host=" + rabbit.getHost(),
					"--app.rabbitmq.port=" + rabbit.getAmqpPort(), "--app.rabbitmq.user=" + rabbit.getAdminUsername(),
					"--app.rabbitmq.password=" + rabbit.getAdminPassword(), "--app.outbox.enabled=false",
					"--app.sse.heartbeat=200ms", "--management.health.rabbit.enabled=false",
					"--management.health.db.enabled=false");
		porta = Integer.parseInt(Objects.requireNonNull(contexto.getEnvironment().getProperty("local.server.port")));
		jdbc = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		jdbc.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		usuario = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO usuarios (login, senha_hash, nome, papel, criado_em)
				VALUES ('t225-abandono', 'x', 'RH', 'profissional_rh', now()) RETURNING id
				""", UUID.class));
	}

	@AfterAll
	static void encerrar() {
		if (contexto != null) {
			contexto.close();
		}
		if (rabbit != null) {
			rabbit.stop();
		}
		if (postgres != null) {
			postgres.stop();
		}
	}

	/**
	 * {@code arquivado} não é alcançável a partir da espera pela confirmação. O caso de
	 * {@code arquivar} põe o job num estado que o alcança, para exercitar a marcação
	 * nessa ação também.
	 */
	@ParameterizedTest
	@CsvSource({ "cancelar, aguardando_confirmacao_parametros, pendente",
			"cancelar, aguardando_confirmacao_parametros, em_reextracao",
			"cancelar, aguardando_confirmacao_parametros, em_transcricao",
			"arquivar, aguardando_decisao_usuario, pendente" })
	void encerrarOJobAbandonaSoARodadaAbertaEPreservaOConteudo(String acao, String status, String aberta)
			throws Exception {
		Historico h = historico(status, aberta);
		JsonNode antes = rodadas(h.job());
		AppMetrics metricas = contexto.getBean(AppMetrics.class);
		double abandonadas = metricas.rodadasAbandonadas().count();

		try (var externo = new CorrelationContext().abrir("job-anterior", "usuario-anterior");
				var logs = new CapturaDeLog(JobController.class)) {
			JobDetalhadoDto job = contexto.getBean(JobController.class).executar(h.job(), corpo(acao));
			assertThat(job.status()).isEqualTo(AcaoJob.deColuna(acao).destino().paraColuna());
			assertThat(logs.eventos()).hasSize(1);
			assertThat(logs.eventos().getFirst().getFormattedMessage()).isEqualTo(MENSAGEM);
			String linha = CapturaDeLog.emJson(logs.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			JsonNode log = JSON.readTree(linha);
			assertThat(log.path("job_id").asString()).isEqualTo(h.job().toString());
			assertThat(log.path("extra").path("rodadas_abandonadas").asInt()).isEqualTo(1);
			assertThat(log.path("extra").path("acao").asString()).isEqualTo(acao);
			assertThat(linha).doesNotContain("segredo", "percentual", "elementos", "conflitos");
			assertThat(MDC.get("job_id")).isEqualTo("job-anterior");
			assertThat(MDC.get("user_id")).isEqualTo("usuario-anterior");
		}
		assertThat(MDC.get("job_id")).isNull();

		JsonNode depois = rodadas(h.job());
		assertThat(depois.path(0)).isEqualTo(antes.path(0));
		assertThat(depois.path(1)).isEqualTo(antes.path(1));
		ObjectNode marcada = (ObjectNode) depois.path(2).deepCopy();
		ObjectNode original = (ObjectNode) antes.path(2).deepCopy();
		assertThat(marcada.path("estado").asString()).isEqualTo("abandonada");
		assertThat(jdbc.queryForObject(
				"SELECT atualizada_em > now() - interval '1 minute' FROM rodadas_correcao WHERE id = ?", Boolean.class,
				h.aberta()))
			.isTrue();
		marcada.remove(List.of("estado", "atualizada_em"));
		original.remove(List.of("estado", "atualizada_em"));
		assertThat(marcada).isEqualTo(original);

		assertThat(metricas.rodadasAbandonadas().count()).isEqualTo(abandonadas + 1);
		String scrape = get("/metrics", 200);
		assertThat(amostra(scrape)).isEqualTo(abandonadas + 1);
		assertThat(scrape).doesNotContain(h.job().toString());

		JsonNode historico = JSON.readTree(get("/jobs/" + h.job() + "/rodadas", 200));
		assertThat(historico.size()).isEqualTo(3);
		for (JsonNode rodada : historico) {
			ContratoDeEvento.validarRespostaHttp("Rodada", rodada.toString());
		}
		assertThat(historico.path(0).path("estado").asString()).isEqualTo("corrigida");
		assertThat(historico.path(1).path("estado").asString()).isEqualTo("reextracao_falhou");
		JsonNode ultima = historico.path(2);
		assertThat(ultima.path("id").asString()).isEqualTo(h.aberta().toString());
		assertThat(ultima.path("estado").asString()).isEqualTo("abandonada");
		assertThat(ultima.path("rodada_anterior_id").asString()).isEqualTo(h.falhou().toString());
		assertThat(ultima.path("regra_analisada_id").asString()).isEqualTo(h.v2().toString());
		assertThat(ultima.path("regra_resultante_id").isNull()).isTrue();
		assertThat(ultima.path("conflitos")).isEqualTo(JSON.readTree(CONFLITOS));
		if ("em_reextracao".equals(aberta)) {
			assertThat(ultima.path("correcao").path("texto").asString()).isEqualTo("segredo correcao 3 T225");
		}
		else if ("em_transcricao".equals(aberta)) {
			assertThat(ultima.path("correcao").path("tipo").asString()).isEqualTo("voz");
			assertThat(ultima.path("correcao").path("texto").isNull()).isTrue();
		}
		else {
			assertThat(ultima.path("correcao").isNull()).isTrue();
		}

		JsonNode encerradas = rodadas(h.job());
		try (var logs = new CapturaDeLog(JobController.class)) {
			for (String repetida : List.of("cancelar", "arquivar")) {
				post("/jobs/" + h.job() + "/actions", corpo(repetida), 409);
			}
			assertThat(logs.eventos()).isEmpty();
		}
		assertThat(rodadas(h.job())).isEqualTo(encerradas);
		assertThat(metricas.rodadasAbandonadas().count()).isEqualTo(abandonadas + 1);
	}

	@Test
	void propostaQueChegaDepoisDoAbandonoEDescartadaSemCriarVersao() throws Exception {
		Historico h = historico("aguardando_confirmacao_parametros", "em_reextracao");
		post("/jobs/" + h.job() + "/actions", corpo("cancelar"), 200);
		assertThat(estado(h.aberta())).isEqualTo("abandonada");
		JsonNode antes = fotografia(h.job());
		AppMetrics metricas = contexto.getBean(AppMetrics.class);
		double aplicadas = metricas.correcaoProposta("aplicada").count();

		ObjectNode evento = JSON.createObjectNode();
		evento.put("job_id", h.job().toString());
		evento.put("regra_origem_id", h.v2().toString());
		evento.put("submissao_id", Objects.requireNonNull(h.submissao()).toString());
		evento.set("representacao",
				JSON.valueToTree(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao()));
		((ObjectNode) evento.path("representacao").path("nucleo")).put("percentual", new BigDecimal("0.031"));
		evento.set("parametros", JSON.readTree(PARAMETROS));
		ContratoDeEvento.validar("correcao-proposta", evento.toString());
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			contexto.getBean(RabbitTemplate.class)
				.send("correcao-proposta",
						MessageBuilder.withBody(evento.toString().getBytes(StandardCharsets.UTF_8))
							.setContentType("application/json")
							.build());
			await().atMost(Duration.ofSeconds(10))
				.untilAsserted(() -> assertThat(logs.eventos()
					.stream()
					.map(CapturaDeLog::emJson)
					.map(JSON::readTree)
					.map(linha -> linha.path("extra").path("resultado").asString())
					.toList()).contains("descartada"));
			for (var registro : logs.eventos()) {
				assertThat(CapturaDeLog.emJson(registro)).doesNotContain("segredo", "percentual");
			}
		}

		assertThat(fotografia(h.job())).isEqualTo(antes);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Integer.class, h.job()))
			.isEqualTo(2);
		assertThat(metricas.correcaoProposta("aplicada").count()).isEqualTo(aplicadas);
	}

	@Test
	void sairDaTelaNaoAbandonaARodadaPendente() throws Exception {
		Historico h = historico("aguardando_confirmacao_parametros", "pendente");
		JsonNode antes = fotografia(h.job());
		double abandonadas = contexto.getBean(AppMetrics.class).rodadasAbandonadas().count();

		get("/jobs/" + h.job() + "/rodadas", 200);
		HttpResponse<InputStream> resposta = HTTP.send(
				HttpRequest.newBuilder(uri("/jobs/" + h.job() + "/events")).GET().build(),
				HttpResponse.BodyHandlers.ofInputStream());
		StreamCliente stream = new StreamCliente(resposta);
		try {
			stream.aguardarBloco("event:estado", Duration.ofSeconds(5));
		}
		finally {
			stream.fechar();
		}
		EmissoresSse emissores = contexto.getBean(EmissoresSse.class);
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(emissores.conexoesAtivas()).isZero());

		assertThat(fotografia(h.job())).isEqualTo(antes);
		assertThat(estado(h.aberta())).isEqualTo("pendente");
		assertThat(contexto.getBean(AppMetrics.class).rodadasAbandonadas().count()).isEqualTo(abandonadas);
	}

	@ParameterizedTest
	@ValueSource(strings = { "job_transicoes", "rodadas_correcao" })
	void falhaNaTransicaoOuNaMarcacaoDesfazAsDuas(String tabela) throws Exception {
		Historico h = historico("aguardando_confirmacao_parametros", "pendente");
		JsonNode antes = fotografia(h.job());
		double abandonadas = contexto.getBean(AppMetrics.class).rodadasAbandonadas().count();
		String operacao = "job_transicoes".equals(tabela) ? "INSERT" : "UPDATE";
		jdbc.execute(
				"CREATE FUNCTION t225_falhar() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''segredo banco T225''; END'");
		jdbc.execute("CREATE TRIGGER t225_falha BEFORE " + operacao + " ON " + tabela
				+ " FOR EACH ROW EXECUTE FUNCTION t225_falhar()");
		try (var logs = new CapturaDeLog(JobController.class)) {
			assertThat(post("/jobs/" + h.job() + "/actions", corpo("cancelar"), 500)).doesNotContain("segredo");
			assertThat(logs.eventos()).isEmpty();
		}
		finally {
			jdbc.execute("DROP TRIGGER t225_falha ON " + tabela);
			jdbc.execute("DROP FUNCTION t225_falhar()");
		}

		assertThat(fotografia(h.job())).isEqualTo(antes);
		assertThat(estado(h.aberta())).isEqualTo("pendente");
		assertThat(contexto.getBean(AppMetrics.class).rodadasAbandonadas().count()).isEqualTo(abandonadas);
	}

	/**
	 * Um job com a primeira rodada corrigida pela versão 2, a segunda com a reextração
	 * falha e a terceira aberta sobre a versão 2.
	 */
	private static Historico historico(String status, String estadoAberto) {
		UUID job = contexto.getBean(JobService.class)
			.criar(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO), usuario)
			.id();
		UUID v1 = Objects
			.requireNonNull(jdbc.queryForObject("SELECT id FROM regras WHERE job_id = ?", UUID.class, job));
		jdbc.update("UPDATE jobs SET status = ? WHERE id = ?", status, job);
		jdbc.update("UPDATE regras SET parametros = ?::jsonb WHERE id = ?", PARAMETROS, v1);
		UUID v2 = Objects.requireNonNull(jdbc.queryForObject(
				"""
						INSERT INTO regras (job_id, versao, origem, regra_origem_id, nucleo, especificacoes, representacao,
						                    parametros, hash, criada_em)
						SELECT job_id, 2, 'correcao', id, nucleo, especificacoes, representacao, parametros, repeat('2', 64), now()
						FROM regras WHERE id = ? RETURNING id
						""",
				UUID.class, v1));
		UUID corrigida = rodada(job, v1, "corrigida", submissao("segredo correcao 1 T225"), v2, null, 3);
		UUID falhou = rodada(job, v2, "reextracao_falhou", submissao("segredo correcao 2 T225"), null, corrigida, 2);
		UUID submissao = switch (estadoAberto) {
			case "em_reextracao" -> submissao("segredo correcao 3 T225");
			case "em_transcricao" -> Objects.requireNonNull(jdbc.queryForObject("""
					INSERT INTO submissoes (usuario_id, tipo, binario, formato, criado_em)
					VALUES (?, 'voz', '\\x52494646'::bytea, 'wav', now()) RETURNING id
					""", UUID.class, usuario));
			default -> null;
		};
		UUID aberta = rodada(job, v2, estadoAberto, submissao, null, falhou, 1);
		return new Historico(job, v2, falhou, aberta, submissao);
	}

	private static UUID submissao(String texto) {
		return Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em)
				VALUES (?, 'texto', ?, now()) RETURNING id
				""", UUID.class, usuario, texto));
	}

	private static UUID rodada(UUID job, UUID analisada, String estado, @Nullable UUID submissao,
			@Nullable UUID resultante, @Nullable UUID anterior, int horasAtras) {
		return Objects.requireNonNull(jdbc.queryForObject(
				"""
						INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado, submissao_correcao_id,
						                              regra_resultante_id, rodada_anterior_id, criada_em, atualizada_em)
						VALUES (?, ?, ?::jsonb, ?, ?, ?, ?, now() - make_interval(hours => ?), now() - make_interval(hours => ?))
						RETURNING id
						""",
				UUID.class, job, analisada, CONFLITOS, estado, submissao, resultante, anterior, horasAtras,
				horasAtras));
	}

	private static String estado(UUID rodada) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, rodada));
	}

	private static JsonNode rodadas(UUID job) {
		return JSON.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"SELECT jsonb_agg(to_jsonb(r) ORDER BY criada_em, id)::text FROM rodadas_correcao r WHERE job_id = ?",
				String.class, job)));
	}

	private static JsonNode fotografia(UUID job) {
		return JSON.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"""
						SELECT jsonb_build_object('job', to_jsonb(j),
						'regras', (SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM regras r WHERE job_id = j.id),
						'rodadas', (SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM rodadas_correcao r WHERE job_id = j.id),
						'transicoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM job_transicoes t WHERE job_id = j.id),
						'acoes', (SELECT jsonb_agg(to_jsonb(a) ORDER BY id) FROM job_acoes a WHERE job_id = j.id),
						'trilhas', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM trilhas_auditoria t WHERE job_id = j.id),
						'outbox', (SELECT jsonb_agg(to_jsonb(o) ORDER BY id) FROM outbox_events o WHERE job_id = j.id))::text FROM jobs j WHERE id = ?
						""",
				String.class, job)));
	}

	private static double amostra(String scrape) {
		String linha = scrape.lines()
			.filter(valor -> valor.startsWith("correcao_rodadas_abandonadas_total "))
			.findFirst()
			.orElseThrow();
		return Double.parseDouble(linha.substring(linha.lastIndexOf(' ') + 1));
	}

	private static String corpo(String acao) {
		return "{\"acao\":\"" + acao + "\"}";
	}

	private static URI uri(String caminho) {
		return URI.create("http://localhost:" + porta + caminho);
	}

	private static String get(String caminho, int esperado) throws IOException, InterruptedException {
		return enviar(HttpRequest.newBuilder(uri(caminho)).GET().build(), esperado);
	}

	private static String post(String caminho, String corpo, int esperado) throws IOException, InterruptedException {
		return enviar(HttpRequest.newBuilder(uri(caminho))
			.header("Content-Type", "application/json")
			.POST(HttpRequest.BodyPublishers.ofString(corpo))
			.build(), esperado);
	}

	private static String enviar(HttpRequest requisicao, int esperado) throws IOException, InterruptedException {
		HttpResponse<String> resposta = HTTP.send(requisicao,
				HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(esperado);
		return resposta.body();
	}

	record Historico(UUID job, UUID v2, UUID falhou, UUID aberta, @Nullable UUID submissao) {
	}

}
