package synapse.api.core.persistence;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

import liquibase.Contexts;
import liquibase.LabelExpression;
import liquibase.Liquibase;
import liquibase.database.Database;
import liquibase.database.DatabaseFactory;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.ClassLoaderResourceAccessor;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * O changelog roda contra um Postgres de verdade, na mesma major que o compose: o
 * {@code uuidv7()} e o índice parcial não existem num banco em memória.
 */
@EnabledIf("dockerIsAvailable")
class MigrationTests {

	private static final String CHANGELOG = "db/changelog/changelog.yaml";

	private static final List<String> TABELAS = List.of("usuarios", "submissoes", "jobs", "job_transicoes", "job_acoes",
			"regras", "prompts", "respostas_modelo", "codigos_gerados", "resultados_simulacao", "explicacoes",
			"simulacoes", "trilhas_auditoria", "outbox_events");

	// Uma tabela por changeset, mais o 000 que cria os usuários de banco e não cria
	// tabela nenhuma.
	private static final int CHANGESETS = TABELAS.size() + 1;

	private static PostgreSQLContainer postgres;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void subirOPostgres() {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
	}

	@AfterAll
	static void derrubarOPostgres() {
		if (postgres != null) {
			postgres.stop();
		}
	}

	/**
	 * O container é um só e o teste de rollback derruba tudo: cada teste parte de um
	 * banco limpo em vez de herdar o estado do anterior.
	 */
	@BeforeEach
	void zerarOBanco() throws Exception {
		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			statement.execute("DROP SCHEMA public CASCADE");
			statement.execute("CREATE SCHEMA public");
		}
	}

	@Test
	void aplicaOChangelogECriaAsTabelasDoModelo() throws Exception {
		atualizar();

		assertThat(tabelasExistentes()).containsExactlyInAnyOrderElementsOf(TABELAS);
	}

	@Test
	void criaOsDoisIndicesQueODbmlNaoExpressa() throws Exception {
		atualizar();

		assertThat(definicaoDoIndice("idx_jobs_usuario_id_criado_em")).contains("criado_em DESC");
		assertThat(definicaoDoIndice("idx_outbox_events_criado_em_pendentes")).contains("WHERE (publicado_em IS NULL)");
	}

	@Test
	void subirDeNovoNaoReaplicaOChangeset() throws Exception {
		atualizar();
		int aplicadosNaPrimeira = changesetsAplicados();

		atualizar();

		assertThat(aplicadosNaPrimeira).isEqualTo(CHANGESETS);
		assertThat(changesetsAplicados()).isEqualTo(aplicadosNaPrimeira);
	}

	@Test
	void oRollbackDeclaradoDesfazACriacao() throws Exception {
		atualizar();

		reverter(CHANGESETS);

		assertThat(tabelasExistentes()).isEmpty();
	}

	@Test
	void idOmitidoNasceUuidV7EIdFornecidoEPreservado() throws Exception {
		atualizar();

		try (Connection connection = abrir(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO usuarios (login, senha_hash, nome, papel, criado_em)
					VALUES ('omitido', 'x', 'Omitido', 'auditor', now())
					""");
			statement.execute("""
					INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
					VALUES ('11111111-1111-4111-8111-111111111111', 'fornecido', 'x', 'Fornecido',
					        'auditor', now())
					""");

			try (ResultSet rs = statement.executeQuery("""
					SELECT login, id::text AS id, uuid_extract_version(id) AS versao
					FROM usuarios ORDER BY login
					""")) {
				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("login")).isEqualTo("fornecido");
				assertThat(rs.getString("id")).isEqualTo("11111111-1111-4111-8111-111111111111");
				assertThat(rs.getInt("versao")).isEqualTo(4);

				assertThat(rs.next()).isTrue();
				assertThat(rs.getString("login")).isEqualTo("omitido");
				assertThat(rs.getInt("versao")).isEqualTo(7);
			}
		}
	}

	// Liquibase.close() fecha a conexão JDBC por baixo, então cada operação abre a sua
	// em vez de compartilhar uma com as afirmações.
	private static void atualizar() throws Exception {
		try (Connection connection = abrir(); Liquibase liquibase = liquibase(connection)) {
			liquibase.update(new Contexts());
		}
	}

	private static void reverter(int changesets) throws Exception {
		try (Connection connection = abrir(); Liquibase liquibase = liquibase(connection)) {
			liquibase.rollback(changesets, new Contexts(), new LabelExpression());
		}
	}

	private static Liquibase liquibase(Connection connection) throws Exception {
		Database database = DatabaseFactory.getInstance()
			.findCorrectDatabaseImplementation(new JdbcConnection(connection));
		Liquibase liquibase = new Liquibase(CHANGELOG, new ClassLoaderResourceAccessor(), database);
		UsuariosDeBanco.parametrosEm(liquibase);
		return liquibase;
	}

	private static Connection abrir() throws Exception {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static List<String> tabelasExistentes() throws Exception {
		List<String> tabelas = new ArrayList<>();
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("""
						SELECT table_name FROM information_schema.tables
						WHERE table_schema = 'public' AND table_name NOT LIKE 'databasechangelog%'
						""")) {
			while (rs.next()) {
				tabelas.add(rs.getString("table_name"));
			}
		}
		return tabelas;
	}

	private static String definicaoDoIndice(String indice) throws Exception {
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT indexdef FROM pg_indexes WHERE indexname = '" + indice + "'")) {
			assertThat(rs.next()).as("índice %s não existe", indice).isTrue();
			return rs.getString("indexdef");
		}
	}

	private static int changesetsAplicados() throws Exception {
		try (Connection connection = abrir();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("SELECT count(*) FROM databasechangelog")) {
			rs.next();
			return rs.getInt(1);
		}
	}

}
