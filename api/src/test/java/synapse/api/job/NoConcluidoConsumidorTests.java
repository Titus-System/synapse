package synapse.api.job;

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

import ch.qos.logback.classic.spi.ILoggingEvent;
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
import org.springframework.dao.DataIntegrityViolationException;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;
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
	void falhaDaTrilhaNaoInterrompeSimulacaoEReentregaGravaUmaUnicaVez() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID codigoId = criarCodigoGerado(jobId, regraId);
		UUID resultadoId = criarResultado(jobId, codigoId);
		UUID eventoId = UUID.randomUUID();
		double falhas = consumos("falha");
		double gravados = consumos("gravado");
		double duplicados = consumos("duplicado");
		try (CapturaDeLog captura = new CapturaDeLog(NoConcluidoConsumidor.class)) {
			try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
				statement.execute("REVOKE INSERT ON trilhas_auditoria FROM synapse_api");
			}
			try {
				publicar(eventoId, jobId, "geracao_codigo", regraId, codigoId, null, null);
				await().atMost(Duration.ofSeconds(15))
					.untilAsserted(() -> assertThat(consumos("falha")).isGreaterThan(falhas));
				String corpo = """
						{"job_id":"%s","resultado_id":"%s","status":"sucesso","veredito":"viavel"}
						""".formatted(jobId, resultadoId);
				ContratoDeEvento.validar("simulacao-concluida", corpo);
				rabbitTemplate.send("", RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API,
						MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
							.setContentType(MessageProperties.CONTENT_TYPE_JSON)
							.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
							.build());
				await().atMost(Duration.ofSeconds(15))
					.untilAsserted(() -> assertThat(contexto.getBean(JobService.class).buscar(jobId).status())
						.isEqualTo("aguardando_decisao_usuario"));
				assertThat(contarTrilhas(jobId)).isZero();
				assertThat(consumos("gravado")).isEqualTo(gravados);
			}
			finally {
				try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
					statement.execute("GRANT INSERT ON trilhas_auditoria TO synapse_api");
				}
			}
			await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
				assertThat(contarTrilhas(jobId)).isEqualTo(1);
				assertThat(consumos("gravado")).isEqualTo(gravados + 1);
				assertThat(resultadoDaSimulacao(codigoId)).isEqualTo(resultadoId);
			});
			publicar(eventoId, jobId, "geracao_codigo", regraId, codigoId, null, null);
			await().atMost(Duration.ofSeconds(10))
				.untilAsserted(() -> assertThat(consumos("duplicado")).isEqualTo(duplicados + 1));
			assertThat(contarTrilhas(jobId)).isEqualTo(1);
			assertThat(consumos("gravado")).isEqualTo(gravados + 1);
			var falha = captura.eventos()
				.stream()
				.filter(e -> e.getMessage().equals("falha na gravação da trilha; mensagem será reentregue"))
				.findFirst()
				.orElseThrow();
			String linha = CapturaDeLog.emJson(falha);
			ContratoDeEvento.validarLog(linha);
			var json = new JsonMapper().readTree(linha);
			assertThat(json.path("job_id").asString()).isEqualTo(jobId.toString());
			assertThat(json.path("extra").path("no").asString()).isEqualTo("geracao_codigo");
			assertThat(json.path("extra").path("classe_falha").asString()).isEqualTo("BadSqlGrammarException");
			assertThat(linha).doesNotContain("conclusao", "exception", "INSERT", "senha-de-teste");
		}
		int porta = Objects
			.requireNonNull(
					((org.springframework.boot.web.server.context.WebServerApplicationContext) contexto).getWebServer())
			.getPort();
		var resposta = java.net.http.HttpClient.newHttpClient()
			.send(java.net.http.HttpRequest.newBuilder(java.net.URI.create("http://localhost:" + porta + "/metrics"))
				.GET()
				.build(), java.net.http.HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(200);
		for (String resultado : List.of("gravado", "duplicado", "falha")) {
			var amostras = resposta.body()
				.lines()
				.filter(l -> l.startsWith("no_concluido_consumo_total{")
						&& l.contains("resultado=\"" + resultado + "\""))
				.toList();
			assertThat(amostras).hasSize(1);
			assertThat(Double.parseDouble(amostras.getFirst().substring(amostras.getFirst().lastIndexOf(' ') + 1)))
				.isEqualTo(consumos(resultado))
				.isPositive();
		}
	}

	private static double consumos(String resultado) {
		var contador = contexto.getBean(io.micrometer.core.instrument.MeterRegistry.class)
			.find("no.concluido.consumo")
			.tag("resultado", resultado)
			.counter();
		return contador == null ? 0 : contador.count();
	}

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

	// --- Busca da meta maior em curso (T-283) ---------------------------------------

	@Test
	void decisaoQueAbriuABuscaDeixaOJobComABuscaEmCursoAteAMetaChegar() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		mudarStatus(jobId, "aguardando_decisao_usuario");
		assertThat(buscaEmCurso(jobId)).isNull();

		publicarDecisao(UUID.randomUUID(), jobId, regraId, "busca_meta");

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(buscaEmCurso(jobId)).isTrue());
		registrarBuscaSemSolucao(jobId, regraId);
		assertThat(buscaEmCurso(jobId)).isNull();
	}

	@Test
	void oFechoDaBuscaSemMetaRegistradaTambemAEncerra() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		mudarStatus(jobId, "aguardando_decisao_usuario");

		publicarDecisao(UUID.randomUUID(), jobId, regraId, "busca_meta");
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(buscaEmCurso(jobId)).isTrue());
		publicarFechoDaBusca(UUID.randomUUID(), jobId, regraId);

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(buscaEmCurso(jobId)).isNull());
	}

	@Test
	void oServicoAnunciaOComecoEOFimUmaVezSoMesmoComReentrega() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		mudarStatus(jobId, "aguardando_decisao_usuario");
		JobEventosService servico = contexto.getBean(JobEventosService.class);
		UUID abertura = UUID.randomUUID();
		UUID fecho = UUID.randomUUID();

		assertThat(registrarDecisao(servico, abertura, jobId, regraId, "busca_meta"))
			.isEqualTo(JobEventosService.BuscaMetaAnunciada.INICIADA);
		assertThat(registrarDecisao(servico, abertura, jobId, regraId, "busca_meta"))
			.isEqualTo(JobEventosService.BuscaMetaAnunciada.DUPLICADA);
		assertThat(registrarDecisao(servico, fecho, jobId, regraId, null))
			.isEqualTo(JobEventosService.BuscaMetaAnunciada.ENCERRADA);
		assertThat(registrarDecisao(servico, fecho, jobId, regraId, null))
			.isEqualTo(JobEventosService.BuscaMetaAnunciada.DUPLICADA);
	}

	@Test
	void oFechoDepoisDaMetaRegistradaNaoAnunciaDeNovo() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		mudarStatus(jobId, "aguardando_decisao_usuario");
		JobEventosService servico = contexto.getBean(JobEventosService.class);

		assertThat(registrarDecisao(servico, UUID.randomUUID(), jobId, regraId, "busca_meta"))
			.isEqualTo(JobEventosService.BuscaMetaAnunciada.INICIADA);
		registrarBuscaSemSolucao(jobId, regraId);

		assertThat(registrarDecisao(servico, UUID.randomUUID(), jobId, regraId, null))
			.isEqualTo(JobEventosService.BuscaMetaAnunciada.NENHUMA);
	}

	@Test
	void decisaoQueEncerrouOFluxoNaoAbreBusca() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		mudarStatus(jobId, "aguardando_decisao_usuario");

		publicarDecisao(UUID.randomUUID(), jobId, regraId, "fim");

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(contarTrilhas(jobId)).isEqualTo(1));
		assertThat(buscaEmCurso(jobId)).isNull();
	}

	@Test
	void buscaDeUmaVersaoSuperadaNaoEstaEmCurso() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		mudarStatus(jobId, "aguardando_decisao_usuario");

		publicarDecisao(UUID.randomUUID(), jobId, regraId, "busca_meta");
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(buscaEmCurso(jobId)).isTrue());
		criarVersaoSeguinte(jobId);

		assertThat(buscaEmCurso(jobId)).isNull();
	}

	@Test
	void comOJobForaDaDecisaoDoUsuarioABuscaNaoEstaEmCurso() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);

		publicarDecisao(UUID.randomUUID(), jobId, regraId, "busca_meta");

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(contarTrilhas(jobId)).isEqualTo(1));
		assertThat(buscaEmCurso(jobId)).isNull();
		mudarStatus(jobId, "aguardando_decisao_usuario");
		assertThat(buscaEmCurso(jobId)).isTrue();
		mudarStatus(jobId, "arquivado");
		assertThat(buscaEmCurso(jobId)).isNull();
	}

	// --- Resultado sobre o qual a etapa agiu (T-301) -----------------------------------

	@Test
	void umaEtapaComResultadoGravaAReferenciaNaTrilha() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID resultadoId = criarResultado(jobId, criarCodigoGerado(jobId, regraId));

		publicarConformeOContrato(corpoDaDecisao(UUID.randomUUID(), jobId, regraId, "2025-11-28T14:32:10Z",
				"{\"resumo\":\"x\"}", resultadoId));

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(contarTrilhas(jobId)).isEqualTo(1));
		assertThat(trilhaUnica(jobId).resultadoId()).isEqualTo(resultadoId);
	}

	@Test
	void umaEtapaSemResultadoGravaAColunaNula() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);

		publicarConformeOContrato(
				corpoDaDecisao(UUID.randomUUID(), jobId, regraId, "2025-11-28T14:32:10Z", "{\"resumo\":\"x\"}", null));

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(contarTrilhas(jobId)).isEqualTo(1));
		assertThat(trilhaUnica(jobId).resultadoId()).isNull();
	}

	@Test
	void aReentregaDeUmaEtapaComResultadoGravaUmaUnicaLinha() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID resultadoId = criarResultado(jobId, criarCodigoGerado(jobId, regraId));
		String corpo = corpoDaDecisao(UUID.randomUUID(), jobId, regraId, "2025-11-28T14:32:10Z", "{\"resumo\":\"x\"}",
				resultadoId);

		publicarConformeOContrato(corpo);
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(contarTrilhas(jobId)).isEqualTo(1));
		publicarConformeOContrato(corpo);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.NO_CONCLUIDO).getMessageCount()).isZero());
		assertThat(trilhaUnica(jobId).resultadoId()).isEqualTo(resultadoId);
	}

	/**
	 * A decisão que abre a busca aponta o resultado decidido, e a que a encerra aponta a
	 * candidata vencedora, que não tem linha em {@code simulacoes}. A busca abre e fecha
	 * como sem o campo, e o anúncio no log não leva nada da conclusão.
	 */
	@Test
	void aBuscaComResultadoNasDuasLinhasAbreEEncerraComoSemEle() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		mudarStatus(jobId, "aguardando_decisao_usuario");
		UUID codigoGeradoId = criarCodigoGerado(jobId, regraId);
		UUID decidido = criarResultado(jobId, codigoGeradoId);
		UUID candidata = criarCandidataDaBusca(jobId, codigoGeradoId);
		String resumoDaAbertura = "Fluxo encaminhado para a busca de uma meta maior.";
		String resumoDoFecho = "busca encerrada com uma meta maior encontrada";

		try (CapturaDeLog captura = new CapturaDeLog(NoConcluidoConsumidor.class)) {
			publicarConformeOContrato(corpoDaDecisao(UUID.randomUUID(), jobId, regraId, "2025-11-28T14:32:10Z",
					"{\"resumo\":\"%s\",\"encaminhamento\":\"busca_meta\"}".formatted(resumoDaAbertura), decidido));
			await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(buscaEmCurso(jobId)).isTrue());
			publicarConformeOContrato(corpoDaDecisao(UUID.randomUUID(), jobId, regraId, "2025-11-28T14:40:10Z",
					"{\"resumo\":\"%s\",\"desfecho_busca\":\"encontrada\",\"candidatas_simuladas\":3}"
						.formatted(resumoDoFecho),
					candidata));
			await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(buscaEmCurso(jobId)).isNull());

			await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(anuncios(captura)).hasSize(2));
			List<String> status = new ArrayList<>();
			for (ILoggingEvent anuncio : anuncios(captura)) {
				String linha = CapturaDeLog.emJson(anuncio);
				ContratoDeEvento.validarLog(linha);
				assertThat(linha).doesNotContain(resumoDaAbertura, resumoDoFecho);
				JsonNode log = new JsonMapper().readTree(linha);
				assertThat(log.path("job_id").asString()).isEqualTo(jobId.toString());
				status.add(log.path("extra").path("status").asString());
			}
			assertThat(status).containsExactly("buscando_meta", "busca_meta_encerrada");
		}
		assertThat(trilhas(jobId)).extracting(Trilha::resultadoId).containsExactly(decidido, candidata);
	}

	/**
	 * Pela fila, a violação da chave estrangeira volta para a fila como as das demais
	 * referências (skill consumidores); o serviço é chamado direto para não deixar a
	 * mensagem em loop.
	 */
	@Test
	void umResultadoInexistentePropagaAFalhaSemGravarATrilha() throws Exception {
		UUID jobId = criarJob();
		UUID regraId = criarRegra(jobId);
		UUID eventoId = UUID.randomUUID();
		JobEventosService servico = contexto.getBean(JobEventosService.class);
		NoConcluidoDto evento = new NoConcluidoDto(eventoId, jobId, "decisao", Instant.parse("2025-11-28T14:32:10Z"),
				new JsonMapper().readTree("{\"resumo\":\"x\"}"), regraId, null, null, null, null, UUID.randomUUID());

		assertThatExceptionOfType(DataIntegrityViolationException.class)
			.isThrownBy(() -> servico.registrarNoConcluido(jobId, eventoId, EtapaDoGrafo.DECISAO, evento));
		assertThat(contarTrilhas(jobId)).isZero();
	}

	private static String corpoDaDecisao(UUID eventoId, UUID jobId, UUID regraId, String concluidoEm, String conclusao,
			@Nullable UUID resultadoId) {
		String resultado = (resultadoId != null) ? ",\"resultado_id\":\"%s\"".formatted(resultadoId) : "";
		return """
				{"evento_id":"%s","job_id":"%s","no":"decisao","concluido_em":"%s","conclusao":%s,"regra_id":"%s"%s}
				""".formatted(eventoId, jobId, concluidoEm, conclusao, regraId, resultado).strip();
	}

	private static void publicarConformeOContrato(String corpo) throws Exception {
		ContratoDeEvento.validar("no-concluido", corpo);
		enviarCorpo(corpo);
	}

	private static List<ILoggingEvent> anuncios(CapturaDeLog captura) {
		return captura.eventos()
			.stream()
			.filter((linha) -> "busca da meta maior anunciada".equals(linha.getMessage()))
			.toList();
	}

	private static UUID criarCandidataDaBusca(UUID jobId, UUID codigoGeradoId) throws SQLException {
		UUID resultadoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute(
					"""
							INSERT INTO resultados_simulacao (id, job_id, codigo_gerado_id, status, veredito, assercoes, proposito, meta_venda, criado_em)
							VALUES ('%s', '%s', '%s', 'sucesso', 'viavel', '[]'::jsonb, 'busca_meta', 1200, now())
							"""
						.formatted(resultadoId, jobId, codigoGeradoId));
		}
		return resultadoId;
	}

	private record Trilha(String no, @Nullable UUID simulacaoId, @Nullable UUID resultadoId) {
	}

	private static @Nullable Boolean buscaEmCurso(UUID jobId) {
		return contexto.getBean(JobService.class).buscar(jobId).busca_meta_em_curso();
	}

	private static void publicarDecisao(UUID eventoId, UUID jobId, UUID regraId, String encaminhamento) {
		enviarCorpo("""
				{"evento_id":"%s","job_id":"%s","no":"decisao","concluido_em":"2025-11-28T14:32:10Z",
				 "conclusao":{"resumo":"x","encaminhamento":"%s"},"regra_id":"%s"}
				""".formatted(eventoId, jobId, encaminhamento, regraId));
	}

	// Como o codegen fecha a busca: outra decisão da mesma versão, sem encaminhamento.
	private static void publicarFechoDaBusca(UUID eventoId, UUID jobId, UUID regraId) {
		enviarCorpo("""
				{"evento_id":"%s","job_id":"%s","no":"decisao","concluido_em":"2025-11-28T14:40:00Z",
				 "conclusao":{"resumo":"Busca encerrada sem meta maior no intervalo pesquisado."},"regra_id":"%s"}
				""".formatted(eventoId, jobId, regraId));
	}

	private static JobEventosService.BuscaMetaAnunciada registrarDecisao(JobEventosService servico, UUID eventoId,
			UUID jobId, UUID regraId, @Nullable String encaminhamento) {
		String conclusao = encaminhamento == null ? "{\"resumo\":\"x\"}"
				: "{\"resumo\":\"x\",\"encaminhamento\":\"%s\"}".formatted(encaminhamento);
		Instant concluidoEm = encaminhamento == null ? Instant.parse("2025-11-28T14:40:00Z")
				: Instant.parse("2025-11-28T14:32:10Z");
		NoConcluidoDto evento = new NoConcluidoDto(eventoId, jobId, "decisao", concluidoEm,
				new JsonMapper().readTree(conclusao), regraId, null, null, null, null, null);
		return servico.registrarNoConcluido(jobId, eventoId, EtapaDoGrafo.DECISAO, evento);
	}

	private static void mudarStatus(UUID jobId, String status) throws SQLException {
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("UPDATE jobs SET status = '%s' WHERE id = '%s'".formatted(status, jobId));
		}
	}

	private static void criarVersaoSeguinte(UUID jobId) throws SQLException {
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
					VALUES ('%s', '%s', 2, 'confirmacao_usuario', '{}'::jsonb, '[]'::jsonb, '%s', now())
					""".formatted(UUID.randomUUID(), jobId, "1".repeat(64)));
		}
	}

	// A meta sugerida é a api que grava, ao consumir meta-venda-sugerida; a fixture usa o
	// dono
	// para não depender do codegen.
	private static void registrarBuscaSemSolucao(UUID jobId, UUID regraId) throws SQLException {
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO sugestoes_meta_venda (job_id, regra_id, motivo_sem_solucao)
					VALUES ('%s', '%s', 'intervalo_esgotado')
					""".formatted(jobId, regraId));
		}
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
						"SELECT no, simulacao_id, resultado_id FROM trilhas_auditoria WHERE job_id = '%s' ORDER BY concluido_em"
							.formatted(jobId))) {
			while (rs.next()) {
				trilhas.add(new Trilha(Objects.requireNonNull(rs.getString("no")),
						rs.getObject("simulacao_id", UUID.class), rs.getObject("resultado_id", UUID.class)));
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
