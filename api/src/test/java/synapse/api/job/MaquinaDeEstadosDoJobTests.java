package synapse.api.job;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import liquibase.Contexts;
import liquibase.Liquibase;
import liquibase.database.Database;
import liquibase.database.DatabaseFactory;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.ClassLoaderResourceAccessor;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;

/**
 * Roda contra um Postgres de verdade, como o usuário {@code synapse_api}: o que se afirma
 * é o que a máquina de estados alcança com a permissão real do serviço, não uma simulação
 * em memória.
 */
@EnabledIf("dockerIsAvailable")
class MaquinaDeEstadosDoJobTests {

	private static final String CHANGELOG = "db/changelog/changelog.yaml";

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "22222222-2222-4222-8222-222222222222";

	private static PostgreSQLContainer postgres;

	private static JdbcTemplate jdbcTemplate;

	private static MaquinaDeEstadosDoJob maquina;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void prepararOBanco() throws Exception {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();

		try (Connection connection = comoDono(); Liquibase liquibase = liquibase(connection)) {
			liquibase.update(new Contexts());
		}

		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("ALTER ROLE " + USUARIO_API + " WITH PASSWORD '" + SENHA + "'");
			statement.execute("""
					INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
					VALUES ('%s', 'rh', 'x', 'RH', 'profissional_rh', now())
					""".formatted(USUARIO_ID));
		}

