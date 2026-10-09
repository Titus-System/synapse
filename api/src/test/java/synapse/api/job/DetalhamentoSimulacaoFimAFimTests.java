package synapse.api.job;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import ch.qos.logback.classic.spi.ILoggingEvent;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import synapse.api.ApiApplication;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * Sobe a aplicação inteira contra um Postgres real e consulta o detalhamento por HTTP de
 * verdade. Os artefatos entram como o codegen e o worker os gravam: a simulação ainda sem
 * resultado e, depois, o resultado com o detalhamento no mesmo {@code INSERT}. Cada
 * resposta é conferida contra o contrato, cada log contra o envelope, e a série
 * {@code http_server_requests_seconds} da rota em {@code /metrics}.
 */
@EnabledIf("dockerIsAvailable")
class DetalhamentoSimulacaoFimAFimTests {

	private static final String ROTA = "/jobs/{id}/simulacoes/{simulacaoId}/linhas";

	private static final String LOGGER = "synapse.api.job.BuscarJobService";

	private static final UUID USUARIO = UUID.fromString("66666666-6666-4666-8666-666666666666");

	private static final UUID OUTRO_USUARIO = UUID.fromString("77777777-7777-4777-8777-777777777777");

	private static final String TOTAIS = """
			{"baseline":480000.00,"simulado":484226.40,"diferenca_abs":4226.40,"diferenca_pct":0.0088,"orcamento":485000.00}
			""";

	private static final String DECOMPOSICAO = """
			{"elemento":{"nucleo.percentual":4226.40},"loja":{"13":4226.40},"marca":{"10":4226.40},
			 "cargo":{"100":4226.40},"competencia":{"2025-11":4226.40}}
			""";

	private static final String ASSERCOES = "[{\"nome\":\"sem_comissao_negativa\",\"resultado\":\"ok\",\"detalhe\":null}]";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = new JsonMapper();

	private static PostgreSQLContainer postgres;

	private static ConfigurableApplicationContext contexto;

	private static JdbcTemplate dono;

	private static int porta;

