package synapse.api.job;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
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
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.support.SqlArrayValue;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;

/**
 * Roda contra um Postgres de verdade, como o usuário {@code synapse_api}: prova que a
 * ação transiciona o job, grava {@code job_acoes} e {@code job_transicoes} na mesma
 * transação, e que uma recusa desfaz as duas.
 */
@EnabledIf("dockerIsAvailable")
class ExecutarAcaoPersistenciaTests {

	private static final UUID USUARIO = UUID.fromString("44444444-4444-4444-8444-444444444444");

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static JdbcTemplate dono;

	private static ExecutarAcaoService service;

	private static BuscarJobService buscarJob;

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
		jdbc.update("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES (?, 'rh-t077', 'x', 'RH', 'profissional_rh', now())
				""", USUARIO);

		contexto = new AnnotationConfigApplicationContext();
		contexto.registerBean(DataSource.class, () -> dataSource);
		contexto.registerBean(JdbcTemplate.class, () -> jdbc);
		contexto.registerBean(PlatformTransactionManager.class, () -> new DataSourceTransactionManager(dataSource));
		contexto.register(Config.class);
		contexto.refresh();
		service = contexto.getBean(ExecutarAcaoService.class);
		buscarJob = contexto.getBean(BuscarJobService.class);
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
	void limparJobs() {
		dono.update("DELETE FROM job_acoes");
		dono.update("DELETE FROM job_transicoes");
		dono.update("DELETE FROM regras");
		dono.update("DELETE FROM jobs");
		dono.update("DELETE FROM submissoes");
	}

	@TestConfiguration(proxyBeanMethods = false)
	@EnableTransactionManagement
	@Import({ ExecutarAcaoService.class, MaquinaDeEstadosDoJob.class, BuscarJobService.class })
	static class Config {

	}

	@Test
	void confirmarLiberarSobreJobViavelTransicionaEGravaATrilhaComAtorETimestamp() {
		UUID jobId = criarJobComRegra(JobStatus.AGUARDANDO_DECISAO_USUARIO);
		Instant antes = Instant.now();

		JobDetalhadoDto job = service.aplicar(jobId, AcaoJob.CONFIRMAR_LIBERAR).job();

		Instant depois = Instant.now();
		assertThat(job.status()).isEqualTo("liberado");
		assertThat(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId))
			.isEqualTo("liberado");
		Timestamp finalizadoEm = Objects
			.requireNonNull(jdbc.queryForObject("SELECT finalizado_em FROM jobs WHERE id = ?", Timestamp.class, jobId));
		assertThat(finalizadoEm.toInstant()).isBetween(antes, depois);

		Map<String, Object> acao = jdbc.queryForMap("SELECT * FROM job_acoes WHERE job_id = ?", jobId);
		assertThat(acao).containsEntry("acao", "confirmar_liberar");
		assertThat(acao.get("executado_em")).isNotNull();

		Map<String, Object> transicao = jdbc.queryForMap("""
				SELECT * FROM job_transicoes WHERE job_id = ? AND status_novo = 'liberado'
				""", jobId);
		assertThat(transicao).containsEntry("ator", "usuario")
			.containsEntry("status_anterior", "aguardando_decisao_usuario");
		assertThat(transicao.get("ocorrido_em")).isNotNull();
	}

	@Test
	void salvarGravaOLiteralSalvarMasTransicionaComoLiberar() {
		UUID jobId = criarJobComRegra(JobStatus.AGUARDANDO_DECISAO_USUARIO);

		JobDetalhadoDto job = service.aplicar(jobId, AcaoJob.SALVAR).job();

		assertThat(job.status()).isEqualTo("liberado");
		assertThat(jdbc.queryForObject("SELECT acao FROM job_acoes WHERE job_id = ?", String.class, jobId))
			.isEqualTo("salvar");
	}

	@Test
	void recusaLiberarJobInviavelSemAlterarEstadoNemGravarTrilha() {
		UUID jobId = criarJobComRegra(JobStatus.SIMULACAO_INVIAVEL);

		assertThatExceptionOfType(ExecutarAcaoException.class)
			.isThrownBy(() -> service.aplicar(jobId, AcaoJob.CONFIRMAR_LIBERAR))
			.satisfies(ex -> assertThat(ex.erro().codigo()).isEqualTo("simulacao_inviavel"));

		assertThat(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId))
			.isEqualTo("simulacao_inviavel");
		assertThat(jdbc.queryForObject("SELECT finalizado_em FROM jobs WHERE id = ?", Timestamp.class, jobId)).isNull();
		assertThat(jdbc.queryForObject("SELECT count(*) FROM job_acoes WHERE job_id = ?", Integer.class, jobId))
			.isZero();
		assertThat(jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(1);
	}

	@ParameterizedTest
	@EnumSource(value = JobStatus.class, names = { "SIMULACAO_INVIAVEL", "AGUARDANDO_DECISAO_USUARIO" })
	void cancelarLevaAoEstadoCancelado(JobStatus origem) {
		UUID jobId = criarJobComRegra(origem);

		JobDetalhadoDto job = service.aplicar(jobId, AcaoJob.CANCELAR).job();

		assertThat(job.status()).isEqualTo("cancelado");
	}

	@ParameterizedTest
	@EnumSource(value = JobStatus.class, names = { "SIMULACAO_INVIAVEL", "AGUARDANDO_DECISAO_USUARIO" })
	void arquivarLevaAoEstadoArquivadoEMantemOJobEATrilhaConsultaveis(JobStatus origem) {
		UUID jobId = criarJobComRegra(origem);

		service.aplicar(jobId, AcaoJob.ARQUIVAR);

		JobDetalhadoDto job = buscarJob.buscar(jobId);
		assertThat(job.status()).isEqualTo("arquivado");
		assertThat(jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(2);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM job_acoes WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(1);
	}

	@Test
	void acaoSobreJobInexistenteLancaJobNaoEncontrado() {
		assertThatExceptionOfType(JobNaoEncontradoException.class)
			.isThrownBy(() -> service.aplicar(UUID.randomUUID(), AcaoJob.CANCELAR));
	}

	@Test
	void acaoForaDoEstadoAtualERecusadaComOsEstadosExigidos() {
		UUID jobId = criarJobComRegra(JobStatus.LIBERADO);

		assertThatExceptionOfType(ExecutarAcaoException.class)
			.isThrownBy(() -> service.aplicar(jobId, AcaoJob.CANCELAR))
			.satisfies(ex -> {
				assertThat(ex.erro().codigo()).isEqualTo("estado_invalido");
				assertThat(ex.erro().mensagem()).contains("aguardando_decisao_usuario").contains("liberado");
			});
	}

	private static UUID criarJobComRegra(JobStatus status) {
		UUID submissaoId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, conteudo, criado_em)
				VALUES (?, 'formulario', '{}'::jsonb, now()) RETURNING id
				""", UUID.class, USUARIO));
		UUID jobId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES (?, ?, ?, ?, 500000, now()) RETURNING id
				""", UUID.class, status.paraColuna(), USUARIO, submissaoId,
				new SqlArrayValue("text", List.of("2025-11").toArray())));
		jdbc.update("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES (?, 1, 'confirmacao_usuario', '{}'::jsonb, '[]'::jsonb, 'hash', now())
				""", jobId);
		jdbc.update("""
				INSERT INTO job_transicoes (job_id, status_anterior, status_novo, ocorrido_em, ator)
				VALUES (?, NULL, ?, now(), 'sistema')
				""", jobId, status.paraColuna());
		return jobId;
	}

}
