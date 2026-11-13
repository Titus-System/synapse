package synapse.api.auditoria;

import java.sql.Connection;
import java.sql.DriverManager;
import java.util.Objects;
import java.util.UUID;

import javax.sql.DataSource;

import liquibase.Contexts;
import liquibase.Liquibase;
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

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import synapse.api.job.NomesDeJobs;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.spy;

/**
 * Executa {@link AuditoriaService} como {@code synapse_api} num Postgres real e grava
 * como dono do banco no meio da leitura: as consultas de uma resposta precisam correr
 * numa transação somente leitura com um único instantâneo, e o que entra depois da
 * primeira consulta não aparece nas seguintes.
 */
@EnabledIf("dockerIsAvailable")
class AuditoriaSnapshotPersistenciaTests {

	private static final UUID USUARIO = UUID.fromString("22222222-2222-4222-8222-222222222222");

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static JdbcTemplate dono;

	private static AuditoriaService service;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void preparar() throws Exception {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		try (Connection conexao = DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(),
				postgres.getPassword());
				Liquibase liquibase = new Liquibase("db/changelog/changelog.yaml", new ClassLoaderResourceAccessor(),
						DatabaseFactory.getInstance().findCorrectDatabaseImplementation(new JdbcConnection(conexao)))) {
			liquibase.getChangeLogParameters().set("usuario_api", "synapse_api");
			liquibase.getChangeLogParameters().set("usuario_codegen", "synapse_codegen");
			liquibase.getChangeLogParameters().set("usuario_worker", "synapse_worker");
			liquibase.update(new Contexts());
		}
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		DataSource dataSource = new DriverManagerDataSource(postgres.getJdbcUrl(), "synapse_api", "senha-de-teste");
		jdbc = new JdbcTemplate(dataSource);
		contexto = new AnnotationConfigApplicationContext();
		contexto.registerBean(DataSource.class, () -> dataSource);
		contexto.registerBean(JdbcTemplate.class, () -> jdbc);
		contexto.registerBean(PlatformTransactionManager.class, () -> new DataSourceTransactionManager(dataSource));
		contexto.registerBean(AuditoriaRepository.class, () -> spy(new AuditoriaRepository(jdbc)));
		contexto.registerBean(NomesDeJobs.class, () -> mock(NomesDeJobs.class));
		contexto.register(Config.class);
		contexto.refresh();
		service = contexto.getBean(AuditoriaService.class);
	}

	@AfterAll
	static void encerrar() {
		if (contexto != null) {
			contexto.close();
		}
		if (postgres != null) {
			postgres.stop();
		}
	}

	@BeforeEach
	void prepararUsuario() {
		dono.execute("TRUNCATE usuarios CASCADE");
		dono.update("""
				INSERT INTO usuarios (id, login, nome, papel, criado_em)
				VALUES (?, 'rh', 'RH', 'profissional_rh', now())
				""", USUARIO);
	}

	@TestConfiguration
	@EnableTransactionManagement
	@Import(AuditoriaService.class)
	static class Config {

	}

	@Test
	void contagemEPaginaDaListagemUsamOMesmoSnapshotMesmoComCriacaoConcorrente() {
		UUID existente = criarJob();
		AuditoriaRepository repository = contexto.getBean(AuditoriaRepository.class);
		reset(repository);
		doAnswer(chamada -> {
			assertTransacaoDeLeituraComSnapshot();
			Object total = chamada.callRealMethod();
			criarJob();
			return total;
		}).when(repository).contarJobs();
		try {
			PaginaJobsAuditoriaDto pagina = service.listar(new PaginaAuditoria(0, 20));

			assertThat(pagina.total()).isEqualTo(1);
			assertThat(pagina.itens()).extracting(JobAuditoriaDto::id).containsExactly(existente);
			assertThat(dono.queryForObject("SELECT count(*) FROM jobs", Integer.class)).isEqualTo(2);
		}
		finally {
			reset(repository);
		}
	}

	@Test
	void secoesDoRegistroUsamOMesmoSnapshotMesmoComEscritaConcorrente() {
		UUID job = criarJob();
		AuditoriaRepository repository = contexto.getBean(AuditoriaRepository.class);
		reset(repository);
		doAnswer(chamada -> {
			assertTransacaoDeLeituraComSnapshot();
			Object entradas = chamada.callRealMethod();
			dono.update("INSERT INTO job_acoes (job_id, acao, executado_em) VALUES (?, 'salvar', now())", job);
			return entradas;
		}).when(repository).listarEntradas(job);
		try {
			RegistroAuditoriaDto registro = service.consultar(job);

			assertThat(registro.acoes()).isEmpty();
			assertThat(dono.queryForObject("SELECT count(*) FROM job_acoes WHERE job_id = ?", Integer.class, job))
				.isEqualTo(1);
		}
		finally {
			reset(repository);
		}
	}

	private static void assertTransacaoDeLeituraComSnapshot() {
		assertThat(jdbc.queryForObject("SHOW transaction_isolation", String.class)).isEqualTo("repeatable read");
		assertThat(jdbc.queryForObject("SHOW transaction_read_only", String.class)).isEqualTo("on");
	}

	private static UUID criarJob() {
		UUID submissao = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em)
				VALUES (?, 'texto', 'Comissão de 2% na loja 13', now()) RETURNING id
				""", UUID.class, USUARIO));
		return Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES ('gerando_regra', ?, ?, ARRAY['2025-11'], 485000, now()) RETURNING id
				""", UUID.class, USUARIO, submissao));
	}

}