	private static String linhas;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void subirAplicacao() throws IOException {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		// O log da consulta atendida é DEBUG; o teste o liga para conferir o que ele
		// leva.
		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
					"--app.postgres.password=senha-de-teste", "--spring.rabbitmq.dynamic=false",
					"--spring.rabbitmq.listener.simple.auto-startup=false", "--management.health.rabbit.enabled=false",
					"--management.health.db.enabled=false", "--app.outbox.enabled=false",
					"--logging.level." + LOGGER + "=DEBUG");
		porta = Integer.parseInt(Objects.requireNonNull(contexto.getEnvironment().getProperty("local.server.port")));
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		// Sem Keycloak, a requisição age como o primeiro usuário ativo.
		dono.update("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES (?, 'rh', 'x', 'RH', 'profissional_rh', '2026-01-01T00:00:00Z'),
				       (?, 'outro-rh', 'x', 'Outro RH', 'profissional_rh', '2026-01-02T00:00:00Z')
				""", USUARIO, OUTRO_USUARIO);
		linhas = Files.readString(exemplo("domain/resultado-linhas.json"));
	}

	@AfterAll
	static void derrubarTudo() {
		if (contexto != null) {
			contexto.close();
		}
		if (postgres != null) {
			postgres.stop();
		}
	}

	@Test
	void devolveODetalhamentoIgualAoGravado() throws Exception {
		Simulacao simulacao = criarSimulacao(criarJob(USUARIO));
		gravarResultado(simulacao, "sucesso", linhas);

		HttpResponse<String> resposta = consultar(simulacao.jobId(), simulacao.id());

		assertThat(resposta.statusCode()).isEqualTo(200);
		assertThat(resposta.headers().firstValue("Content-Type"))
			.hasValueSatisfying((tipo) -> assertThat(tipo).startsWith("application/json"));
		ContratoDeEvento.validarRespostaHttp("DetalhamentoSimulacao", resposta.body());
		JsonNode corpo = JSON.readTree(resposta.body());
		assertThat(corpo.path("simulacao_id").asString()).isEqualTo(simulacao.id().toString());
		assertThat(corpo.path("linhas")).isEqualTo(JSON.readTree(linhasGravadas(simulacao)));
		assertThat(corpo.path("linhas").propertyNames()).containsExactlyInAnyOrder("2025-08", "2025-11");
	}

	@ParameterizedTest
	@ValueSource(strings = { "sem_resultado", "sucesso_anterior_ao_detalhamento", "erro_codigo" })
	void simulacaoSemDetalhamentoResponde200SemLinhas(String caso) throws Exception {
		Simulacao simulacao = criarSimulacao(criarJob(USUARIO));
		switch (caso) {
			case "sucesso_anterior_ao_detalhamento" -> gravarResultado(simulacao, "sucesso", null);
			case "erro_codigo" -> gravarResultado(simulacao, "erro_codigo", null);
			default -> {
			}
		}

		try (CapturaDeLog captura = new CapturaDeLog(LOGGER)) {
			HttpResponse<String> resposta = consultar(simulacao.jobId(), simulacao.id());

			assertThat(resposta.statusCode()).isEqualTo(200);
			ContratoDeEvento.validarRespostaHttp("DetalhamentoSimulacao", resposta.body());
			JsonNode corpo = JSON.readTree(resposta.body());
			assertThat(corpo.propertyNames()).containsExactly("simulacao_id");
			assertThat(corpo.path("simulacao_id").asString()).isEqualTo(simulacao.id().toString());
			JsonNode log = unicoLog(captura, "DEBUG");
			assertThat(log.path("message").asString()).isEqualTo("detalhamento da simulação consultado");
			assertThat(log.path("extra").path("com_detalhamento").asBoolean()).isFalse();
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "inexistente", "de_outro_job" })
	void simulacaoQueNaoPertenceAoJobResponde404ELogaARecusa(String caso) throws Exception {
		Simulacao propria = criarSimulacao(criarJob(USUARIO));
		gravarResultado(propria, "sucesso", linhas);
		UUID simulacaoId = UUID.randomUUID();
		if (caso.equals("de_outro_job")) {
			Simulacao deOutroJob = criarSimulacao(criarJob(USUARIO));
			gravarResultado(deOutroJob, "sucesso", linhas);
			simulacaoId = deOutroJob.id();
		}

		try (CapturaDeLog captura = new CapturaDeLog(LOGGER)) {
			HttpResponse<String> resposta = consultar(propria.jobId(), simulacaoId);

			assertThat(resposta.statusCode()).isEqualTo(404);
			ContratoDeEvento.validarRespostaHttp("Erro", resposta.body());
			assertThat(codigo(resposta)).isEqualTo("simulacao_nao_encontrada");
			assertThat(resposta.body()).doesNotContain("MATRIC");
			JsonNode log = unicoLog(captura, "WARN");
			assertThat(log.path("message").asString())
				.isEqualTo("detalhamento recusado: simulação não encontrada no job");
			assertThat(log.path("job_id").asString()).isEqualTo(propria.jobId().toString());
			assertThat(log.path("extra").path("simulacao_id").asString()).isEqualTo(simulacaoId.toString());
		}
	}

	@Test
	void jobDeOutroUsuarioEJobInexistenteSaoRecusadosComoNasOutrasRotas() throws Exception {
		Simulacao alheia = criarSimulacao(criarJob(OUTRO_USUARIO));
		gravarResultado(alheia, "sucesso", linhas);

		HttpResponse<String> semPosse = consultar(alheia.jobId(), alheia.id());
		HttpResponse<String> inexistente = consultar(UUID.randomUUID(), alheia.id());

		assertThat(semPosse.statusCode()).isEqualTo(403);
		ContratoDeEvento.validarRespostaHttp("Erro", semPosse.body());
		assertThat(codigo(semPosse)).isEqualTo("sem_permissao");
		assertThat(semPosse.body()).doesNotContain("MATRIC");
		assertThat(inexistente.statusCode()).isEqualTo(404);
		ContratoDeEvento.validarRespostaHttp("Erro", inexistente.body());
		assertThat(codigo(inexistente)).isEqualTo("job_nao_encontrado");
	}

	@Test
	void consultaAtendidaLogaAsReferenciasSemOConteudo() throws Exception {
		Simulacao simulacao = criarSimulacao(criarJob(USUARIO));
		gravarResultado(simulacao, "sucesso", linhas);

		try (CapturaDeLog captura = new CapturaDeLog(LOGGER)) {
			assertThat(consultar(simulacao.jobId(), simulacao.id()).statusCode()).isEqualTo(200);

			String linha = CapturaDeLog.emJson(unicoEvento(captura));
			JsonNode log = JSON.readTree(linha);
			assertThat(log.path("level").asString()).isEqualTo("DEBUG");
			assertThat(log.path("logger").asString()).isEqualTo(LOGGER);
			assertThat(log.path("service.name").asString()).isEqualTo("synapse-api");
			assertThat(log.path("message").asString()).isEqualTo("detalhamento da simulação consultado");
			assertThat(log.path("job_id").asString()).isEqualTo(simulacao.jobId().toString());
			assertThat(log.path("extra").path("simulacao_id").asString()).isEqualTo(simulacao.id().toString());
			assertThat(log.path("extra").path("com_detalhamento").asBoolean()).isTrue();
			assertThat(linha).doesNotContain("MATRIC", "comissao", "contribuicoes", "2025-08");
		}
	}

	@Test
	void serieHttpDaRotaContaAsConsultasAtendidasERecusadas() throws Exception {
		Simulacao simulacao = criarSimulacao(criarJob(USUARIO));
		gravarResultado(simulacao, "sucesso", linhas);
		for (String status : List.of("200", "404")) {
			long contagemAntes = contagem(status);
			double duracaoAntes = duracao(status);
			UUID simulacaoId = status.equals("200") ? simulacao.id() : UUID.randomUUID();

			assertThat(consultar(simulacao.jobId(), simulacaoId).statusCode()).isEqualTo(Integer.parseInt(status));

			await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> {
				assertThat(contagem(status)).isEqualTo(contagemAntes + 1);
				assertThat(duracao(status)).isGreaterThan(duracaoAntes);
				HttpResponse<String> metricas = get("/metrics");
				assertThat(metricas.statusCode()).isEqualTo(200);
				List<String> contagens = amostras(metricas.body(), "http_server_requests_seconds_count{", status);
				List<String> duracoes = amostras(metricas.body(), "http_server_requests_seconds_sum{", status);
				assertThat(soma(contagens)).isEqualTo((double) (contagemAntes + 1));
				assertThat(soma(duracoes)).isGreaterThan(duracaoAntes);
				assertThat(String.join("\n", contagens) + String.join("\n", duracoes))
					.doesNotContain(simulacao.jobId().toString(), simulacaoId.toString());
			});
		}
	}

	// --- Apoio ----------------------------------------------------------------------

	private record Simulacao(UUID jobId, UUID id, UUID codigoGeradoId) {
	}

	private static UUID criarJob(UUID usuarioId) {
		return Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO jobs (status, usuario_id, competencias, orcamento, criado_em)
				VALUES ('aguardando_decisao_usuario', ?, '{2025-08,2025-11}', 485000, now()) RETURNING id
				""", UUID.class, usuarioId));
	}

	/**
	 * O que o codegen deixa ao gerar o código: a regra, o código e a simulação sem
	 * resultado.
	 */
	private static Simulacao criarSimulacao(UUID jobId) {
		UUID regra = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES (?, 1, 'confirmacao_usuario', '{"percentual":0.02}'::jsonb, '[]'::jsonb, ?, now()) RETURNING id
				""", UUID.class, jobId, "a".repeat(64)));
		UUID prompt = UUID.randomUUID();
		UUID codigo = UUID.randomUUID();
		dono.update("""
				INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
				VALUES (?, ?, 'geracao_codigo', 'fixture', '{}'::jsonb, now())
				""", prompt, jobId);
		dono.update("""
				INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES (?, ?, ?, 'python', 'fixture', ?, now())
				""", codigo, jobId, regra, prompt);
		UUID simulacao = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO simulacoes (criado_em, regra_id, job_id, codigo_gerado_id)
				VALUES (now(), ?, ?, ?) RETURNING id
				""", UUID.class, regra, jobId, codigo));
		return new Simulacao(jobId, simulacao, codigo);
	}

	/**
	 * O que o worker grava: o resultado com o detalhamento no mesmo {@code INSERT}.
	 * Depois a simulação passa a apontar para ele, como a api faz ao aplicar o
	 * {@code simulacao-concluida}.
	 */
	private static void gravarResultado(Simulacao simulacao, String status, @Nullable String detalhamento) {
		boolean sucesso = status.equals("sucesso");
		UUID resultado = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, totais, veredito, assercoes,
				                                  decomposicao, linhas, criado_em)
				VALUES (?, ?, ?, ?::jsonb, ?, ?::jsonb, ?::jsonb, ?::jsonb, now()) RETURNING id
				""", UUID.class, simulacao.jobId(), simulacao.codigoGeradoId(), status, sucesso ? TOTAIS : null,
				sucesso ? "viavel" : null, ASSERCOES, sucesso ? DECOMPOSICAO : null, detalhamento));
		dono.update("UPDATE simulacoes SET resultado_id = ? WHERE id = ?", resultado, simulacao.id());
	}

	private static String linhasGravadas(Simulacao simulacao) {
		return Objects.requireNonNull(dono.queryForObject("""
				SELECT r.linhas FROM simulacoes s JOIN resultados_simulacao r ON r.id = s.resultado_id
				WHERE s.id = ?
				""", String.class, simulacao.id()));
	}

	private static HttpResponse<String> consultar(UUID jobId, UUID simulacaoId)
			throws IOException, InterruptedException {
		return get("/jobs/" + jobId + "/simulacoes/" + simulacaoId + "/linhas");
	}

	private static HttpResponse<String> get(String caminho) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest.newBuilder(URI.create("http://localhost:" + porta + caminho))
			.GET()
			.build();
		return HTTP.send(requisicao, HttpResponse.BodyHandlers.ofString());
	}

	private static String codigo(HttpResponse<String> resposta) {
		return JSON.readTree(resposta.body()).path("codigo").asString();
	}

	private static ILoggingEvent unicoEvento(CapturaDeLog captura) {
		assertThat(captura.eventos()).hasSize(1);
		return captura.eventos().getFirst();
	}

	/** O único log capturado, já conferido contra o envelope e no nível esperado. */
	private static JsonNode unicoLog(CapturaDeLog captura, String nivel) throws IOException {
		String linha = CapturaDeLog.emJson(unicoEvento(captura));
		ContratoDeEvento.validarLog(linha);
		JsonNode log = JSON.readTree(linha);
		assertThat(log.path("level").asString()).isEqualTo(nivel);
		return log;
	}

	private static List<Timer> timers(String status) {
		return List.copyOf(contexto.getBean(MeterRegistry.class)
			.find("http.server.requests")
			.tags("method", "GET", "uri", ROTA, "status", status)
			.timers());
	}

	private static long contagem(String status) {
		return timers(status).stream().mapToLong(Timer::count).sum();
	}

	private static double duracao(String status) {
		return timers(status).stream().mapToDouble((timer) -> timer.totalTime(TimeUnit.SECONDS)).sum();
	}

	/**
	 * As amostras da rota com o status pedido. Pode haver mais de uma série, separadas
	 * pela tag {@code exception}, quando outros testes já recusaram a rota por outro
	 * motivo.
	 */
	private static List<String> amostras(String metricas, String prefixo, String status) {
		List<String> amostras = metricas.lines()
			.filter((linha) -> linha.startsWith(prefixo))
			.filter((linha) -> linha.contains("uri=\"" + ROTA + "\"") && linha.contains("method=\"GET\"")
					&& linha.contains("status=\"" + status + "\""))
			.toList();
		assertThat(amostras).isNotEmpty();
		return amostras;
	}

	private static double soma(List<String> amostras) {
		return amostras.stream()
			.mapToDouble((amostra) -> Double.parseDouble(amostra.substring(amostra.indexOf("} ") + 2)))
			.sum();
	}

	private static Path exemplo(String caminhoRelativo) {
		Path diretorio = Path.of("").toAbsolutePath();
		while (diretorio != null) {
			Path exemplos = diretorio.resolve("contracts/examples");
			if (Files.isDirectory(exemplos)) {
				return exemplos.resolve(caminhoRelativo);
			}
			diretorio = diretorio.getParent();
		}
		throw new IllegalStateException("Diretório contracts/examples não encontrado a partir do diretório atual.");
	}

}
