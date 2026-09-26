package synapse.api.job;

import java.sql.Connection;
import java.sql.DriverManager;
import java.util.List;
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

import synapse.api.core.outbox.Outbox;
import synapse.api.job.SugestaoAdaptacaoService.SugestaoAplicada;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * A adaptação do lado da api: a versão proposta é gravada e o job volta a
 * {@code gerando_regra}, de onde uma simulação nova é obrigatória.
 */
@EnabledIf("dockerIsAvailable")
class SugestaoAdaptacaoPersistenciaTests {

	private static final UUID USUARIO = CriarJobControllerTests.USUARIO;

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static CriarJobService criarService;

	private static SugestaoAdaptacaoService sugestaoService;

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
		JdbcTemplate dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		DataSource dataSource = new DriverManagerDataSource(postgres.getJdbcUrl(), "synapse_api", "senha-de-teste");
		jdbc = new JdbcTemplate(dataSource);
		jdbc.update("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES (?, 'rh-us03', 'x', 'RH', 'profissional_rh', '2026-01-02T00:00:00Z')
				""", USUARIO);
		contexto = new AnnotationConfigApplicationContext();
		contexto.registerBean(DataSource.class, () -> dataSource);
		contexto.registerBean(JdbcTemplate.class, () -> jdbc);
		contexto.registerBean(PlatformTransactionManager.class, () -> new DataSourceTransactionManager(dataSource));
		contexto.register(Config.class);
		contexto.refresh();
		criarService = contexto.getBean(CriarJobService.class);
		sugestaoService = contexto.getBean(SugestaoAdaptacaoService.class);
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

	@TestConfiguration(proxyBeanMethods = false)
	@EnableTransactionManagement
	@Import({ CriarJobService.class, SugestaoAdaptacaoService.class, MaquinaDeEstadosDoJob.class, Outbox.class,
			VersoesDaRegra.class })
	static class Config {

	}

	@Test
	void gravaAVersaoSugeridaDerivadaDaQueNaoCoube() {
		UUID jobId = jobInviavel();
		UUID origem = versaoId(jobId, 1);

		SugestaoAplicada aplicada = sugestaoService.aplicar(jobId, origem, representacao("0.0246"));

		assertThat(aplicada.versao().versao()).isEqualTo(2);
		assertThat(aplicada.versao().origem()).isEqualTo("sugestao_adaptacao");
		assertThat(
				jdbc.queryForObject("SELECT origem FROM regras WHERE job_id = ? AND versao = 2", String.class, jobId))
			.isEqualTo("sugestao_adaptacao");
		assertThat(jdbc.queryForObject("SELECT regra_origem_id FROM regras WHERE job_id = ? AND versao = 2", UUID.class,
				jobId))
			.isEqualTo(origem);
		assertThat(percentual(jobId, 1)).isEqualTo("0.025");
		assertThat(percentual(jobId, 2)).isEqualTo("0.0246");
	}

	@Test
	void reabreOCicloDeGeracaoEPublicaParametrosConfirmados() {
		UUID jobId = jobInviavel();

		SugestaoAplicada aplicada = sugestaoService.aplicar(jobId, versaoId(jobId, 1), representacao("0.0246"));

		assertThat(aplicada.origem()).isEqualTo(JobStatus.SIMULACAO_INVIAVEL);
		assertThat(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId))
			.isEqualTo("gerando_regra");
		assertThat(jdbc.queryForObject("""
				SELECT count(*) FROM job_transicoes
				WHERE job_id = ? AND status_anterior = 'simulacao_inviavel' AND status_novo = 'gerando_regra'
				AND ator = 'evento' AND motivo = 'sugestao_adaptacao_proposta'
				""", Integer.class, jobId)).isEqualTo(1);
		assertThat(jdbc.queryForObject("""
				SELECT payload->>'regra_id' FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'
				""", String.class, jobId)).isEqualTo(aplicada.versao().id().toString());
	}

	@Test
	void reentregaDaMesmaPropostaNaoDuplicaVersaoNemEvento() {
		UUID jobId = jobInviavel();
		UUID origem = versaoId(jobId, 1);
		sugestaoService.aplicar(jobId, origem, representacao("0.0246"));

		assertThatThrownBy(() -> sugestaoService.aplicar(jobId, origem, representacao("0.0246")))
			.isInstanceOf(TransicaoDeStatusInvalidaException.class);

		assertThat(versoes(jobId)).isEqualTo(2);
		assertThat(jdbc.queryForObject("""
				SELECT count(*) FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'
				""", Integer.class, jobId)).isEqualTo(1);
	}

	@Test
	void propostaIgualAUmaVersaoExistenteReaproveitaALinha() {
		UUID jobId = jobInviavel();
		UUID origem = versaoId(jobId, 1);

		SugestaoAplicada aplicada = sugestaoService.aplicar(jobId, origem, representacao("0.025"));

		assertThat(aplicada.versao().id()).isEqualTo(origem);
		assertThat(aplicada.versao().origem()).isEqualTo("confirmacao_usuario");
		assertThat(versoes(jobId)).isEqualTo(1);
	}

	@Test
	void naoAceitaPropostaParaJobQueNaoEstaEmSimulacaoInviavel() {
		UUID jobId = criarService.criar(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO)).id();

		assertThatThrownBy(() -> sugestaoService.aplicar(jobId, versaoId(jobId, 1), representacao("0.0246")))
			.isInstanceOf(TransicaoDeStatusInvalidaException.class);

		assertThat(versoes(jobId)).isEqualTo(1);
	}

	private static UUID jobInviavel() {
		UUID jobId = criarService.criar(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO)).id();
		jdbc.update("UPDATE jobs SET status = 'simulacao_inviavel' WHERE id = ?", jobId);
		return jobId;
	}

	private static RepresentacaoRegraDto representacao(String percentual) {
		return new RepresentacaoRegraDto(new NucleoRegraDto(new VigenciaDto("2025-11", "2025-11"), List.of("13"),
				List.of("10", "20"), List.of("100", "300"), new java.math.BigDecimal(percentual)), List.of());
	}

	private static UUID versaoId(UUID jobId, int versao) {
		return Objects.requireNonNull(jdbc.queryForObject("SELECT id FROM regras WHERE job_id = ? AND versao = ?",
				UUID.class, jobId, versao));
	}

	private static String percentual(UUID jobId, int versao) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT nucleo->>'percentual' FROM regras WHERE job_id = ? AND versao = ?",
						String.class, jobId, versao));
	}

	private static int versoes(UUID jobId) {
		Integer total = jdbc.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Integer.class, jobId);
		return (total != null) ? total : 0;
	}

}
