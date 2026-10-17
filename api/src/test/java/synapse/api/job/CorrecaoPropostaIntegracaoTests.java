package synapse.api.job;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.sql.DriverManager;
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
import org.junit.jupiter.params.provider.ValueSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import org.springframework.amqp.core.AmqpAdmin;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.rabbit.listener.RabbitListenerEndpointRegistry;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.client.RestClient;

import synapse.api.ApiApplication;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.logging.CorrelationContext;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.awaitility.Awaitility.await;

@EnabledIf("dockerIsAvailable")
class CorrecaoPropostaIntegracaoTests {

	private static final String FILA = "correcao-proposta";

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static final String PARAMETROS = """
			{"orcamento":485000.1234567890123456789,"meta_venda":12000000.9876543210987654321,"competencias":["2025-11"]}
			""";

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbit;

	private static ConfigurableApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static UUID usuario;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void preparar() {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		rabbit = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		rabbit.start();
		contexto = abrirAplicacao();
		jdbc = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		jdbc.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		usuario = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO usuarios (login, senha_hash, nome, papel, criado_em)
				VALUES ('t217-proposta', 'x', 'RH', 'profissional_rh', now()) RETURNING id
				""", UUID.class));
	}

	private static ConfigurableApplicationContext abrirAplicacao() {
		return abrirAplicacao(true);
	}

	private static ConfigurableApplicationContext abrirAplicacao(boolean iniciarConsumidores) {
		return new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
					"--app.postgres.password=senha-de-teste", "--app.rabbitmq.host=" + rabbit.getHost(),
					"--app.rabbitmq.port=" + rabbit.getAmqpPort(), "--app.rabbitmq.user=" + rabbit.getAdminUsername(),
					"--app.rabbitmq.password=" + rabbit.getAdminPassword(), "--app.outbox.enabled=false",
					"--spring.rabbitmq.listener.simple.concurrency=2", "--spring.rabbitmq.listener.simple.prefetch=1",
					"--management.health.rabbit.enabled=false", "--management.health.db.enabled=false",
					"--spring.rabbitmq.listener.simple.auto-startup=" + iniciarConsumidores);
	}

	@AfterAll
	static void encerrar() {
		if (contexto != null)
			contexto.close();
		if (rabbit != null)
			rabbit.stop();
		if (postgres != null)
			postgres.stop();
	}

	@ParameterizedTest
	@ValueSource(strings = { "regra", "orcamento", "meta", "periodo", "remover_orcamento", "remover_meta",
			"remover_periodo", "vazio", "ausente", "percentual_ausente", "extensoes" })
	void aplicaPelaFilaComVersaoParametrosRodadaAuditoriaEOutboxCoerentes(String caso) throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		ObjectNode params = (ObjectNode) evento.path("parametros");
		ObjectNode nucleo = (ObjectNode) evento.path("representacao").path("nucleo");
		List<String> corrigidos;
		switch (caso) {
			case "orcamento" -> {
				params.put("orcamento", new BigDecimal("-7.12345678901234567890123456789"));
				corrigidos = List.of("parametros.orcamento");
			}
			case "meta" -> {
				params.put("meta_venda", BigDecimal.ZERO);
				corrigidos = List.of("parametros.meta_venda");
			}
			case "periodo" -> {
				params.set("competencias", JSON.readTree("[\"2030-12\",\"2025-08\",\"2030-12\"]"));
				corrigidos = List.of("parametros.competencias");
			}
			case "remover_orcamento" -> {
				params.remove("orcamento");
				corrigidos = List.of("parametros.orcamento");
			}
			case "remover_meta" -> {
				params.remove("meta_venda");
				corrigidos = List.of("parametros.meta_venda");
			}
			case "remover_periodo" -> {
				params.remove("competencias");
				corrigidos = List.of("parametros.competencias");
			}
			case "vazio" -> {
				params.removeAll();
				corrigidos = List.of("parametros.orcamento", "parametros.meta_venda", "parametros.competencias");
			}
			case "percentual_ausente" -> {
				nucleo.remove("percentual");
				corrigidos = List.of("nucleo.percentual");
			}
			default -> {
				nucleo.put("percentual", new BigDecimal("0.03000000000000000000001"));
				corrigidos = List.of("nucleo.percentual");
				if ("ausente".equals(caso))
					evento.remove("parametros");
				if ("extensoes".equals(caso)) {
					((ObjectNode) evento.path("representacao")).set("extensao_raiz",
							JSON.readTree("{\"valor\":123.12345678901234567890123456789}"));
					((ObjectNode) nucleo.path("vigencia")).put("extensao", "reservada T217");
					nucleo.set("extensao", JSON.readTree("{\"segredo\":123.12345678901234567890123456789}"));
					params.set("extensao", JSON.readTree("{\"fonte\":\"reservada T217\"}"));
					((ObjectNode) evento.path("representacao")).set("especificacoes", JSON.readTree("""
							[{"ref":"elem.1","construto":"generico","descricao":"reservada T217",
							"extensao":{"valores":[0.12345678901234567890123456789]}}]
							"""));
					corrigidos = List.of("nucleo.percentual", "elem.1");
				}
			}
		}
		JsonNode antes = linha("regras", c.regra());
		AppMetrics metricas = contexto.getBean(AppMetrics.class);
		double tentativas = metricas.jobRuns(FILA).count();
		long duracoes = metricas.jobDuration(FILA).count();
		try (var logs = new CapturaDeLog("synapse.api.job.CorrecaoPropostaConsumidor")) {
			publicar(evento);
			esperarResultado(logs, "aplicada");
			verificarLogs(logs, c.job());
		}
		assertThat(linha("regras", c.regra())).isEqualTo(antes);
		JsonNode versao = JSON.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"SELECT row_to_json(r)::text FROM regras r WHERE job_id = ? AND versao = 2", String.class, c.job())));
		assertThat(versao.path("origem").asString()).isEqualTo("correcao");
		assertThat(versao.path("regra_origem_id").asString()).isEqualTo(c.regra().toString());
		assertThat(versao.path("nucleo")).isEqualTo(nucleo);
		assertThat(versao.path("representacao")).isEqualTo(evento.path("representacao"));
		assertThat(versao.path("especificacoes")).isEqualTo(evento.path("representacao").path("especificacoes"));
		JsonNode esperados = JSON.readTree(evento.has("parametros") ? params.toString() : PARAMETROS);
		assertThat(versao.path("parametros")).isEqualTo(esperados);
		assertThat(versao.path("hash").asString()).isEqualTo(HashDaRegra.calcular(
				Objects.requireNonNull(RepresentacaoExtraida.validada(evento.path("representacao").toString())),
				ParametrosExtraidos.deVersaoExistente(esperados.toString())));
		JsonNode job = linha("jobs", c.job());
		assertThat(job.path("status").asString()).isEqualTo("gerando_regra");
		for (String campo : List.of("orcamento", "meta_venda")) {
			if (esperados.has(campo))
				assertThat(job.path(campo).decimalValue()).isEqualByComparingTo(esperados.path(campo).decimalValue());
			else
				assertThat(job.path(campo).isNull()).isTrue();
		}
		List<String> periodo = esperados.has("competencias")
				? esperados.path("competencias").valueStream().map(JsonNode::asString).distinct().sorted().toList()
				: CompetenciasPublicadas.TODAS;
		assertThat(job.path("competencias")).isEqualTo(JSON.valueToTree(periodo));
		JsonNode rodada = linha("rodadas_correcao", c.rodada());
		assertThat(rodada.path("estado").asString()).isEqualTo("corrigida");
		assertThat(rodada.path("regra_resultante_id")).isEqualTo(versao.path("id"));
		assertThat(rodada.path("submissao_correcao_id").asString()).isEqualTo(c.submissao().toString());
		assertThat(jdbc.queryForObject(
				"SELECT count(*) FROM job_transicoes WHERE job_id = ? AND status_novo = 'gerando_regra' AND motivo = 'correcao_aplicada'",
				Integer.class, c.job()))
			.isEqualTo(1);
		JsonNode trilha = JSON.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"SELECT conclusao::text FROM trilhas_auditoria WHERE job_id = ? AND no = 'confirmacao'", String.class,
				c.job())));
		assertThat(trilha.path("editado_pelo_usuario").asBoolean()).isTrue();
		assertThat(trilha.path("campos_corrigidos")).isEqualTo(JSON.valueToTree(corrigidos));
		assertThat(jdbc.queryForObject("SELECT evento_id FROM trilhas_auditoria WHERE job_id = ?", UUID.class, c.job()))
			.isEqualTo(UUID
				.nameUUIDFromBytes(("confirmacao:" + versao.path("id").asString()).getBytes(StandardCharsets.UTF_8)));
		String payload = Objects.requireNonNull(jdbc.queryForObject(
				"SELECT payload::text FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'",
				String.class, c.job()));
		ContratoDeEvento.validar("parametros-confirmados", payload);
		JsonNode publicado = JSON.readTree(payload);
		assertThat(publicado.path("regra_id")).isEqualTo(versao.path("id"));
		assertThat(publicado.path("competencias")).isEqualTo(job.path("competencias"));
		for (String campo : List.of("orcamento", "meta_venda")) {
			assertThat(publicado.has(campo)).isEqualTo(!job.path(campo).isNull());
			if (publicado.has(campo))
				assertThat(publicado.path(campo).decimalValue()).isEqualByComparingTo(job.path(campo).decimalValue());
		}
		await().atMost(Duration.ofSeconds(5))
			.untilAsserted(() -> assertThat(metricas.jobDuration(FILA).count()).isEqualTo(duracoes + 1));
		assertThat(metricas.jobRuns(FILA).count()).isEqualTo(tentativas + 1);
		String scrape = RestClient
			.create("http://localhost:" + contexto.getEnvironment().getProperty("local.server.port"))
			.get()
			.uri("/metrics")
			.retrieve()
			.body(String.class);
		assertThat(scrape).contains("job_runs_total", "job_duration_seconds_count", "job_name=\"correcao-proposta\"")
			.doesNotContain(c.job().toString());
		assertThat(amostra(Objects.requireNonNull(scrape), "job_runs_total")).isEqualTo(tentativas + 1);
		assertThat(amostra(scrape, "job_duration_seconds_count")).isEqualTo(duracoes + 1);
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void ausenciaDoObjetoPreservaJobEArtefatoLegado(boolean nulo) throws Exception {
		Cenario c = cenario();
		String legado = nulo ? null : "{}";
		jdbc.update("UPDATE regras SET parametros = ?::jsonb, hash = ? WHERE id = ?", legado,
				HashDaRegra.calcular(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao(),
						ParametrosExtraidos.deVersaoExistente(legado)),
				c.regra());
		JsonNode original = linha("regras", c.regra());
		JsonNode jobAnterior = linha("jobs", c.job());
		ObjectNode evento = evento(c);
		evento.remove("parametros");
		((ObjectNode) evento.path("representacao").path("nucleo")).put("percentual", new BigDecimal("0.04"));
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(evento);
			esperarResultado(logs, "aplicada");
		}
		assertThat(linha("regras", c.regra())).isEqualTo(original);
		assertThat(jdbc.queryForObject("SELECT parametros::text FROM regras WHERE job_id = ? AND versao = 2",
				String.class, c.job()))
			.isEqualTo(legado);
		JsonNode jobAtual = linha("jobs", c.job());
		JsonNode payload = JSON.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"SELECT payload::text FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'",
				String.class, c.job())));
		for (String campo : List.of("orcamento", "meta_venda", "competencias")) {
			assertThat(jobAtual.path(campo)).isEqualTo(jobAnterior.path(campo));
			assertThat(payload.path(campo)).isEqualTo(jobAtual.path(campo));
		}
		verificarCicloUnico(c);
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void repeticaoSequencialOuConcorrenteProduzUmUnicoCiclo(boolean concorrente) throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		((ObjectNode) evento.path("parametros")).put("orcamento", new BigDecimal("123.456789"));
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			if (concorrente) {
				try (var trava = DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(),
						postgres.getPassword());
						var consulta = trava.prepareStatement("SELECT id FROM jobs WHERE id = ? FOR UPDATE")) {
					trava.setAutoCommit(false);
					consulta.setObject(1, c.job());
					try (var linha = consulta.executeQuery()) {
						assertThat(linha.next()).isTrue();
					}
					publicar(evento);
					publicar(evento);
					await().atMost(Duration.ofSeconds(10))
						.untilAsserted(() -> assertThat(jdbc.queryForObject(
								"SELECT count(*) FROM pg_stat_activity WHERE usename = 'synapse_api' AND wait_event_type = 'Lock' AND query LIKE '%FOR UPDATE OF j%'",
								Integer.class))
							.isEqualTo(2));
					trava.commit();
				}
			}
			else {
				publicar(evento);
				esperarResultado(logs, "aplicada");
				publicar(evento);
			}
			esperarResultado(logs, "aplicada");
			esperarResultado(logs, "duplicada");
			assertThat(logs.eventos()
				.stream()
				.map(CapturaDeLog::emJson)
				.map(JSON::readTree)
				.filter(l -> "aplicada".equals(l.path("extra").path("resultado").asString()))
				.count()).isEqualTo(1);
			verificarLogs(logs, c.job());
		}
		verificarCicloUnico(c);
		JsonNode confirmado = fotografia(c.job());
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(evento);
			esperarResultado(logs, "duplicada");
		}
		assertThat(fotografia(c.job())).isEqualTo(confirmado);
	}

	@Test
	void consumidorRestauraCorrelacaoAposSucessoEDescarteInvalido() throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		((ObjectNode) evento.path("parametros")).put("meta_venda", BigDecimal.ZERO);
		var consumidor = contexto.getBean(CorrecaoPropostaConsumidor.class);
		String anterior = UUID.randomUUID().toString();
		try (var escopo = contexto.getBean(CorrelationContext.class).abrir(anterior, null);
				var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			consumidor.receber(MessageBuilder.withBody(evento.toString().getBytes(StandardCharsets.UTF_8)).build());
			assertThat(org.slf4j.MDC.get("job_id")).isEqualTo(anterior);
			evento.remove("submissao_id");
			assertThatThrownBy(() -> consumidor
				.receber(MessageBuilder.withBody(evento.toString().getBytes(StandardCharsets.UTF_8)).build()))
				.isInstanceOf(org.springframework.amqp.AmqpRejectAndDontRequeueException.class);
			assertThat(org.slf4j.MDC.get("job_id")).isEqualTo(anterior);
			verificarLogs(logs, c.job());
		}
		assertThat(org.slf4j.MDC.get("job_id")).isNull();
	}

	private static void verificarCicloUnico(Cenario c) {
		assertThat(jdbc.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Integer.class, c.job()))
			.isEqualTo(2);
		assertThat(jdbc.queryForObject(
				"SELECT count(*) FROM job_transicoes WHERE job_id = ? AND motivo = 'correcao_aplicada'", Integer.class,
				c.job()))
			.isEqualTo(1);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM trilhas_auditoria WHERE job_id = ? AND no = 'confirmacao'",
				Integer.class, c.job()))
			.isEqualTo(1);
		assertThat(jdbc.queryForObject(
				"SELECT count(*) FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'",
				Integer.class, c.job()))
			.isEqualTo(1);
		assertThat(linha("rodadas_correcao", c.rodada()).path("estado").asString()).isEqualTo("corrigida");
	}

	@ParameterizedTest
	@ValueSource(strings = { "submissao", "origem", "estado" })
	void propostaInaplicavelNaoModificaOPersistido(String caso) throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		((ObjectNode) evento.path("representacao").path("nucleo")).put("percentual", new BigDecimal("0.04"));
		if ("submissao".equals(caso))
			evento.put("submissao_id", UUID.randomUUID().toString());
		if ("origem".equals(caso))
			evento.put("regra_origem_id", cenario().regra().toString());
		if ("estado".equals(caso))
			jdbc.update("UPDATE jobs SET status = 'cancelado' WHERE id = ?", c.job());
		JsonNode antes = fotografia(c.job());
		try (var logs = new CapturaDeLog("synapse.api.job.CorrecaoPropostaConsumidor")) {
			publicar(evento);
			esperarResultado(logs, "descartada");
			verificarLogs(logs, c.job());
		}
		assertThat(fotografia(c.job())).isEqualTo(antes);
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void semAlteracaoFechaTentativaEAbreSucessoraSemCiclo(boolean historica) throws Exception {
		Cenario inicial = cenario();
		Cenario c = inicial;
		if (historica) {
			String parametros = PARAMETROS.replace("485000.1234567890123456789", "123");
			String hash = HashDaRegra.calcular(
					CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao(),
					ParametrosExtraidos.deVersaoExistente(parametros));
			UUID atual = Objects.requireNonNull(jdbc.queryForObject(
					"""
							INSERT INTO regras (job_id, versao, origem, regra_origem_id, nucleo, especificacoes, parametros, hash, criada_em)
							SELECT job_id, 2, 'correcao', id, nucleo, especificacoes, ?::jsonb, ?, now() FROM regras WHERE id = ? RETURNING id
							""",
					UUID.class, parametros, hash, c.regra()));
			jdbc.update("UPDATE rodadas_correcao SET regra_analisada_id = ? WHERE id = ?", atual, c.rodada());
			jdbc.update("UPDATE jobs SET orcamento = 123 WHERE id = ?", c.job());
			c = new Cenario(c.job(), atual, c.submissao(), c.rodada());
		}
		JsonNode antes = fotografia(c.job());
		ObjectNode evento = evento(c);
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(evento);
			esperarResultado(logs, "sem_alteracao");
			verificarLogs(logs, c.job());
		}
		assertThat(linha("rodadas_correcao", c.rodada()).path("estado").asString()).isEqualTo("reextracao_falhou");
		JsonNode depois = fotografia(c.job());
		for (String parte : List.of("job", "regras", "transicoes", "trilhas", "outbox")) {
			assertThat(depois.path(parte)).isEqualTo(antes.path(parte));
		}
		UUID sucessora = Objects.requireNonNull(jdbc
			.queryForObject("SELECT id FROM rodadas_correcao WHERE rodada_anterior_id = ?", UUID.class, c.rodada()));
		JsonNode nova = linha("rodadas_correcao", sucessora);
		assertThat(nova.path("estado").asString()).isEqualTo("pendente");
		assertThat(nova.path("regra_analisada_id").asString()).isEqualTo(c.regra().toString());
		assertThat(nova.path("conflitos")).isEqualTo(linha("rodadas_correcao", c.rodada()).path("conflitos"));
		assertThat(nova.path("submissao_correcao_id").isNull()).isTrue();
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(evento);
			esperarResultado(logs, "duplicada");
		}
		assertThat(fotografia(c.job())).isEqualTo(depois);
	}

	@Test
	void resultadosSaoContadosDepoisDoCommitEExpostosSemIdentificadores() throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		var registry = contexto.getBean(io.micrometer.core.instrument.MeterRegistry.class);
		double aplicadas = contadorResultado(registry, "aplicada");
		double duplicadas = contadorResultado(registry, "duplicada");
		((ObjectNode) evento.path("parametros")).put("meta_venda", BigDecimal.ZERO);
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(evento);
			esperarResultado(logs, "aplicada");
			publicar(evento);
			esperarResultado(logs, "duplicada");
			verificarLogs(logs, c.job());
			assertThat(logs.eventos()
				.stream()
				.map(CapturaDeLog::emJson)
				.map(JSON::readTree)
				.filter(l -> l.path("extra").has("resultado")))
				.allSatisfy(l -> assertThat(l.path("extra").path("motivo").asString()).isNotBlank());
		}
		assertThat(contadorResultado(registry, "aplicada")).isEqualTo(aplicadas + 1);
		assertThat(contadorResultado(registry, "duplicada")).isEqualTo(duplicadas + 1);
		String scrape = Objects.requireNonNull(
				RestClient.create("http://localhost:" + contexto.getEnvironment().getProperty("local.server.port"))
					.get()
					.uri("/metrics")
					.retrieve()
					.body(String.class));
		assertThat(scrape)
			.contains("correcao_propostas_total{resultado=\"aplicada\"}",
					"correcao_propostas_total{resultado=\"duplicada\"}")
			.doesNotContain(c.job().toString());
	}

	private static double contadorResultado(io.micrometer.core.instrument.MeterRegistry registry, String resultado) {
		var contador = registry.find("correcao.propostas").tag("resultado", resultado).counter();
		return contador == null ? 0 : contador.count();
	}

	@ParameterizedTest
	@ValueSource(strings = { "submissao_ausente", "uuid", "parametros_null", "orcamento_null", "meta_null",
			"periodo_vazio", "mes", "representacao", "json" })
	void rejeitaContratoInvalidoSemAplicarNemReenfileirar(String caso) throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		switch (caso) {
			case "submissao_ausente" -> evento.remove("submissao_id");
			case "uuid" -> evento.put("submissao_id", "invalido-reservado-T217");
			case "parametros_null" -> evento.putNull("parametros");
			case "orcamento_null" -> ((ObjectNode) evento.path("parametros")).putNull("orcamento");
			case "meta_null" -> ((ObjectNode) evento.path("parametros")).putNull("meta_venda");
			case "periodo_vazio" -> ((ObjectNode) evento.path("parametros")).set("competencias", JSON.readTree("[]"));
			case "mes" -> ((ObjectNode) evento.path("parametros")).set("competencias", JSON.readTree("[\"2025-13\"]"));
			case "representacao" -> ((ObjectNode) evento.path("representacao")).remove("especificacoes");
			default -> {
			}
		}
		JsonNode antes = fotografia(c.job());
		try (var logs = new CapturaDeLog("synapse.api.job.CorrecaoPropostaConsumidor")) {
			publicarTexto("json".equals(caso) ? "{segredo-T217" : evento.toString());
			esperarResultado(logs, "invalida");
			verificarLogs(logs, "json".equals(caso) ? null : c.job());
		}
		assertThat(fotografia(c.job())).isEqualTo(antes);
		await().atMost(Duration.ofSeconds(5))
			.untilAsserted(() -> assertThat(
					Objects.requireNonNull(contexto.getBean(AmqpAdmin.class).getQueueInfo(FILA)).getMessageCount())
				.isZero());
	}

	@ParameterizedTest
	@ValueSource(strings = { "normal", "concorrente", "reinicio_sem_ack" })
	void colisaoPreservaEventoFechaTentativaELiberaFila(String caso) throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		((ObjectNode) evento.path("representacao")).set("extensao_raiz",
				JSON.readTree("{\"valor\":123.12345678901234567890123456789}"));
		evento.set("extensao_evento", JSON.readTree("{\"privado\":0.12345678901234567890123456789}"));
		JsonNode antes = fotografia(c.job());
		var container = Objects.requireNonNull(
				contexto.getBean(RabbitListenerEndpointRegistry.class).getListenerContainer("correcaoProposta"));
		if ("reinicio_sem_ack".equals(caso)) {
			container.stop();
			publicar(evento);
			var factory = new com.rabbitmq.client.ConnectionFactory();
			factory.setHost(rabbit.getHost());
			factory.setPort(rabbit.getAmqpPort());
			factory.setUsername(rabbit.getAdminUsername());
			factory.setPassword(rabbit.getAdminPassword());
			try (var conexao = factory.newConnection(); var canal = conexao.createChannel()) {
				var entrega = Objects.requireNonNull(canal.basicGet(FILA, false));
				contexto.getBean(CorrecaoPropostaConsumidor.class)
					.receber(MessageBuilder.withBody(entrega.getBody()).build());
				assertThat(linha("rodadas_correcao", c.rodada()).path("estado").asString())
					.isEqualTo("reextracao_falhou");
				contexto.close();
			}
			contexto = abrirAplicacao(false);
			try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
				contexto.getBean(RabbitListenerEndpointRegistry.class).start();
				esperarResultado(logs, "duplicada");
			}
		}
		else {
			try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
				if ("concorrente".equals(caso)) {
					publicarConcorrentes(c, evento);
				}
				else {
					publicar(evento);
				}
				esperarResultado(logs, "bloqueada");
				if ("concorrente".equals(caso))
					esperarResultado(logs, "duplicada");
				verificarLogs(logs, c.job());
			}
		}
		JsonNode rodada = linha("rodadas_correcao", c.rodada());
		assertThat(rodada.path("estado").asString()).isEqualTo("reextracao_falhou");
		assertThat(rodada.path("proposta_nao_aplicada")).isEqualTo(evento);
		JsonNode depois = fotografia(c.job());
		for (String parte : List.of("job", "regras", "transicoes", "trilhas", "outbox"))
			assertThat(depois.path(parte)).isEqualTo(antes.path(parte));
		assertThat(jdbc.queryForObject(
				"SELECT count(*) FROM rodadas_correcao WHERE rodada_anterior_id = ? AND estado = 'pendente' AND regra_analisada_id = ? AND conflitos = ?::jsonb",
				Integer.class, c.rodada(), c.regra(), rodada.path("conflitos").toString()))
			.isEqualTo(1);
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(evento);
			esperarResultado(logs, "duplicada");
		}
		assertThat(fotografia(c.job())).isEqualTo(depois);
		Cenario outro = cenario();
		ObjectNode proxima = evento(outro);
		((ObjectNode) proxima.path("parametros")).put("meta_venda", BigDecimal.ZERO);
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(proxima);
			esperarResultado(logs, "aplicada");
		}
		verificarCicloUnico(outro);
	}

	@Test
	void colisaoNaoExpoePropostaEmHttpNemEmiteSse() throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		((ObjectNode) evento.path("representacao")).put("extensao_privada", "artefato-reservado-T217");
		var emissores = org.mockito.Mockito.mock(synapse.api.core.sse.EmissoresSse.class);
		var consumidor = new CorrecaoPropostaConsumidor(contexto.getBean(CorrecaoPropostaService.class),
				contexto.getBean(CorrelationContext.class), contexto.getBean(AppMetrics.class), emissores);
		consumidor.receber(MessageBuilder.withBody(evento.toString().getBytes(StandardCharsets.UTF_8)).build());
		org.mockito.Mockito.verifyNoInteractions(emissores);
		var mvc = org.springframework.test.web.servlet.setup.MockMvcBuilders
			.standaloneSetup(new RodadasController(contexto.getBean(RodadasRepository.class)))
			.build();
		String resposta = mvc
			.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/jobs/{id}/rodadas",
					c.job()))
			.andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString();
		assertThat(resposta).contains("reextracao_falhou", "pendente")
			.doesNotContain("proposta_nao_aplicada", "extensao_privada", "artefato-reservado-T217");
	}

	private static void publicarConcorrentes(Cenario c, ObjectNode evento) throws Exception {
		try (var trava = DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(),
				postgres.getPassword());
				var consulta = trava.prepareStatement("SELECT id FROM jobs WHERE id = ? FOR UPDATE")) {
			trava.setAutoCommit(false);
			consulta.setObject(1, c.job());
			try (var linha = consulta.executeQuery()) {
				assertThat(linha.next()).isTrue();
			}
			publicar(evento);
			publicar(evento);
			await().atMost(Duration.ofSeconds(10))
				.untilAsserted(() -> assertThat(jdbc.queryForObject(
						"SELECT count(*) FROM pg_stat_activity WHERE usename = 'synapse_api' AND wait_event_type = 'Lock' AND query LIKE '%FOR UPDATE OF j%'",
						Integer.class))
					.isEqualTo(2));
			trava.commit();
		}
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void falhaNaSucessoraRevertePropostaEFechamentoAntesDaReentrega(boolean colisao) throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		if (colisao)
			((ObjectNode) evento.path("parametros")).put("extensao", "segredo-T217");
		JsonNode antes = fotografia(c.job());
		var registry = contexto.getBean(io.micrometer.core.instrument.MeterRegistry.class);
		String resultado = colisao ? "bloqueada" : "sem_alteracao";
		double concluidas = contadorResultado(registry, resultado);
		var container = Objects.requireNonNull(
				contexto.getBean(RabbitListenerEndpointRegistry.class).getListenerContainer("correcaoProposta"));
		jdbc.execute(
				"CREATE FUNCTION t217_sucessora_falha() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''segredo banco T217''; END'");
		jdbc.execute(
				"CREATE TRIGGER t217_sucessora_falha BEFORE INSERT ON rodadas_correcao FOR EACH ROW WHEN (NEW.rodada_anterior_id IS NOT NULL) EXECUTE FUNCTION t217_sucessora_falha()");
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(evento);
			esperarResultado(logs, "falha");
			container.stop();
			assertThat(fotografia(c.job())).isEqualTo(antes);
			assertThat(contadorResultado(registry, resultado)).isEqualTo(concluidas);
			verificarLogs(logs, c.job());
		}
		finally {
			jdbc.execute("DROP TRIGGER t217_sucessora_falha ON rodadas_correcao");
			jdbc.execute("DROP FUNCTION t217_sucessora_falha()");
		}
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			container.start();
			esperarResultado(logs, resultado);
			verificarLogs(logs, c.job());
		}
		assertThat(contadorResultado(registry, resultado)).isEqualTo(concluidas + 1);
		assertThat(linha("rodadas_correcao", c.rodada()).path("proposta_nao_aplicada")).isEqualTo(evento);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM rodadas_correcao WHERE rodada_anterior_id = ?",
				Integer.class, c.rodada()))
			.isEqualTo(1);
		JsonNode depois = fotografia(c.job());
		for (String parte : List.of("job", "regras", "transicoes", "trilhas", "outbox"))
			assertThat(depois.path(parte)).isEqualTo(antes.path(parte));
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void eventoAntigoNaoEncerraSucessoraEmReextracao(boolean falhaAnterior) throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		if (falhaAnterior) {
			contexto.getBean(JobEventosService.class)
				.aplicarEtapaAlterada(c.job(), EtapaDoGrafo.EXTRACAO_PARAMETROS, "erro", null, c.regra(), null,
						c.submissao());
		}
		else {
			try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
				publicar(evento);
				esperarResultado(logs, "sem_alteracao");
			}
		}
		UUID submissao = Objects.requireNonNull(jdbc.queryForObject(
				"INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em) VALUES (?, 'texto', 'outra correcao', now()) RETURNING id",
				UUID.class, usuario));
		jdbc.update(
				"UPDATE rodadas_correcao SET estado = 'em_reextracao', submissao_correcao_id = ? WHERE rodada_anterior_id = ?",
				submissao, c.rodada());
		JsonNode antes = fotografia(c.job());
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(evento);
			esperarResultado(logs, falhaAnterior ? "descartada" : "duplicada");
			verificarLogs(logs, c.job());
		}
		assertThat(fotografia(c.job())).isEqualTo(antes);
	}

	@ParameterizedTest
	@ValueSource(strings = { "competencias", "decimal", "parametros_extensao", "nucleo_extensao" })
	void comparaArtefatoCompletoSemConfundirEquivalenciaEColisao(String caso) throws Exception {
		Cenario c = cenario();
		JsonNode antes = fotografia(c.job());
		ObjectNode evento = evento(c);
		boolean colisao = caso.endsWith("extensao");
		switch (caso) {
			case "competencias" ->
				((ObjectNode) evento.path("parametros")).putArray("competencias").add("2025-11").add("2025-11");
			case "decimal" ->
				((ObjectNode) evento.path("representacao").path("nucleo")).put("percentual", new BigDecimal("0.02500"));
			case "parametros_extensao" -> ((ObjectNode) evento.path("parametros")).put("extensao",
					new BigDecimal("0.12345678901234567890123456789"));
			case "nucleo_extensao" -> ((ObjectNode) evento.path("representacao").path("nucleo")).put("extensao",
					new BigDecimal("0.12345678901234567890123456789"));
			default -> throw new AssertionError(caso);
		}
		try (var logs = new CapturaDeLog(CorrecaoPropostaConsumidor.class)) {
			publicar(evento);
			esperarResultado(logs, colisao ? "bloqueada" : "sem_alteracao");
		}
		assertThat(linha("rodadas_correcao", c.rodada()).path("proposta_nao_aplicada"))
			.isEqualTo(JSON.readTree(evento.toString()));
		assertThat(jdbc.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Integer.class, c.job()))
			.isEqualTo(1);
		JsonNode depois = fotografia(c.job());
		for (String parte : List.of("job", "regras", "transicoes", "trilhas", "outbox"))
			assertThat(depois.path(parte)).isEqualTo(antes.path(parte));
	}

	@Test
	void falhaDeBancoReverteTudoEPermiteReentregaPeloBroker() throws Exception {
		Cenario c = cenario();
		ObjectNode evento = evento(c);
		((ObjectNode) evento.path("parametros")).put("orcamento", new BigDecimal("123.4567890123456789"));
		JsonNode antes = fotografia(c.job());
		AppMetrics metricas = contexto.getBean(AppMetrics.class);
		double falhas = metricas.jobFailures(FILA).count();
		long duracoes = metricas.jobDuration(FILA).count();
		jdbc.execute(
				"CREATE FUNCTION t217_proposta_falha() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''segredo banco T217''; END'");
		jdbc.execute(
				"CREATE TRIGGER t217_proposta_falha BEFORE UPDATE ON rodadas_correcao FOR EACH ROW EXECUTE FUNCTION t217_proposta_falha()");
		var registro = contexto.getBean(RabbitListenerEndpointRegistry.class);
		try (var logs = new CapturaDeLog("synapse.api.job.CorrecaoPropostaConsumidor")) {
			publicar(evento);
			esperarResultado(logs, "falha");
			Objects.requireNonNull(registro.getListenerContainer("correcaoProposta")).stop();
			assertThat(fotografia(c.job())).isEqualTo(antes);
			verificarLogs(logs, c.job());
			assertThat(metricas.jobFailures(FILA).count()).isGreaterThan(falhas);
			assertThat(metricas.jobDuration(FILA).count()).isGreaterThan(duracoes);
			String scrape = Objects.requireNonNull(
					RestClient.create("http://localhost:" + contexto.getEnvironment().getProperty("local.server.port"))
						.get()
						.uri("/metrics")
						.retrieve()
						.body(String.class));
			assertThat(amostra(scrape, "job_failures_total")).isEqualTo(metricas.jobFailures(FILA).count());
			assertThat(amostra(scrape, "job_duration_seconds_count")).isEqualTo(metricas.jobDuration(FILA).count());
			assertThat(scrape).doesNotContain(c.job().toString());
		}
		finally {
			jdbc.execute("DROP TRIGGER t217_proposta_falha ON rodadas_correcao");
			jdbc.execute("DROP FUNCTION t217_proposta_falha()");
			var container = registro.getListenerContainer("correcaoProposta");
			if (container != null)
				container.start();
		}
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(linha("rodadas_correcao", c.rodada()).path("estado").asString())
				.isEqualTo("corrigida"));
		verificarCicloUnico(c);
	}

	private static Cenario cenario() {
		UUID job = contexto.getBean(JobService.class)
			.criar(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO), usuario)
			.id();
		UUID regra = Objects
			.requireNonNull(jdbc.queryForObject("SELECT id FROM regras WHERE job_id = ?", UUID.class, job));
		jdbc.update(
				"UPDATE jobs SET status = 'aguardando_confirmacao_parametros', meta_venda = 12000000.9876543210987654321 WHERE id = ?",
				job);
		jdbc.update("UPDATE regras SET parametros = ?::jsonb, hash = ? WHERE id = ?", PARAMETROS,
				HashDaRegra.calcular(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao(),
						ParametrosExtraidos.deVersaoExistente(PARAMETROS)),
				regra);
		UUID submissao = Objects.requireNonNull(jdbc.queryForObject(
				"INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em) VALUES (?, 'texto', 'segredo texto T217', now()) RETURNING id",
				UUID.class, usuario));
		UUID rodada = Objects.requireNonNull(jdbc.queryForObject(
				"""
						INSERT INTO rodadas_correcao (job_id, regra_analisada_id, submissao_correcao_id, conflitos, estado, criada_em, atualizada_em)
						VALUES (?, ?, ?, '[{"elementos":["nucleo.percentual"],"motivo":"segredo conflito T217"}]'::jsonb, 'em_reextracao', now(), now()) RETURNING id
						""",
				UUID.class, job, regra, submissao));
		return new Cenario(job, regra, submissao, rodada);
	}

	private static ObjectNode evento(Cenario c) {
		ObjectNode evento = JSON.createObjectNode();
		evento.put("job_id", c.job().toString());
		evento.put("regra_origem_id", c.regra().toString());
		evento.put("submissao_id", c.submissao().toString());
		evento.set("representacao",
				JSON.valueToTree(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao()));
		evento.set("parametros", JSON.readTree(PARAMETROS));
		return evento;
	}

	private static void publicar(ObjectNode evento) throws Exception {
		ContratoDeEvento.validar(FILA, evento.toString());
		publicarTexto(evento.toString());
	}

	private static void publicarTexto(String texto) {
		assertThat(contexto.getBean(AmqpAdmin.class).getQueueInfo(FILA)).as("fila durável declarada pela aplicação")
			.isNotNull();
		contexto.getBean(RabbitTemplate.class)
			.send(FILA,
					MessageBuilder.withBody(texto.getBytes(StandardCharsets.UTF_8))
						.setContentType("application/json")
						.build());
	}

	private static void esperarResultado(CapturaDeLog logs, String resultado) {
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(logs.eventos()
				.stream()
				.map(CapturaDeLog::emJson)
				.map(JSON::readTree)
				.anyMatch(l -> resultado.equals(l.path("extra").path("resultado").asString()))).isTrue());
		var registry = contexto.getBean(io.micrometer.core.instrument.MeterRegistry.class);
		double contador = contadorResultado(registry, resultado);
		assertThat(contador).isPositive();
		assertThat(registry.get("correcao.propostas").tag("resultado", resultado).counter().getId().getTags())
			.containsExactly(io.micrometer.core.instrument.Tag.of("resultado", resultado));
		String scrape = Objects.requireNonNull(
				RestClient.create("http://localhost:" + contexto.getEnvironment().getProperty("local.server.port"))
					.get()
					.uri("/metrics")
					.retrieve()
					.body(String.class));
		String amostra = scrape.lines()
			.filter(l -> l.startsWith("correcao_propostas_total{resultado=\"" + resultado + "\"} "))
			.findFirst()
			.orElseThrow();
		assertThat(Double.parseDouble(amostra.substring(amostra.lastIndexOf(' ') + 1)))
			.isGreaterThanOrEqualTo(contador);
	}

	private static void verificarLogs(CapturaDeLog logs, @Nullable UUID job) throws Exception {
		assertThat(logs.eventos()).isNotEmpty();
		for (var e : logs.eventos()) {
			String linha = CapturaDeLog.emJson(e);
			ContratoDeEvento.validarLog(linha);
			if (job != null)
				assertThat(JSON.readTree(linha).path("job_id").asString()).isEqualTo(job.toString());
			assertThat(linha).doesNotContain("segredo", "reservada", "percentual", "485000", "PSQLException",
					"representacao");
		}
	}

	private static JsonNode linha(String tabela, UUID id) {
		return JSON.readTree(Objects.requireNonNull(jdbc
			.queryForObject("SELECT row_to_json(t)::text FROM " + tabela + " t WHERE id = ?", String.class, id)));
	}

	private static JsonNode fotografia(UUID job) {
		return JSON.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"""
						SELECT jsonb_build_object('job', to_jsonb(j),
						'regras', (SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM regras r WHERE job_id = j.id),
						'rodadas', (SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM rodadas_correcao r WHERE job_id = j.id),
						'transicoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM job_transicoes t WHERE job_id = j.id),
						'trilhas', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM trilhas_auditoria t WHERE job_id = j.id),
						'outbox', (SELECT jsonb_agg(to_jsonb(o) ORDER BY id) FROM outbox_events o WHERE job_id = j.id))::text FROM jobs j WHERE id = ?
						""",
				String.class, job)));
	}

	private static double amostra(String scrape, String nome) {
		String linha = scrape.lines()
			.filter(l -> l.startsWith(nome + "{") && l.contains("job_name=\"correcao-proposta\""))
			.findFirst()
			.orElseThrow();
		return Double.parseDouble(linha.substring(linha.lastIndexOf(' ') + 1));
	}

	record Cenario(UUID job, UUID regra, UUID submissao, UUID rodada) {
	}

}
