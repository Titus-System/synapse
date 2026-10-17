package synapse.api.submissoes;

import java.io.ByteArrayOutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import com.zaxxer.hikari.HikariDataSource;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.jspecify.annotations.Nullable;
import org.springframework.transaction.PlatformTransactionManager;
import synapse.api.core.config.AppProperties;
import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.job.JobsDeSubmissoes;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import synapse.api.ApiApplication;
import synapse.api.job.ContratoDeEvento;
import synapse.api.job.StreamCliente;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * O processamento da transcrição pelo caminho real: a api sobe contra um Postgres de
 * verdade, o job de voz é criado por {@code POST /submissoes} e o provedor é um servidor
 * HTTP local que responde como o Deepgram. Nada substitui o processador nem o cliente - o
 * teste chama {@code processarPendentes()} do bean e observa o banco, o stream SSE, a
 * consulta do job, os logs e as métricas.
 *
 * <p>
 * O agendamento fica desligado neste contexto para que o ciclo aconteça só quando o teste
 * manda. Dois testes sobem contextos próprios para exercitar o agendamento e a ausência
 * da chave, que são decisões de inicialização.
 */
class ProcessadorTranscricaoTests {

	private static final UUID USUARIO = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final String PARAMETROS = "{\"finalidade\":\"entrada_inicial\",\"tipo\":\"voz\"}";

	private static final String CHAVE = "chave-ficticia-do-teste";

	private static final String TEXTO = "Comissão privada de cinco por cento sobre as vendas da loja treze.";

	private static final String MOTIVO = "Não foi possível transcrever a gravação. Envie a regra de novo, por texto ou por voz.";

	/** Três minutos de WAV PCM mono 8 kHz 16 bits: o limite de duração do contrato. */
	private static final int DURACAO_MAXIMA_SEGUNDOS = 180;

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static PostgreSQLContainer postgres;

	private static ConfigurableApplicationContext contexto;

	private static HttpServer provedor;

	private static ExecutorService executorDoProvedor;

	private static ProcessadorTranscricao processador;

	private static RelogioControlado relogio = new RelogioControlado();

	private static final AtomicReference<String> RETRY_AFTER = new AtomicReference<>();

	private static final AtomicBoolean RESPOSTA_INVALIDA = new AtomicBoolean();

	private static JdbcTemplate dono;

	private static String base;

	/**
	 * O que o provedor fará na próxima chamada; cada teste ajusta o que lhe interessa.
	 */
	private static final AtomicInteger STATUS = new AtomicInteger(200);

	private static final AtomicReference<String> TRANSCRITO = new AtomicReference<>(TEXTO);

	private static final AtomicInteger CHAMADAS = new AtomicInteger();

	private static final AtomicReference<byte[]> RECEBIDO = new AtomicReference<>(new byte[0]);

	private static final AtomicReference<String> CONTENT_TYPE = new AtomicReference<>("");

	/**
	 * Roda dentro do handler do provedor, com a chamada em curso e sem transação nossa.
	 */
	private static final AtomicReference<Runnable> DURANTE_A_CHAMADA = new AtomicReference<>();

