package synapse.api.job;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

import synapse.api.ApiApplication;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * Sobe a aplicação inteira contra um Postgres real (Liquibase migra na subida) e conecta
 * por HTTP de verdade em {@code GET /jobs/{id}/events} - o que confirma o comportamento
 * observável pelo navegador, sem simular servlet nenhum. O comportamento interno de
 * {@link EmissoresSse} (fotografia sob a mesma trava do envio, remoção em cada callback)
 * está em {@code EmissoresSseTests}.
 */
@EnabledIf("dockerIsAvailable")
class AcompanharJobStreamTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "33333333-3333-4333-8333-333333333333";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static PostgreSQLContainer postgres;

	private static ConfigurableApplicationContext contexto;

	private static int porta;

	private static EmissoresSse emissoresSse;

	private final List<StreamCliente> abertos = new ArrayList<>();

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void subirAplicacao() throws Exception {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();

		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=" + USUARIO_API,
					"--app.postgres.password=" + SENHA, "--spring.rabbitmq.dynamic=false",
					"--spring.rabbitmq.listener.simple.auto-startup=false", "--management.health.rabbit.enabled=false",
					"--management.health.db.enabled=false", "--app.sse.heartbeat=200ms");

		porta = Integer.parseInt(Objects.requireNonNull(contexto.getEnvironment().getProperty("local.server.port")));
		emissoresSse = contexto.getBean(EmissoresSse.class);

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
	}

	@AfterEach
	void fecharStreamsAbertosEConferirQueNaoVazou() {
		for (StreamCliente cliente : this.abertos) {
			cliente.fechar();
		}
		this.abertos.clear();
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(emissoresSse.conexoesAtivas()).isZero());
	}

	// --- Cenários -----------------------------------------------------------------

	@Test
	void abreOStreamComAFotografiaDoEstadoAtual() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);

		StreamCliente cliente = conectar(jobId);

		assertThat(cliente.status()).isEqualTo(200);
		assertThat(cliente.cabecalho("Content-Type")).startsWith("text/event-stream");
		assertThat(cliente.cabecalho("Cache-Control")).isEqualTo("no-store");

		String bloco = cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		assertThat(bloco).contains("id:").contains("\"status\":\"gerando_regra\"").doesNotContain("status_anterior");
	}

	@Test
	void doisClientesNoMesmoJobRecebemOMesmoEventoComOMesmoId() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente a = conectar(jobId);
		StreamCliente b = conectar(jobId);
		a.aguardarBloco("event:estado", Duration.ofSeconds(5));
		b.aguardarBloco("event:estado", Duration.ofSeconds(5));

		emissoresSse.emitir(jobId, EventoSse.de("etapa", new EventoEstadoDto(jobId, "geracao_codigo", null, null)));

		String blocoA = a.aguardarBloco("event:etapa", Duration.ofSeconds(5));
		String blocoB = b.aguardarBloco("event:etapa", Duration.ofSeconds(5));
		assertThat(extrairId(blocoA)).isEqualTo(extrairId(blocoB));
	}

	@Test
	void idsCrescemASequencialmenteACadaEmissao() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		String fotografia = cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		int idFotografia = extrairId(fotografia);

		emissoresSse.emitir(jobId, EventoSse.de("etapa", new EventoEstadoDto(jobId, "geracao_codigo", null, null)));
		int idPrimeiraEtapa = extrairId(cliente.aguardarBloco("event:etapa", Duration.ofSeconds(5)));

		emissoresSse.emitir(jobId, EventoSse.de("etapa", new EventoEstadoDto(jobId, "delegacao_worker", null, null)));
		int idSegundaEtapa = extrairId(cliente.aguardarBloco("delegacao_worker", Duration.ofSeconds(5)));

		assertThat(idPrimeiraEtapa).isGreaterThan(idFotografia);
		assertThat(idSegundaEtapa).isGreaterThan(idPrimeiraEtapa);
	}

	@Test
	void desconectarUmClienteNaoAfetaOOutroNemOProcessamentoDoJob() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente a = conectar(jobId);
		StreamCliente b = conectar(jobId);
		a.aguardarBloco("event:estado", Duration.ofSeconds(5));
		b.aguardarBloco("event:estado", Duration.ofSeconds(5));
		assertThat(emissoresSse.conexoesAtivas()).isEqualTo(2);

		a.fechar();
		this.abertos.remove(a);
		await().atMost(Duration.ofSeconds(5))
			.untilAsserted(() -> assertThat(emissoresSse.conexoesAtivas()).isEqualTo(1));

		emissoresSse.emitir(jobId, EventoSse.de("etapa", new EventoEstadoDto(jobId, "geracao_codigo", null, null)));
		assertThat(b.aguardarBloco("event:etapa", Duration.ofSeconds(5))).contains("event:etapa");

		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(contarTransicoes(jobId)).isZero();
	}

	@Test
	void heartbeatChegaNoIntervaloConfigurado() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		await().atMost(Duration.ofSeconds(3))
			.untilAsserted(() -> assertThat(cliente.contarOcorrencias("heartbeat")).isGreaterThanOrEqualTo(2));
	}

	@Test
	void jobEmEstadoTerminalRecebeAFotografiaEFechaOStream() throws Exception {
		UUID jobId = criarJob(JobStatus.LIBERADO);

		StreamCliente cliente = conectar(jobId);

		String bloco = cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		assertThat(bloco).contains("\"status\":\"liberado\"");
		cliente.aguardarFimDoStream(Duration.ofSeconds(5));
		await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> assertThat(emissoresSse.conexoesAtivas()).isZero());
		this.abertos.remove(cliente);
	}

	@Test
	void eventoUltimoFechaTodosOsStreamsDoJob() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente a = conectar(jobId);
		StreamCliente b = conectar(jobId);
		a.aguardarBloco("event:estado", Duration.ofSeconds(5));
		b.aguardarBloco("event:estado", Duration.ofSeconds(5));

		emissoresSse.emitir(jobId,
				EventoSse.ultimo("estado", new EventoEstadoDto(jobId, "liberado", "simulando", null)));

		a.aguardarFimDoStream(Duration.ofSeconds(5));
		b.aguardarFimDoStream(Duration.ofSeconds(5));
		await().atMost(Duration.ofSeconds(5)).untilAsserted(() -> assertThat(emissoresSse.conexoesAtivas()).isZero());
		this.abertos.remove(a);
		this.abertos.remove(b);
	}

	@Test
	void jobInexistenteResponde404ComErroJson() throws Exception {
		UUID jobId = UUID.randomUUID();
		HttpRequest requisicao = HttpRequest.newBuilder(uri(jobId)).GET().build();

		HttpResponse<String> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofString());

		assertThat(resposta.statusCode()).isEqualTo(404);
		assertThat(resposta.body()).contains("job_nao_encontrado");
		assertThat(emissoresSse.conexoesAtivas()).isZero();
	}

	@Test
	void cemConexoesAbertasEFechadasNaoVazam() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		List<StreamCliente> clientes = new ArrayList<>();
		for (int i = 0; i < 100; i++) {
			StreamCliente cliente = conectar(jobId);
			cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
			clientes.add(cliente);
		}

		assertThat(emissoresSse.conexoesAtivas()).isEqualTo(100);

		for (StreamCliente cliente : clientes) {
			cliente.fechar();
		}
		this.abertos.removeAll(clientes);

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(emissoresSse.conexoesAtivas()).isZero());
	}

	// --- Apoio ----------------------------------------------------------------------

	private static URI uri(UUID jobId) {
		return URI.create("http://localhost:" + porta + "/jobs/" + jobId + "/events");
	}

	private StreamCliente conectar(UUID jobId) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest.newBuilder(uri(jobId)).GET().build();
		HttpResponse<InputStream> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofInputStream());
		StreamCliente cliente = new StreamCliente(resposta);
		this.abertos.add(cliente);
		return cliente;
	}

	private static int extrairId(String bloco) {
		Matcher matcher = Pattern.compile("id:(\\d+)").matcher(bloco);
		if (!matcher.find()) {
			throw new AssertionError("bloco sem id: " + bloco);
		}
		return Integer.parseInt(matcher.group(1));
	}

	private static UUID criarJob(JobStatus status) throws SQLException {
		UUID jobId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO jobs (id, status, usuario_id, competencias, orcamento, criado_em)
					VALUES ('%s', '%s', '%s', '{2025-08}', 1000, now())
					""".formatted(jobId, status.paraColuna(), USUARIO_ID));
		}
		return jobId;
	}

	private static String statusPersistido(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement.executeQuery("SELECT status FROM jobs WHERE id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getString("status");
		}
	}

	private static int contarTransicoes(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement
					.executeQuery("SELECT count(*) FROM job_transicoes WHERE job_id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getInt(1);
		}
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

}
