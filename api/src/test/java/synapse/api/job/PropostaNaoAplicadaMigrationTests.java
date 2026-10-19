package synapse.api.job;

import java.sql.DriverManager;
import java.util.Objects;
import java.util.UUID;

import liquibase.Contexts;
import liquibase.LabelExpression;
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
class PropostaNaoAplicadaMigrationTests {

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@Test
	void upgradeLegadoPermissoesPrecisaoERollback() throws Exception {
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
				liquibase.update(30, new Contexts(), new LabelExpression());
				UUID usuario = jdbc.queryForObject(
						"INSERT INTO usuarios (login, nome, papel, criado_em) VALUES ('migracao217e4', 'RH', 'profissional_rh', now()) RETURNING id",
						UUID.class);
				UUID job = jdbc.queryForObject(
						"INSERT INTO jobs (usuario_id, status, competencias, criado_em) VALUES (?, 'aguardando_confirmacao_parametros', ARRAY['2025-11'], now()) RETURNING id",
						UUID.class, usuario);
				UUID regra = jdbc.queryForObject(
						"INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em) VALUES (?, 1, 'extracao', '{}'::jsonb, '[]'::jsonb, repeat('a',64), now()) RETURNING id",
						UUID.class, job);
				String legado = "INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado, criada_em, atualizada_em) VALUES (?, ?, '[]'::jsonb, 'reextracao_falhou', now(), now()) RETURNING id";
				UUID rodada = jdbc.queryForObject(legado, UUID.class, job, regra);
				String antes = jdbc.queryForObject("SELECT row_to_json(r)::text FROM rodadas_correcao r WHERE id = ?",
						String.class, rodada);
				liquibase.update(new Contexts());
				assertThat(jdbc.queryForObject(
						"SELECT count(*) FROM information_schema.columns WHERE table_name = 'rodadas_correcao' AND column_name = 'proposta_nao_aplicada' AND is_nullable = 'YES'",
						Integer.class))
					.isEqualTo(1);
				assertThat(jdbc.queryForObject("SELECT proposta_nao_aplicada::text FROM rodadas_correcao WHERE id = ?",
						String.class, rodada))
					.isNull();
				liquibase.update(new Contexts());
				assertThat(jdbc.queryForObject("SELECT count(*) FROM databasechangelog", Integer.class)).isEqualTo(32);
				jdbc.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
				jdbc.execute("ALTER ROLE synapse_codegen WITH PASSWORD 'senha-de-teste'");
				jdbc.execute("ALTER ROLE synapse_worker WITH PASSWORD 'senha-de-teste'");
				var api = new JdbcTemplate(
						new DriverManagerDataSource(postgres.getJdbcUrl(), "synapse_api", "senha-de-teste"));
				UUID nova = Objects.requireNonNull(api.queryForObject(legado, UUID.class, job, regra));
				api.update("UPDATE rodadas_correcao SET proposta_nao_aplicada = ?::jsonb WHERE id = ?",
						"{\"extensao\":0.12345678901234567890123456789}", nova);
				var codegen = new JdbcTemplate(
						new DriverManagerDataSource(postgres.getJdbcUrl(), "synapse_codegen", "senha-de-teste"));
				assertThat(codegen.queryForObject(
						"SELECT proposta_nao_aplicada->>'extensao' FROM rodadas_correcao WHERE id = ?", String.class,
						nova))
					.isEqualTo("0.12345678901234567890123456789");
				assertThatThrownBy(() -> codegen.update("UPDATE rodadas_correcao SET proposta_nao_aplicada = NULL"))
					.isInstanceOfSatisfying(DataAccessException.class,
							e -> assertThat(((java.sql.SQLException) e.getMostSpecificCause()).getSQLState())
								.isEqualTo("42501"));
				var worker = new JdbcTemplate(
						new DriverManagerDataSource(postgres.getJdbcUrl(), "synapse_worker", "senha-de-teste"));
				assertThatThrownBy(() -> worker.queryForList("SELECT proposta_nao_aplicada FROM rodadas_correcao"))
					.isInstanceOfSatisfying(DataAccessException.class,
							e -> assertThat(((java.sql.SQLException) e.getMostSpecificCause()).getSQLState())
								.isEqualTo("42501"));
				liquibase.rollback(2, new Contexts(), new LabelExpression());
				assertThat(jdbc.queryForObject(
						"SELECT count(*) FROM information_schema.columns WHERE table_name = 'rodadas_correcao' AND column_name = 'proposta_nao_aplicada'",
						Integer.class))
					.isZero();
				assertThat(jdbc.queryForObject("SELECT row_to_json(r)::text FROM rodadas_correcao r WHERE id = ?",
						String.class, rodada))
					.isEqualTo(antes);
				assertThat(jdbc.queryForObject("SELECT count(*) FROM rodadas_correcao", Integer.class)).isEqualTo(2);
			}
		}
	}

}
