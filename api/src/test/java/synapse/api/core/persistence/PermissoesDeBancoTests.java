package synapse.api.core.persistence;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;

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
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;

/**
 * O isolamento entre serviços é aplicado pelo banco, e é isto que prova: uma escrita
 * indevida falha por permissão, não porque alguém lembrou de não fazê-la.
 *
 * Afirma o SQLState {@code 42501} e não a mensagem — é o que distingue "o banco recusou
 * por privilégio" de "a query quebrou por outro motivo", e faz o teste falhar se um dia a
 * recusa vier de outro lugar.
 */
@EnabledIf("dockerIsAvailable")
class PermissoesDeBancoTests {

	private static final String CHANGELOG = "db/changelog/changelog.yaml";

	/** {@code insufficient_privilege}. */
	private static final String PERMISSAO_NEGADA = "42501";

	private static final String SENHA = "senha-de-teste";

	private static PostgreSQLContainer postgres;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	/**
	 * O changelog roda uma vez e o cenário é semeado pelo dono. Nenhum teste escreve pelo
	 * dono depois disso: o que se afirma é sempre o que o usuário do serviço alcança.
	 */
	@BeforeAll
	static void prepararOBanco() throws Exception {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();

		try (Connection connection = comoDono(); Liquibase liquibase = liquibase(connection)) {
			liquibase.update(new Contexts());
		}

		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			// O changeset cria o papel sem senha, porque senha não entra em arquivo
			// versionado. Em produção quem a define é o initdb do compose; aqui, o teste.
			for (String usuario : new String[] { UsuariosDeBanco.API, UsuariosDeBanco.CODEGEN,
					UsuariosDeBanco.WORKER }) {
				statement.execute("ALTER ROLE " + usuario + " WITH PASSWORD '" + SENHA + "'");
			}
			semear(statement);
		}
	}

	@AfterAll
	static void derrubarOPostgres() {
		if (postgres != null) {
			postgres.stop();
		}
	}

	// --- A negativa: estado e decisão de negócio são inalcançáveis -----------------

	@Test
	void oCodegenNaoEscreveEmJobs() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, INSERE_JOB)).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void oWorkerNaoEscreveEmJobs() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, INSERE_JOB)).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void nenhumDosDoisLeJobs() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "SELECT id FROM jobs")).isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "SELECT id FROM jobs")).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void nenhumDosDoisAlcancaTrilhaTransicoesOuOutbox() {
		for (String usuario : new String[] { UsuariosDeBanco.CODEGEN, UsuariosDeBanco.WORKER }) {
			assertThat(sqlStateAoFalhar(usuario, "SELECT id FROM trilhas_auditoria")).isEqualTo(PERMISSAO_NEGADA);
			assertThat(sqlStateAoFalhar(usuario, "SELECT id FROM job_transicoes")).isEqualTo(PERMISSAO_NEGADA);
			assertThat(sqlStateAoFalhar(usuario, "SELECT id FROM job_acoes")).isEqualTo(PERMISSAO_NEGADA);
			assertThat(sqlStateAoFalhar(usuario, "SELECT id FROM outbox_events")).isEqualTo(PERMISSAO_NEGADA);
		}
	}

	// --- O positivo: sem ele, um papel sem GRANT nenhum passaria em tudo acima -----

	@Test
	void oCodegenGravaOsArtefatosQueProduz() {
		assertThatCode(() -> executar(UsuariosDeBanco.CODEGEN, """
				INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
				VALUES ('%s', 'extracao', 'texto', '{}'::jsonb, now())
				""".formatted(JOB_ID))).doesNotThrowAnyException();
	}

	@Test
	void oWorkerGravaOResultado() {
		assertThatCode(() -> executar(UsuariosDeBanco.WORKER, """
				INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, assercoes, criado_em)
				VALUES ('%s', '%s', 'sucesso', '[]'::jsonb, now())
				""".formatted(JOB_ID, CODIGO_ID))).doesNotThrowAnyException();
	}

	@Test
	void oCodegenLeATranscricao() {
		assertThatCode(() -> executar(UsuariosDeBanco.CODEGEN, "SELECT transcricao FROM submissoes"))
			.doesNotThrowAnyException();
	}

	// --- O código executado é lido, nunca alterado ---------------------------------

	@Test
	void oWorkerLeOCodigoAExecutar() {
		assertThatCode(() -> executar(UsuariosDeBanco.WORKER, "SELECT fonte FROM codigos_gerados"))
			.doesNotThrowAnyException();
	}

	@Test
	void oWorkerNaoAlteraOCodigoAExecutar() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.WORKER, "UPDATE codigos_gerados SET fonte = 'adulterado'"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	// --- A regra é imutável para quem a escreve ------------------------------------

	@Test
	void oCodegenInsereVersaoDeRegraMasNaoAAltera() {
		assertThatCode(() -> executar(UsuariosDeBanco.CODEGEN, """
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES ('%s', 2, 'extracao', '{}'::jsonb, '{}'::jsonb, repeat('b', 64), now())
				""".formatted(JOB_ID))).doesNotThrowAnyException();

		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "UPDATE regras SET versao = 99"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.CODEGEN, "DELETE FROM regras")).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void nemMesmoAApiAlteraUmaRegraJaGravada() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "UPDATE regras SET versao = 99")).isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "DELETE FROM regras")).isEqualTo(PERMISSAO_NEGADA);
	}

	@Test
	void aApiNaoEscreveNaTabelaDeArtefatoDeOutroServico() {
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "UPDATE codigos_gerados SET fonte = 'x'"))
			.isEqualTo(PERMISSAO_NEGADA);
		assertThat(sqlStateAoFalhar(UsuariosDeBanco.API, "UPDATE resultados_simulacao SET veredito = 'x'"))
			.isEqualTo(PERMISSAO_NEGADA);
	}

	// --- Apoio ---------------------------------------------------------------------

	private static final String JOB_ID = "11111111-1111-4111-8111-111111111111";

	private static final String CODIGO_ID = "33333333-3333-4333-8333-333333333333";

	private static final String INSERE_JOB = """
			INSERT INTO jobs (status, usuario_id, competencias, orcamento, criado_em)
			VALUES ('recebido', '%s', '{2025-08}', 1000, now())
			""".formatted("22222222-2222-4222-8222-222222222222");

	/**
	 * As linhas de apoio de que as afirmações dependem: um job para as chaves
	 * estrangeiras, uma submissão para o codegen ler e um código gerado para o worker ler
	 * e tentar alterar.
	 */
	private static void semear(Statement statement) throws SQLException {
		statement.execute("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES ('22222222-2222-4222-8222-222222222222', 'rh', 'x', 'RH', 'profissional_rh', now())
				""");
		statement.execute("""
				INSERT INTO submissoes (id, usuario_id, tipo, transcricao, criado_em)
				VALUES ('44444444-4444-4444-8444-444444444444', '22222222-2222-4222-8222-222222222222',
				        'voz', 'pague 5% sobre a meta', now())
				""");
		statement.execute("""
				INSERT INTO jobs (id, status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES ('%s', 'recebido', '22222222-2222-4222-8222-222222222222',
				        '44444444-4444-4444-8444-444444444444', '{2025-08}', 1000, now())
				""".formatted(JOB_ID));
		statement.execute("""
				INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES ('55555555-5555-4555-8555-555555555555', '%s', 1, 'extracao',
				        '{}'::jsonb, '{}'::jsonb, repeat('a', 64), now())
				""".formatted(JOB_ID));
		statement.execute("""
				INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
				VALUES ('66666666-6666-4666-8666-666666666666', '%s', 'geracao', 'texto', '{}'::jsonb, now())
				""".formatted(JOB_ID));
		statement.execute("""
				INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES ('%s', '%s', '55555555-5555-4555-8555-555555555555', 'python', 'def apurar(): ...',
				        '66666666-6666-4666-8666-666666666666', now())
				""".formatted(CODIGO_ID, JOB_ID));
	}

	/** Roda o comando como {@code usuario} e devolve o SQLState da recusa. */
	private static String sqlStateAoFalhar(String usuario, String sql) {
		return assertThatExceptionOfType(SQLException.class).isThrownBy(() -> executar(usuario, sql))
			.actual()
			.getSQLState();
	}

	private static void executar(String usuario, String sql) throws SQLException {
		try (Connection connection = como(usuario); Statement statement = connection.createStatement()) {
			statement.execute(sql);
		}
	}

	private static Connection como(String usuario) throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), usuario, SENHA);
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static Liquibase liquibase(Connection connection) throws Exception {
		Database database = DatabaseFactory.getInstance()
			.findCorrectDatabaseImplementation(new JdbcConnection(connection));
		Liquibase liquibase = new Liquibase(CHANGELOG, new ClassLoaderResourceAccessor(), database);
		UsuariosDeBanco.parametrosEm(liquibase);
		return liquibase;
	}

}
