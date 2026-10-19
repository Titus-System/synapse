package synapse.api.job;

import java.sql.DriverManager;
import java.util.Objects;
import java.util.UUID;

import liquibase.Contexts;
import liquibase.Liquibase;
import liquibase.database.DatabaseFactory;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.ClassLoaderResourceAccessor;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@EnabledIf("dockerIsAvailable")
class RepresentacaoMigrationTests {

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@Test
	void migraVersoesAntigasPreservaInsertsPermissoesEReverteSomenteAColunaNova() throws Exception {
		try (var postgres = new PostgreSQLContainer("postgres:18-alpine")) {
			postgres.start();
			var jdbc = new JdbcTemplate(
					new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
			try (var conexao = DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(),
					postgres.getPassword());
					var liquibase = new Liquibase("db/changelog/changelog.yaml", new ClassLoaderResourceAccessor(),
							DatabaseFactory.getInstance()
								.findCorrectDatabaseImplementation(new JdbcConnection(conexao)))) {
				liquibase.getChangeLogParameters().set("usuario_api", "synapse_api");
				liquibase.getChangeLogParameters().set("usuario_codegen", "synapse_codegen");
				liquibase.getChangeLogParameters().set("usuario_worker", "synapse_worker");
				liquibase.update(29, new Contexts(), new liquibase.LabelExpression());
				UUID usuario = Objects.requireNonNull(jdbc.queryForObject(
						"INSERT INTO usuarios (login, nome, papel, criado_em) VALUES ('migration217', 'RH', 'profissional_rh', now()) RETURNING id",
						UUID.class));
				UUID job = Objects.requireNonNull(jdbc.queryForObject(
						"INSERT INTO jobs (usuario_id, status, competencias, criado_em) VALUES (?, 'gerando_regra', ARRAY['2025-11'], now()) RETURNING id",
						UUID.class, usuario));
				String legado = "INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em) VALUES (?, ?, 'confirmacao_usuario', '{}'::jsonb, '[]'::jsonb, ?, now())";
				jdbc.update(legado, job, 1, "a".repeat(64));
				String antes = jdbc.queryForObject("SELECT row_to_json(r)::text FROM regras r WHERE job_id = ?",
						String.class, job);
				liquibase.update(new Contexts());
				assertThat(jdbc.queryForObject(
						"SELECT count(*) FROM information_schema.columns WHERE table_name = 'regras' AND column_name = 'representacao' AND is_nullable = 'YES'",
						Integer.class))
					.isEqualTo(1);
				assertThat(jdbc.queryForObject("SELECT representacao::text FROM regras WHERE job_id = ?", String.class,
						job))
					.isNull();
				liquibase.update(new Contexts());
				assertThat(jdbc.queryForObject("SELECT count(*) FROM databasechangelog", Integer.class)).isEqualTo(32);
				jdbc.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
				jdbc.execute("ALTER ROLE synapse_codegen WITH PASSWORD 'senha-de-teste'");
				var api = new JdbcTemplate(
						new DriverManagerDataSource(postgres.getJdbcUrl(), "synapse_api", "senha-de-teste"));
				api.update(legado, job, 2, "b".repeat(64));
				String inserir = "INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, representacao, hash, criada_em) VALUES (?, 3, 'correcao', '{}'::jsonb, '[]'::jsonb, ?::jsonb, ?, now())";
				for (String invalida : new String[] { "{}", "null", "[]", "{\"nucleo\":{},\"especificacoes\":[{}]}",
						"{\"nucleo\":{\"loja\":[\"1\"]},\"especificacoes\":[]}" }) {
					assertThatThrownBy(() -> api.update(inserir, job, invalida, "c".repeat(64))).isInstanceOfSatisfying(
							DataAccessException.class,
							ex -> assertThat(((java.sql.SQLException) ex.getMostSpecificCause()).getSQLState())
								.isEqualTo("23514"));
				}
				String completa = "{\"nucleo\":{},\"especificacoes\":[],\"extensao\":123.12345678901234567890123456789}";
				api.update(inserir, job, completa, "c".repeat(64));
				assertThat(api.queryForObject(
						"SELECT representacao->>'extensao' FROM regras WHERE job_id = ? AND versao = 3", String.class,
						job))
					.isEqualTo("123.12345678901234567890123456789");
				var codegen = new JdbcTemplate(
						new DriverManagerDataSource(postgres.getJdbcUrl(), "synapse_codegen", "senha-de-teste"));
				assertThat(codegen.queryForObject("SELECT count(representacao) FROM regras", Integer.class))
					.isEqualTo(1);
				for (var papel : new JdbcTemplate[] { api, codegen }) {
					for (String sql : new String[] { "UPDATE regras SET representacao = NULL", "DELETE FROM regras" }) {
						assertThatThrownBy(() -> papel.update(sql)).isInstanceOfSatisfying(DataAccessException.class,
								ex -> assertThat(((java.sql.SQLException) ex.getMostSpecificCause()).getSQLState())
									.isEqualTo("42501"));
					}
				}
				liquibase.rollback(3, new Contexts(), new liquibase.LabelExpression());
				assertThat(jdbc.queryForObject(
						"SELECT count(*) FROM information_schema.columns WHERE table_name = 'regras' AND column_name = 'representacao'",
						Integer.class))
					.isZero();
				assertThat(jdbc.queryForObject(
						"SELECT row_to_json(r)::text FROM regras r WHERE job_id = ? AND versao = 1", String.class, job))
					.isEqualTo(antes);
				assertThat(jdbc.queryForObject("SELECT count(*) FROM regras", Integer.class)).isEqualTo(3);
			}
		}
	}

}