		DriverManagerDataSource dataSource = new DriverManagerDataSource(postgres.getJdbcUrl(), USUARIO_API, SENHA);
		jdbcTemplate = new JdbcTemplate(dataSource);
		maquina = new MaquinaDeEstadosDoJob(jdbcTemplate);
	}

	@AfterAll
	static void derrubarOPostgres() {
		if (postgres != null) {
			postgres.stop();
		}
	}

	// --- Caminho feliz completo, de criação a liberado ------------------------------

	@Test
	void oCaminhoFelizVaiDaCriacaoALiberado() throws SQLException {
		UUID jobId = criarJob();

		maquina.registrarCriacao(jobId, "sistema");
		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "sistema", null);
		maquina.transicionar(jobId, JobStatus.SIMULANDO, "sistema", null);
		maquina.transicionar(jobId, JobStatus.AGUARDANDO_DECISAO_USUARIO, "sistema", null);
		maquina.transicionar(jobId, JobStatus.LIBERADO, "rh", "aprovado pelo usuário");

		assertThat(statusPersistido(jobId)).isEqualTo("liberado");
		assertThat(transicoesRegistradas(jobId)).containsExactly("null->aguardando_confirmacao_parametros",
				"aguardando_confirmacao_parametros->gerando_regra", "gerando_regra->simulando",
				"simulando->aguardando_decisao_usuario", "aguardando_decisao_usuario->liberado");
	}

	/**
	 * {@code transicionar} devolve o status de **origem**, não o de destino - é o que o
	 * evento SSE {@code estado} precisa em {@code status_anterior} sem uma segunda
	 * consulta fora da trava (T-045).
	 */
	@Test
	void transicionarDevolveOStatusDeOrigem() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "sistema");

		JobStatus origem = maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "sistema", null);

		assertThat(origem).isEqualTo(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS);
	}

	@Test
	void cadaTransicaoGravaUmaLinhaComTimestamp() throws SQLException {
		UUID jobId = criarJob();
		Instant antes = Instant.now();

		maquina.registrarCriacao(jobId, "sistema");
		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "sistema", null);

		Instant depois = Instant.now();
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT ocorrido_em FROM job_transicoes WHERE job_id = '%s' ORDER BY ocorrido_em"
						.formatted(jobId))) {
			while (rs.next()) {
				Timestamp ocorridoEm = rs.getTimestamp("ocorrido_em");
				assertThat(ocorridoEm).isNotNull();
				assertThat(ocorridoEm.toInstant()).isBetween(antes, depois);
			}
		}
	}

	// --- finalizado_em -----------------------------------------------------------------

	@Test
	void transicaoParaEstadoTerminalGravaFinalizadoEm() throws SQLException {
		UUID jobId = criarJob();
		Instant antes = Instant.now();
		maquina.registrarCriacao(jobId, "sistema");

		maquina.transicionar(jobId, JobStatus.CANCELADO, "rh", "usuário desistiu");

		Instant depois = Instant.now();
		Timestamp finalizadoEm = finalizadoEmPersistido(jobId);
		assertThat(finalizadoEm).isNotNull();
		assertThat(finalizadoEm.toInstant()).isBetween(antes, depois);
	}

	@Test
	void transicaoIntermediariaDeixaFinalizadoEmNulo() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "sistema");

		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "sistema", null);

		assertThat(finalizadoEmPersistido(jobId)).isNull();
	}

	@Test
	void reentregaAposEstadoTerminalNaoAlteraOsTimestampsRegistrados() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, JobStatus.GERANDO_REGRA, "sistema");
		maquina.transicionar(jobId, JobStatus.SIMULANDO, "evento", null);
		maquina.transicionar(jobId, JobStatus.ERRO, "evento", "erro_infra");
		Timestamp iniciadoEm = timestampDoJob(jobId, "iniciado_em");
		Timestamp finalizadoEm = timestampDoJob(jobId, "finalizado_em");

		boolean avancou = maquina.avancarSeEm(jobId, JobStatus.SIMULANDO, JobStatus.ERRO, "evento", "erro_infra");
		assertThatExceptionOfType(TransicaoDeStatusInvalidaException.class)
			.isThrownBy(() -> maquina.transicionar(jobId, JobStatus.ERRO, "evento", "erro_infra"));

		assertThat(avancou).isFalse();
		assertThat(timestampDoJob(jobId, "iniciado_em")).isEqualTo(iniciadoEm);
		assertThat(timestampDoJob(jobId, "finalizado_em")).isEqualTo(finalizadoEm);
		assertThat(transicoesRegistradas(jobId)).hasSize(3);
	}

	// --- iniciado_em -------------------------------------------------------------------

	/**
	 * O job de formulário já nasce em {@code gerando_regra}: não há transição para
	 * {@code gerando_regra} depois da criação, então é a própria transição inicial que
	 * marca o começo do processamento.
	 */
	@Test
	void criacaoDiretamenteEmGerandoRegraGravaIniciadoEmComOInstanteDaTransicaoInicial() throws SQLException {
		UUID jobId = criarJob();
		Instant antes = Instant.now();

		maquina.registrarCriacao(jobId, JobStatus.GERANDO_REGRA, "usuario");

		Instant depois = Instant.now();
		Timestamp iniciadoEm = timestampDoJob(jobId, "iniciado_em");
		assertThat(iniciadoEm).isNotNull();
		assertThat(iniciadoEm.toInstant()).isBetween(antes, depois);
		assertThat(iniciadoEm).isEqualTo(ocorridoEmDaUltimaTransicao(jobId));
		assertThat(timestampDoJob(jobId, "finalizado_em")).isNull();
	}

	@Test
	void jobQueAguardaConfirmacaoSoGanhaIniciadoEmQuandoAConfirmacaoOLevaAGerandoRegra() throws SQLException {
		UUID jobId = criarJob();

		maquina.registrarCriacao(jobId, "usuario");
		assertThat(timestampDoJob(jobId, "iniciado_em")).isNull();

		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "usuario", null);

		assertThat(timestampDoJob(jobId, "iniciado_em")).isNotNull().isEqualTo(ocorridoEmDaUltimaTransicao(jobId));
	}

	@Test
	void oInicioNaoMudaNasTransicoesPosterioresNemQuandoOCicloReabre() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, JobStatus.GERANDO_REGRA, "usuario");
		Timestamp iniciadoEm = timestampDoJob(jobId, "iniciado_em");

		maquina.transicionar(jobId, JobStatus.SIMULANDO, "evento", null);
		maquina.transicionar(jobId, JobStatus.SIMULACAO_INVIAVEL, "evento", "inviavel");
		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "evento", "sugestao_adaptacao_proposta");
		maquina.transicionar(jobId, JobStatus.SIMULANDO, "evento", null);
		maquina.transicionar(jobId, JobStatus.AGUARDANDO_DECISAO_USUARIO, "evento", null);

		assertThat(timestampDoJob(jobId, "iniciado_em")).isEqualTo(iniciadoEm);
		assertThat(timestampDoJob(jobId, "finalizado_em")).isNull();
	}

	@Test
	void transicaoParaEstadoSemProcessamentoNaoGravaIniciadoEm() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "usuario");

		maquina.transicionar(jobId, JobStatus.CANCELADO, "usuario", null);

		assertThat(timestampDoJob(jobId, "iniciado_em")).isNull();
		assertThat(timestampDoJob(jobId, "finalizado_em")).isNotNull();
	}

	// --- avancarSeEm -------------------------------------------------------------------

	@Test
	void avancarSeEmMoveOJobQuandoEleEstaNaOrigemEsperada() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "sistema");
		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "sistema", null);

		boolean avancou = maquina.avancarSeEm(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, "evento", null);

		assertThat(avancou).isTrue();
		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(transicoesRegistradas(jobId)).endsWith("gerando_regra->simulando");
	}

	@Test
	void avancarSeEmNaoFazNadaQuandoOJobJaSaiuDaOrigemEsperada() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "sistema");
		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "sistema", null);
		maquina.transicionar(jobId, JobStatus.SIMULANDO, "sistema", null);

		boolean avancou = maquina.avancarSeEm(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, "evento", null);

		assertThat(avancou).isFalse();
		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(transicoesRegistradas(jobId)).hasSize(3);
	}

	@Test
	void avancarSeEmRecusaUmDestinoForaDoGrafoMesmoNaOrigemEsperada() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "sistema");
		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "sistema", null);

		assertThatExceptionOfType(TransicaoDeStatusInvalidaException.class)
			.isThrownBy(() -> maquina.avancarSeEm(jobId, JobStatus.GERANDO_REGRA, JobStatus.LIBERADO, "evento", null));

		assertThat(statusPersistido(jobId)).isEqualTo("gerando_regra");
	}

	// --- Recusas ----------------------------------------------------------------------

	@Test
	void recusaLiberarDiretoDaSimulacaoInviavel() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "sistema");
		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "sistema", null);
		maquina.transicionar(jobId, JobStatus.SIMULANDO, "sistema", null);
		maquina.transicionar(jobId, JobStatus.SIMULACAO_INVIAVEL, "sistema", "orçamento estourado");

		assertThatExceptionOfType(TransicaoDeStatusInvalidaException.class)
			.isThrownBy(() -> maquina.transicionar(jobId, JobStatus.LIBERADO, "rh", null));

		assertThat(statusPersistido(jobId)).isEqualTo("simulacao_inviavel");
	}

	@Test
	void recusaTransicaoAPartirDeUmEstadoTerminal() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "sistema");
		maquina.transicionar(jobId, JobStatus.CANCELADO, "rh", "usuário desistiu");

		assertThatExceptionOfType(TransicaoDeStatusInvalidaException.class)
			.isThrownBy(() -> maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "sistema", null));

		assertThat(statusPersistido(jobId)).isEqualTo("cancelado");
	}

	@Test
	void recusaPularEtapaIndoDireitoDeAguardandoConfirmacaoParaSimulando() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "sistema");

		assertThatExceptionOfType(TransicaoDeStatusInvalidaException.class)
			.isThrownBy(() -> maquina.transicionar(jobId, JobStatus.SIMULANDO, "sistema", null));

		assertThat(statusPersistido(jobId)).isEqualTo("aguardando_confirmacao_parametros");
	}

	@Test
	void umaTransicaoRecusadaNaoGravaLinhaNaTrilha() throws SQLException {
		UUID jobId = criarJob();
		maquina.registrarCriacao(jobId, "sistema");

		assertThatExceptionOfType(TransicaoDeStatusInvalidaException.class)
			.isThrownBy(() -> maquina.transicionar(jobId, JobStatus.LIBERADO, "sistema", null));

		assertThat(transicoesRegistradas(jobId)).hasSize(1);
	}

	// --- Apoio --------------------------------------------------------------------

	private static UUID criarJob() throws SQLException {
		UUID jobId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO jobs (id, status, usuario_id, competencias, orcamento, criado_em)
					VALUES ('%s', '%s', '%s', '{2025-08}', 1000, now())
					""".formatted(jobId, JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS.paraColuna(), USUARIO_ID));
		}
		return jobId;
	}

	private static String statusPersistido(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("SELECT status FROM jobs WHERE id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getString("status");
		}
	}

	private static Timestamp timestampDoJob(UUID jobId, String coluna) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("SELECT %s FROM jobs WHERE id = '%s'".formatted(coluna, jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getTimestamp(coluna);
		}
	}

	private static Timestamp ocorridoEmDaUltimaTransicao(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery(
						"SELECT ocorrido_em FROM job_transicoes WHERE job_id = '%s' ORDER BY ocorrido_em DESC LIMIT 1"
							.formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getTimestamp("ocorrido_em");
		}
	}

	private static Timestamp finalizadoEmPersistido(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT finalizado_em FROM jobs WHERE id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getTimestamp("finalizado_em");
		}
	}

	private static List<String> transicoesRegistradas(UUID jobId) throws SQLException {
		List<String> transicoes = new ArrayList<>();
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery(
						"SELECT status_anterior, status_novo FROM job_transicoes WHERE job_id = '%s' ORDER BY ocorrido_em"
							.formatted(jobId))) {
			while (rs.next()) {
				transicoes.add(rs.getString("status_anterior") + "->" + rs.getString("status_novo"));
			}
		}
		return transicoes;
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static Liquibase liquibase(Connection connection) throws Exception {
		Database database = DatabaseFactory.getInstance()
			.findCorrectDatabaseImplementation(new JdbcConnection(connection));
		Liquibase liquibase = new Liquibase(CHANGELOG, new ClassLoaderResourceAccessor(), database);
		liquibase.getChangeLogParameters().set("usuario_api", USUARIO_API);
		liquibase.getChangeLogParameters().set("usuario_codegen", "synapse_codegen");
		liquibase.getChangeLogParameters().set("usuario_worker", "synapse_worker");
		return liquibase;
	}

}