	@BeforeAll
	static void iniciar() throws Exception {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		executorDoProvedor = Executors.newCachedThreadPool();
		provedor = HttpServer.create(new InetSocketAddress(InetAddress.getByAddress(new byte[] { 127, 0, 0, 1 }), 0),
				0);
		provedor.setExecutor(executorDoProvedor);
		provedor.createContext("/v1/listen", ProcessadorTranscricaoTests::responder);
		provedor.start();
		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.keycloak.enabled=false", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
					"--app.postgres.password=senha-de-teste", "--spring.rabbitmq.dynamic=false",
					"--spring.rabbitmq.listener.simple.auto-startup=false", "--management.health.rabbit.enabled=false",
					"--management.health.db.enabled=false", "--app.outbox.enabled=false",
					"--app.transcription.api-key=" + CHAVE,
					"--app.transcription.base-url=http://127.0.0.1:" + provedor.getAddress().getPort(),
					"--app.transcription.connect-timeout-ms=1000", "--app.transcription.read-timeout-ms=5000",
					"--app.transcription.processor.enabled=false",
					"--app.transcription.processor.reservation-timeout=30s");
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		processador = contexto.getBean(ProcessadorTranscricao.class);
		base = "http://localhost:" + contexto.getEnvironment().getProperty("local.server.port");
	}

	private static void responder(HttpExchange exchange) throws java.io.IOException {
		CHAMADAS.incrementAndGet();
		RECEBIDO.set(exchange.getRequestBody().readAllBytes());
		CONTENT_TYPE.set(exchange.getRequestHeaders().getFirst("Content-Type"));
		Runnable durante = DURANTE_A_CHAMADA.get();
		if (durante != null) {
			durante.run();
		}
		byte[] corpo = ("{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":\"" + TRANSCRITO.get()
				+ "\"}]}]}}")
			.getBytes(StandardCharsets.UTF_8);
		if (RESPOSTA_INVALIDA.get()) {
			corpo = "{}".getBytes(StandardCharsets.UTF_8);
		}
		String prazo = RETRY_AFTER.get();
		if (prazo != null) {
			exchange.getResponseHeaders().add("Retry-After", prazo);
		}
		exchange.getResponseHeaders().add("Content-Type", "application/json");
		exchange.sendResponseHeaders(STATUS.get(), corpo.length);
		try (var saida = exchange.getResponseBody()) {
			saida.write(corpo);
		}
		finally {
			exchange.close();
		}
	}

	@AfterAll
	static void encerrar() {
		if (contexto != null) {
			contexto.close();
		}
		if (provedor != null) {
			provedor.stop(0);
		}
		if (executorDoProvedor != null) {
			executorDoProvedor.shutdownNow();
		}
		if (postgres != null) {
			postgres.stop();
		}
	}

	@BeforeEach
	void limpar() {
		relogio = new RelogioControlado();
		processador = novoProcessador();
		RETRY_AFTER.set(null);
		RESPOSTA_INVALIDA.set(false);
		STATUS.set(200);
		TRANSCRITO.set(TEXTO);
		CHAMADAS.set(0);
		DURANTE_A_CHAMADA.set(null);
		dono.execute("TRUNCATE usuarios CASCADE");
		dono.update(
				"INSERT INTO usuarios (id, login, nome, papel, keycloak_sub, criado_em) VALUES (?, 'rh', 'RH', 'profissional_rh', 'subject-a', now())",
				USUARIO);
	}

	@AfterEach
	void conferirCorrelacaoLimpa() {
		processador.encerrar();
		assertThat(MDC.get("job_id")).as("o ciclo não pode deixar o job_id na thread").isNull();
	}

	@Test
	void falhaTransitoriaReagendaSemEncerrarOJob() throws Exception {
		STATUS.set(503);
		var criada = criarVoz(wav(1), "audio/wav");
		processador.processarPendentes();
		assertThat(status(criada.job())).isEqualTo("aguardando_transcricao");
		assertThat(trabalho(criada.job())).containsEntry("estado", "pendente")
			.containsEntry("tentativas", 1)
			.hasEntrySatisfying("proxima_tentativa_em", instante -> assertThat(instante).isNotNull());
		processador.processarPendentes();
		assertThat(CHAMADAS.get()).isEqualTo(1);
		assertThat(contar("outbox_events")).isZero();
	}

	@Test
	void audioNoLimiteDeDuracaoEhTranscritoEOJobSegueComOEvento() throws Exception {
		byte[] audio = wav(DURACAO_MAXIMA_SEGUNDOS);
		var criada = criarVoz(audio, "audio/wav");
		UUID job = criada.job();
		var stream = abrirStream(job);
		try {
			stream.aguardarBloco("\"status\":\"aguardando_transcricao\"", Duration.ofSeconds(10));

			processador.processarPendentes();

			assertThat(CHAMADAS.get()).isEqualTo(1);
			assertThat(RECEBIDO.get()).as("o provedor recebe o áudio como foi gravado").containsExactly(audio);
			assertThat(CONTENT_TYPE.get()).isEqualTo("audio/wav");
			assertThat(dono.queryForMap("SELECT transcricao, transcrito_em FROM submissoes WHERE id = ?", criada.id()))
				.containsEntry("transcricao", TEXTO)
				.hasEntrySatisfying("transcrito_em", instante -> assertThat(instante).isNotNull());
			assertThat(trabalho(job)).containsEntry("estado", "concluido")
				.containsEntry("tentativas", 1)
				.containsEntry("reservado_ate", null);
			assertThat(status(job)).isEqualTo("gerando_regra");

			String payload = Objects.requireNonNull(dono.queryForObject(
					"SELECT payload::text FROM outbox_events WHERE job_id = ? AND tipo = 'regra-submetida'",
					String.class, job));
			ContratoDeEvento.validar("regra-submetida", payload);
			var evento = JSON.readTree(payload);
			assertThat(evento.path("origem").asString()).isEqualTo("voz");
			assertThat(evento.path("submissao_id").asString()).isEqualTo(criada.id().toString());
			assertThat(evento.has("regra_id")).as("a extração ainda não aconteceu").isFalse();
			assertThat(evento.path("competencias").toString())
				.isEqualTo("[\"2025-08\",\"2025-09\",\"2025-10\",\"2025-11\",\"2025-12\"]");

			JsonNode estado = estadoDoStream(
					stream.aguardarBloco("\"status\":\"gerando_regra\"", Duration.ofSeconds(10)));
			assertThat(estado.path("status_anterior").asString()).isEqualTo("aguardando_transcricao");
			assertThat(estado.has("motivo")).isFalse();
			assertThat(consultar(job).has("motivo")).isFalse();
		}
		finally {
			stream.fechar();
		}
	}

	@ParameterizedTest
	@CsvSource({ "400,permanente", "200,texto_vazio" })
	void falhaDoProvedorTerminaOJobEmErroComOMotivoLocalizado(int status, String classe) throws Exception {
		STATUS.set(status);
		if ("texto_vazio".equals(classe)) {
			// Espaço ideográfico: um áudio sem fala não vira regra vazia.
			TRANSCRITO.set("  \\u3000 ");
		}
		var criada = criarVoz(wav(1), "audio/wav");
		UUID job = criada.job();
		var stream = abrirStream(job);
		try {
			stream.aguardarBloco("\"status\":\"aguardando_transcricao\"", Duration.ofSeconds(10));

			processador.processarPendentes();

			assertThat(status(job)).isEqualTo("erro");
			assertThat(trabalho(job)).containsEntry("estado", "falhou").containsEntry("reservado_ate", null);
			assertThat(dono.queryForMap("SELECT transcricao, transcrito_em FROM submissoes WHERE id = ?", criada.id()))
				.containsEntry("transcricao", null)
				.containsEntry("transcrito_em", null);
			assertThat(contar("outbox_events WHERE tipo = 'regra-submetida'")).isZero();
			assertThat(dono.queryForObject(
					"SELECT motivo FROM job_transicoes WHERE job_id = ? ORDER BY ocorrido_em DESC LIMIT 1",
					String.class, job))
				.isEqualTo("erro_transcricao");

			JsonNode estado = estadoDoStream(stream.aguardarBloco("\"status\":\"erro\"", Duration.ofSeconds(10)));
			assertThat(estado.path("motivo").asString()).isEqualTo(MOTIVO);
			assertThat(consultar(job).path("motivo").asString()).isEqualTo(MOTIVO);
			stream.aguardarFimDoStream(Duration.ofSeconds(10));
		}
		finally {
			stream.fechar();
		}
	}

	@Test
	void jobCanceladoDuranteAChamadaDescartaOTrabalhoSemGravarNada() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		UUID job = criada.job();
		DURANTE_A_CHAMADA.set(() -> cancelar(job));

		processador.processarPendentes();

		assertThat(status(job)).isEqualTo("cancelado");
		assertThat(trabalho(job)).containsEntry("estado", "descartado").containsEntry("tentativas", 1);
		assertThat(dono.queryForMap("SELECT transcricao, transcrito_em FROM submissoes WHERE id = ?", criada.id()))
			.containsEntry("transcricao", null)
			.containsEntry("transcrito_em", null);
		assertThat(contar("outbox_events WHERE tipo = 'regra-submetida'")).isZero();
	}

	@Test
	void falhaAoEncerrarOTrabalhoDesfazTextoEstadoEEventoJuntos() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		UUID job = criada.job();
		var stream = abrirStream(job);
		dono.execute(
				"CREATE FUNCTION falhar_t232() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''falha induzida''; END'");
		dono.execute(
				"CREATE TRIGGER falhar_t232 BEFORE UPDATE ON trabalhos_transcricao FOR EACH ROW WHEN (NEW.estado = 'concluido') EXECUTE FUNCTION falhar_t232()");
		try {
			stream.aguardarBloco("\"status\":\"aguardando_transcricao\"", Duration.ofSeconds(10));

			processador.processarPendentes();

			assertThat(status(job)).isEqualTo("aguardando_transcricao");
			assertThat(
					dono.queryForObject("SELECT transcricao FROM submissoes WHERE id = ?", String.class, criada.id()))
				.isNull();
			assertThat(contar("outbox_events")).isZero();
			assertThat(trabalho(job)).containsEntry("estado", "em_andamento");
			assertThat(stream.conteudo()).doesNotContain("gerando_regra", "erro");
		}
		finally {
			dono.execute("DROP TRIGGER falhar_t232 ON trabalhos_transcricao");
			dono.execute("DROP FUNCTION falhar_t232()");
			stream.fechar();
		}
	}

	@Test
	void chamadaAoProvedorAconteceSemTransacaoAbertaNemConexaoRetida() throws Exception {
		criarVoz(wav(1), "audio/wav");
		var pendentes = new AtomicReference<List<String>>(List.of());
		var ativas = new AtomicInteger(-1);
		var pool = (HikariDataSource) contexto.getBean(javax.sql.DataSource.class);
		DURANTE_A_CHAMADA.set(() -> {
			pendentes.set(dono.queryForList(
					"SELECT state FROM pg_stat_activity WHERE usename = 'synapse_api' AND state LIKE 'idle in transaction%'",
					String.class));
			ativas.set(Objects.requireNonNull(pool.getHikariPoolMXBean()).getActiveConnections());
		});

		processador.processarPendentes();

		assertThat(pendentes.get()).as("nenhuma transação aberta enquanto o provedor responde").isEmpty();
		assertThat(ativas.get()).as("a conexão volta ao pool antes da chamada").isZero();
	}

	@Test
	void doisProcessadoresConcorrentesTranscrevemOTrabalhoUmaVezSo() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		var liberar = new CountDownLatch(1);
		var chegou = new CountDownLatch(1);
		DURANTE_A_CHAMADA.set(() -> {
			chegou.countDown();
			try {
				assertThat(liberar.await(10, TimeUnit.SECONDS)).isTrue();
			}
			catch (InterruptedException ex) {
				Thread.currentThread().interrupt();
			}
		});
		var executor = Executors.newFixedThreadPool(2);
		try {
			var primeiro = executor.submit(() -> processador.processarPendentes());
			assertThat(chegou.await(10, TimeUnit.SECONDS)).as("o primeiro ciclo reservou e chamou").isTrue();
			var segundo = executor.submit(() -> processador.processarPendentes());
			// O segundo ciclo não encontra trabalho elegível e termina sem chamar nada.
			segundo.get(10, TimeUnit.SECONDS);
			liberar.countDown();
			primeiro.get(10, TimeUnit.SECONDS);
		}
		finally {
			executor.shutdownNow();
		}

		assertThat(CHAMADAS.get()).isEqualTo(1);
		assertThat(trabalho(criada.job())).containsEntry("estado", "concluido").containsEntry("tentativas", 1);
		assertThat(contar("outbox_events WHERE tipo = 'regra-submetida'")).isEqualTo(1);
	}

	@Test
	void reservaVencidaVoltaAoCicloEAVigenteNaoEhTocada() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		UUID job = criada.job();
		dono.update(
				"UPDATE trabalhos_transcricao SET estado = 'em_andamento', tentativas = 1, reservado_ate = now() + interval '1 hour'");

		processador.processarPendentes();

		assertThat(CHAMADAS.get()).as("reserva vigente de outra instância não é tocada").isZero();
		assertThat(trabalho(job)).containsEntry("tentativas", 1).containsEntry("estado", "em_andamento");

		dono.update("UPDATE trabalhos_transcricao SET reservado_ate = now() - interval '1 second'");
		try (var logs = new CapturaDeLog(ProcessadorTranscricao.class)) {
			processador.processarPendentes();
			assertThat(logs.eventos().stream().map(CapturaDeLog::emJson))
				.anySatisfy(linha -> assertThat(linha).contains("reserva vencida de transcrição recuperada"));
		}
		assertThat(CHAMADAS.get()).isEqualTo(1);
		assertThat(trabalho(job)).containsEntry("estado", "concluido").containsEntry("tentativas", 2);
		assertThat(status(job)).isEqualTo("gerando_regra");
	}

	@Test
	void reservaRetomadaPorOutraInstanciaDescartaOResultado() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		UUID job = criada.job();
		// Enquanto o provedor responde, outra instância retoma a reserva vencida: a
		// contagem de tentativas muda e este resultado não pode ser gravado.
		DURANTE_A_CHAMADA.set(() -> dono.update("UPDATE trabalhos_transcricao SET tentativas = tentativas + 1"));

		processador.processarPendentes();

		assertThat(status(job)).isEqualTo("aguardando_transcricao");
		assertThat(dono.queryForObject("SELECT transcricao FROM submissoes WHERE id = ?", String.class, criada.id()))
			.isNull();
		assertThat(contar("outbox_events")).isZero();
		assertThat(trabalho(job)).containsEntry("estado", "em_andamento").containsEntry("tentativas", 2);
	}

	@Test
	void logsDeDoisJobsSeguidosNaoCompartilhamCorrelacaoNemConteudo() throws Exception {
		var primeiro = criarVoz(wav(1), "audio/wav");
		var segundo = criarVoz(wav(1), "audio/wav");
		try (var logs = new CapturaDeLog(ProcessadorTranscricao.class);
				var todosOsLogs = new CapturaDeLog(org.slf4j.Logger.ROOT_LOGGER_NAME)) {
			processador.processarPendentes();

			var linhas = logs.eventos().stream().map(CapturaDeLog::emJson).toList();
			for (String linha : linhas) {
				ContratoDeEvento.validarLog(linha);
			}
			assertThat(linhas).filteredOn(linha -> linha.contains(primeiro.job().toString()))
				.as("cada log carrega só o job do seu trabalho")
				.allSatisfy(linha -> assertThat(linha).doesNotContain(segundo.job().toString()));
			assertThat(linhas).filteredOn(linha -> linha.contains(segundo.job().toString()))
				.allSatisfy(linha -> assertThat(linha).doesNotContain(primeiro.job().toString()));
			assertThat(linhas).filteredOn(linha -> linha.contains("transcrição processada")).hasSize(2);
			for (var evento : todosOsLogs.eventos()) {
				assertThat(CapturaDeLog.emJson(evento)).doesNotContain(TEXTO, "RIFF", "OggS", CHAVE);
			}
		}
		assertThat(status(primeiro.job())).isEqualTo("gerando_regra");
		assertThat(status(segundo.job())).isEqualTo("gerando_regra");
	}

	@Test
	void metricasDoProcessamentoAparecemNoScrapeDepoisDeSucessoFalhaEDescarte() throws Exception {
		var antes = metricas();

		criarVoz(wav(1), "audio/wav");
		processador.processarPendentes();

		STATUS.set(400);
		criarVoz(wav(1), "audio/wav");
		processador.processarPendentes();

		STATUS.set(200);
		var descartado = criarVoz(wav(1), "audio/wav");
		DURANTE_A_CHAMADA.set(() -> cancelar(descartado.job()));
		processador.processarPendentes();

		String depois = metricas();
		assertThat(depois).contains("transcricao_trabalhos_total{resultado=\"concluida\"}")
			.contains("transcricao_trabalhos_total{resultado=\"falhou_permanente\"}")
			.contains("transcricao_trabalhos_total{resultado=\"descartada\"}")
			.contains("transcricao_chamada_seconds_count{resultado=\"concluida\"}")
			.contains("transcricao_chamada_seconds_count{resultado=\"falhou_permanente\"}")
			.contains("transcricao_espera_seconds_count");
		assertThat(amostra(depois, "transcricao_trabalhos_total{resultado=\"concluida\"}"))
			.isEqualTo(amostra(antes, "transcricao_trabalhos_total{resultado=\"concluida\"}") + 1);
		assertThat(amostra(depois, "transcricao_espera_seconds_count"))
			.as("três trabalhos esperaram na fila, nenhum deles recuperado")
			.isEqualTo(amostra(antes, "transcricao_espera_seconds_count") + 3);
		assertThat(amostra(depois, "transcricao_chamada_seconds_count{resultado=\"concluida\"}"))
			.as("a chamada do trabalho descartado também é medida")
			.isEqualTo(amostra(antes, "transcricao_chamada_seconds_count{resultado=\"concluida\"}") + 2);
	}

	@ParameterizedTest
	@ValueSource(strings = { "sem-chave", "com-chave" })
	void agendamentoSegueADisponibilidadeDoProvedor(String cenario) throws Exception {
		boolean comChave = cenario.equals("com-chave");
		try (var logs = new CapturaDeLog(ProcessadorTranscricaoConfig.class)) {
			var proprio = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
				.run("--server.port=0", "--app.keycloak.enabled=false", "--app.postgres.host=" + postgres.getHost(),
						"--app.postgres.port=" + postgres.getMappedPort(5432),
						"--app.postgres.database=" + postgres.getDatabaseName(),
						"--app.postgres.owner.user=" + postgres.getUsername(),
						"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
						"--app.postgres.password=senha-de-teste", "--spring.rabbitmq.dynamic=false",
						"--spring.rabbitmq.listener.simple.auto-startup=false",
						"--management.health.rabbit.enabled=false", "--management.health.db.enabled=false",
						"--app.outbox.enabled=false", "--app.transcription.api-key=" + (comChave ? CHAVE : ""),
						"--app.transcription.base-url=http://127.0.0.1:" + provedor.getAddress().getPort(),
						"--app.transcription.connect-timeout-ms=1000", "--app.transcription.read-timeout-ms=5000",
						"--app.transcription.processor.poll-interval=50ms",
						"--app.transcription.processor.reservation-timeout=30s");
			String outraBase = "http://localhost:" + proprio.getEnvironment().getProperty("local.server.port");
			try {
				var resposta = enviarVoz(outraBase, wav(1), "audio/wav");
				var avisos = logs.eventos()
					.stream()
					.map(CapturaDeLog::emJson)
					.filter(linha -> linha.contains("processador de transcrição desligado"))
					.toList();
				assertThat(avisos).as("a inicialização só avisa quando deixa de agendar o processador")
					.hasSize(comChave ? 0 : 1);
				if (!comChave) {
					assertThat(resposta.statusCode()).as("voz recusada sem o provedor").isEqualTo(409);
					// O texto continua aceito, e nenhum trabalho pendente é processado.
					var texto = HTTP.send(HttpRequest.newBuilder(URI.create(outraBase + "/submissoes"))
						.header("Content-Type", "application/json")
						.POST(HttpRequest.BodyPublishers
							.ofString("{\"finalidade\":\"entrada_inicial\",\"tipo\":\"texto\",\"texto\":\"regra\"}"))
						.build(), HttpResponse.BodyHandlers.ofString());
					assertThat(texto.statusCode()).isEqualTo(201);
					return;
				}
				UUID job = UUID.fromString(JSON.readTree(resposta.body()).path("job").path("id").asString());
				await().atMost(Duration.ofSeconds(20))
					.untilAsserted(() -> assertThat(status(job)).isEqualTo("gerando_regra"));
			}
			finally {
				proprio.close();
			}
		}
	}

	private static Submissao criarVoz(byte[] audio, String tipo) throws Exception {
		var resposta = enviarVoz(base, audio, tipo);
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(201);
		var json = JSON.readTree(resposta.body());
		return new Submissao(UUID.fromString(json.path("id").asString()),
				UUID.fromString(json.path("job").path("id").asString()));
	}

	private static HttpResponse<String> enviarVoz(String endereco, byte[] audio, String tipo) throws Exception {
		String limite = "----t232";
		var corpo = new ByteArrayOutputStream();
		corpo.write(("--" + limite + "\r\nContent-Disposition: form-data; name=\"parametros\"\r\n"
				+ "Content-Type: application/json\r\n\r\n" + PARAMETROS + "\r\n")
			.getBytes(StandardCharsets.UTF_8));
		corpo.write(("--" + limite + "\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"regra.bin\"\r\n"
				+ "Content-Type: " + tipo + "\r\n\r\n")
			.getBytes(StandardCharsets.UTF_8));
		corpo.write(audio);
		corpo.write(("\r\n--" + limite + "--\r\n").getBytes(StandardCharsets.UTF_8));
		return HTTP.send(HttpRequest.newBuilder(URI.create(endereco + "/submissoes"))
			.header("Content-Type", "multipart/form-data; boundary=" + limite)
			.POST(HttpRequest.BodyPublishers.ofByteArray(corpo.toByteArray()))
			.build(), HttpResponse.BodyHandlers.ofString());
	}

	/**
	 * WAV PCM mono 8 kHz 16 bits com a duração pedida. A api não decodifica o áudio - só
	 * confere a assinatura do contêiner e o tamanho -, então o conteúdo é silêncio; o que
	 * o teste exige é que o byte a byte chegue ao provedor como foi gravado.
	 */
	private static byte[] wav(int segundos) {
		int taxa = 8000;
		int dados = segundos * taxa * 2;
		var buffer = ByteBuffer.allocate(44 + dados).order(java.nio.ByteOrder.LITTLE_ENDIAN);
		buffer.put("RIFF".getBytes(StandardCharsets.US_ASCII)).putInt(36 + dados);
		buffer.put("WAVEfmt ".getBytes(StandardCharsets.US_ASCII)).putInt(16);
		buffer.putShort((short) 1).putShort((short) 1).putInt(taxa).putInt(taxa * 2);
		buffer.putShort((short) 2).putShort((short) 16);
		buffer.put("data".getBytes(StandardCharsets.US_ASCII)).putInt(dados);
		return buffer.array();
	}

	private static StreamCliente abrirStream(UUID job) throws Exception {
		return new StreamCliente(HTTP.send(HttpRequest.newBuilder(URI.create(base + "/jobs/" + job + "/events"))
			.header("Accept", "text/event-stream")
			.GET()
			.build(), HttpResponse.BodyHandlers.ofInputStream()));
	}

	private static void cancelar(UUID job) {
		try {
			var resposta = HTTP.send(HttpRequest.newBuilder(URI.create(base + "/jobs/" + job + "/actions"))
				.header("Content-Type", "application/json")
				.POST(HttpRequest.BodyPublishers.ofString("{\"acao\":\"cancelar\"}"))
				.build(), HttpResponse.BodyHandlers.ofString());
			assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		}
		catch (Exception ex) {
			throw new AssertionError(ex);
		}
	}

	private static JsonNode consultar(UUID job) throws Exception {
		var resposta = HTTP.send(HttpRequest.newBuilder(URI.create(base + "/jobs/" + job))
			.header("Accept", "application/json")
			.GET()
			.build(), HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("JobDetalhado", resposta.body());
		return JSON.readTree(resposta.body());
	}

	private static JsonNode estadoDoStream(String bloco) throws Exception {
		assertThat(bloco).contains("event:estado");
		Matcher dados = Pattern.compile("(?m)^data:(.*)$").matcher(bloco);
		assertThat(dados.find()).as("bloco sem linha data: %s", bloco).isTrue();
		ContratoDeEvento.validarEventoDoStream("estado", dados.group(1));
		return JSON.readTree(dados.group(1));
	}

	private static String metricas() throws Exception {
		return HTTP
			.send(HttpRequest.newBuilder(URI.create(base + "/metrics")).GET().build(),
					HttpResponse.BodyHandlers.ofString())
			.body();
	}

	private static double amostra(String scrape, String serie) {
		Matcher valor = Pattern.compile("(?m)^" + Pattern.quote(serie) + " (\\S+)$").matcher(scrape);
		return valor.find() ? Double.parseDouble(valor.group(1)) : 0;
	}

	private static String status(UUID job) {
		return Objects.requireNonNull(dono.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, job));
	}

	private static java.util.Map<String, Object> trabalho(UUID job) {
		return dono.queryForMap("SELECT * FROM trabalhos_transcricao WHERE job_id = ?", job);
	}

	private static int contar(String tabela) {
		return Objects.requireNonNull(dono.queryForObject("SELECT count(*) FROM " + tabela, Integer.class));
	}

	private record Submissao(UUID id, UUID job) {
	}

	private static ProcessadorTranscricao novoProcessador() {
		return novoProcessador(contexto.getBean(AppProperties.class));
	}

	private static ProcessadorTranscricao novoProcessador(AppProperties properties) {
		return new ProcessadorTranscricao(contexto.getBean(SubmissoesRepository.class),
				contexto.getBean(ClienteDeepgram.class), contexto.getBean(JobsDeSubmissoes.class),
				contexto.getBean(PlatformTransactionManager.class), contexto.getBean(CorrelationContext.class),
				contexto.getBean(AppMetrics.class), properties, relogio);
	}

	@Test
	void retomaSomenteNoHorarioEConcluiUmaUnicaVezMesmoComNovoProcessador() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		Instant inicio = Instant.now().plusSeconds(1).truncatedTo(java.time.temporal.ChronoUnit.MICROS);
		relogio.fixar(inicio);
		STATUS.set(503);
		processador.processarPendentes();
		assertThat(proxima(criada.job())).isEqualTo(inicio.plusSeconds(10));
		processador.encerrar();
		processador = novoProcessador();
		relogio.fixar(inicio.plusSeconds(10).minusNanos(1000));
		processador.processarPendentes();
		assertThat(CHAMADAS.get()).isEqualTo(1);
		STATUS.set(200);
		relogio.fixar(inicio.plusSeconds(10));
		processador.processarPendentes();
		processador.processarPendentes();
		assertThat(CHAMADAS.get()).isEqualTo(2);
		assertThat(trabalho(criada.job())).containsEntry("estado", "concluido")
			.containsEntry("tentativas", 2)
			.containsEntry("proxima_tentativa_em", null);
		assertThat(status(criada.job())).isEqualTo("gerando_regra");
		assertThat(contar("outbox_events WHERE tipo = 'regra-submetida'")).isEqualTo(1);
	}

	@Test
	void esperaCresceEOTerceiroErroEsgotaComLogsEMetricasReais() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		Instant inicio = Instant.now().plusSeconds(1).truncatedTo(java.time.temporal.ChronoUnit.MICROS);
		relogio.fixar(inicio);
		STATUS.set(503);
		String antes = metricas();
		try (var logs = new CapturaDeLog(ProcessadorTranscricao.class)) {
			processador.processarPendentes();
			assertThat(proxima(criada.job())).isEqualTo(inicio.plusSeconds(10));
			relogio.fixar(proxima(criada.job()));
			processador.processarPendentes();
			assertThat(proxima(criada.job())).isEqualTo(inicio.plusSeconds(40));
			assertThat(status(criada.job())).isEqualTo("aguardando_transcricao");
			relogio.fixar(proxima(criada.job()));
			processador.processarPendentes();
			var linhas = logs.eventos().stream().map(CapturaDeLog::emJson).toList();
			for (String linha : linhas) {
				ContratoDeEvento.validarLog(linha);
				assertThat(linha).contains(criada.job().toString()).doesNotContain(TEXTO, CHAVE, "RIFF");
			}
			assertThat(linhas).anySatisfy(
					linha -> assertThat(linha).contains("nova_tentativa", "proxima_tentativa_em", "tentativas"));
			assertThat(linhas).anySatisfy(linha -> assertThat(linha).contains("esgotado", "transitoria"));
		}
		assertThat(CHAMADAS.get()).isEqualTo(3);
		assertThat(trabalho(criada.job())).containsEntry("estado", "falhou")
			.containsEntry("tentativas", 3)
			.containsEntry("proxima_tentativa_em", null);
		assertThat(status(criada.job())).isEqualTo("erro");
		assertThat(dono.queryForObject(
				"SELECT motivo FROM job_transicoes WHERE job_id = ? ORDER BY ocorrido_em DESC LIMIT 1", String.class,
				criada.job()))
			.isEqualTo("erro_transcricao");
		String depois = metricas();
		for (String resultado : List.of("nova_tentativa", "esgotado")) {
			String serie = "transcricao_trabalhos_total{resultado=\"" + resultado + "\"}";
			assertThat(amostra(depois, serie))
				.isEqualTo(amostra(antes, serie) + (resultado.equals("nova_tentativa") ? 2 : 1));
			assertThat(contexto.getBean(io.micrometer.core.instrument.MeterRegistry.class)
				.get("transcricao.trabalhos")
				.tag("resultado", resultado)
				.counter()
				.count()).isEqualTo(amostra(depois, serie));
		}
		assertThat(amostra(depois, "transcricao_trabalhos_total{resultado=\"concluida\"}"))
			.isEqualTo(amostra(antes, "transcricao_trabalhos_total{resultado=\"concluida\"}"));
	}

	@Test
	void limiteDeTaxaRespeitaPrazoMaiorQueOTetoLocalSemGastarTentativas() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		Instant inicio = Instant.now().plusSeconds(1).truncatedTo(java.time.temporal.ChronoUnit.MICROS);
		relogio.fixar(inicio);
		STATUS.set(429);
		RETRY_AFTER.set("900");
		processador.processarPendentes();
		assertThat(proxima(criada.job())).isEqualTo(inicio.plusSeconds(900));
		relogio.fixar(inicio.plusSeconds(899));
		processador.processarPendentes();
		assertThat(CHAMADAS.get()).isEqualTo(1);
		assertThat(trabalho(criada.job())).containsEntry("tentativas", 1);
		relogio.fixar(inicio.plusSeconds(900));
		STATUS.set(200);
		processador.processarPendentes();
		assertThat(trabalho(criada.job())).containsEntry("estado", "concluido").containsEntry("tentativas", 2);
	}

	@Test
	void ultimaReservaVencidaEsgotaSemUmaQuartaChamada() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		dono.update(
				"UPDATE trabalhos_transcricao SET estado = 'em_andamento', tentativas = 3, reservado_ate = now() - interval '1 second'");
		processador.processarPendentes();
		assertThat(CHAMADAS.get()).isZero();
		assertThat(trabalho(criada.job())).containsEntry("estado", "falhou").containsEntry("tentativas", 3);
		assertThat(status(criada.job())).isEqualTo("erro");
	}

	@Test
	void segundaRespostaInvalidaEhPermanenteMesmoAposReiniciar() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		RESPOSTA_INVALIDA.set(true);
		processador.processarPendentes();
		assertThat(trabalho(criada.job())).containsEntry("resposta_invalida", true).containsEntry("estado", "pendente");
		processador.encerrar();
		processador = novoProcessador();
		relogio.fixar(proxima(criada.job()));
		processador.processarPendentes();
		assertThat(CHAMADAS.get()).isEqualTo(2);
		assertThat(trabalho(criada.job())).containsEntry("estado", "falhou").containsEntry("tentativas", 2);
		assertThat(status(criada.job())).isEqualTo("erro");
	}

	@Test
	void limitePorInstanciaNaoBloqueiaOPollerEDrenaAFila() throws Exception {
		for (int i = 0; i < 6; i++) {
			criarVoz(wav(1), "audio/wav");
		}
		var chegaram = new CountDownLatch(2);
		var liberar = new CountDownLatch(1);
		var ativas = new AtomicInteger();
		var pico = new AtomicInteger();
		DURANTE_A_CHAMADA.set(() -> {
			int atual = ativas.incrementAndGet();
			pico.accumulateAndGet(atual, Math::max);
			chegaram.countDown();
			try {
				assertThat(liberar.await(15, TimeUnit.SECONDS)).isTrue();
			}
			catch (InterruptedException ex) {
				Thread.currentThread().interrupt();
			}
			finally {
				ativas.decrementAndGet();
			}
		});
		try (var logs = new CapturaDeLog(ProcessadorTranscricao.class)) {
			processador.agendarPendentes();
			assertThat(chegaram.await(10, TimeUnit.SECONDS)).isTrue();
			for (int i = 0; i < 10; i++) {
				processador.agendarPendentes();
				processador.processarPendentes();
			}
			assertThat(CHAMADAS.get()).isEqualTo(2);
			liberar.countDown();
			await().atMost(Duration.ofSeconds(20))
				.untilAsserted(
						() -> assertThat(contar("trabalhos_transcricao WHERE estado = 'concluido'")).isEqualTo(6));
			await().atMost(Duration.ofSeconds(5))
				.untilAsserted(() -> assertThat(logs.eventos()
					.stream()
					.filter(evento -> evento.getFormattedMessage().equals("transcrição processada"))
					.count()).isEqualTo(6));
			assertThat(pico.get()).isEqualTo(2);
			assertThat(CHAMADAS.get()).isEqualTo(6);
			for (var evento : logs.eventos()) {
				String linha = CapturaDeLog.emJson(evento);
				ContratoDeEvento.validarLog(linha);
				assertThat(linha).doesNotContain(TEXTO, CHAVE, "RIFF");
				var eventoJson = JSON.readTree(linha);
				UUID trabalhoId = UUID.fromString(eventoJson.path("extra").path("trabalho_id").asString());
				String jobEsperado = Objects.requireNonNull(dono.queryForObject(
						"SELECT job_id::text FROM trabalhos_transcricao WHERE id = ?", String.class, trabalhoId));
				assertThat(eventoJson.path("job_id").asString()).isEqualTo(jobEsperado);
			}
		}
		finally {
			liberar.countDown();
		}
	}

	private static Instant proxima(UUID job) {
		return ((java.sql.Timestamp) Objects.requireNonNull(trabalho(job).get("proxima_tentativa_em"))).toInstant();
	}

	@Test
	void tetoEQuantidadeDeTentativasSaoConfiguraveis() throws Exception {
		var properties = contexto.getBean(AppProperties.class);
		var transcription = properties.transcription();
		var processor = new AppProperties.Transcription.Processor(false, Duration.ofSeconds(1), Duration.ofSeconds(30),
				4, Duration.ofSeconds(10), 3, Duration.ofSeconds(15), 2);
		var configuracao = new AppProperties(properties.environment(), properties.service(), properties.cors(),
				properties.observability(), properties.postgres(), properties.rabbitmq(), properties.sse(),
				properties.outbox(), properties.keycloak(),
				new AppProperties.Transcription(transcription.apiKey(), transcription.baseUrl(),
						transcription.connectTimeoutMs(), transcription.readTimeoutMs(), processor));
		processador.encerrar();
		processador = novoProcessador(configuracao);
		var criada = criarVoz(wav(1), "audio/wav");
		Instant inicio = Instant.now().plusSeconds(1).truncatedTo(java.time.temporal.ChronoUnit.MICROS);
		relogio.fixar(inicio);
		STATUS.set(503);
		for (long segundos : new long[] { 10, 25, 40 }) {
			processador.processarPendentes();
			assertThat(proxima(criada.job())).isEqualTo(inicio.plusSeconds(segundos));
			relogio.fixar(proxima(criada.job()));
		}
		processador.processarPendentes();
		assertThat(CHAMADAS.get()).isEqualTo(4);
		assertThat(status(criada.job())).isEqualTo("erro");
	}

	@Test
	void falhaTransitoriaDeJobCanceladoNaoReagenda() throws Exception {
		var criada = criarVoz(wav(1), "audio/wav");
		STATUS.set(503);
		DURANTE_A_CHAMADA.set(() -> cancelar(criada.job()));
		processador.processarPendentes();
		assertThat(status(criada.job())).isEqualTo("cancelado");
		assertThat(trabalho(criada.job())).containsEntry("estado", "descartado")
			.containsEntry("proxima_tentativa_em", null);
	}

	private static final class RelogioControlado extends Clock {

		private volatile @Nullable Instant fixo;

		void fixar(Instant instante) {
			this.fixo = instante;
		}

		@Override
		public ZoneId getZone() {
			return java.time.ZoneOffset.UTC;
		}

		@Override
		public Clock withZone(ZoneId zona) {
			return this;
		}

		@Override
		public Instant instant() {
			Instant instante = this.fixo;
			return instante == null ? Instant.now() : instante;
		}

	}

}
