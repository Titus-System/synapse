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
