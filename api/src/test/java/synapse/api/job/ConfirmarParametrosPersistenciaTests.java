package synapse.api.job;

import java.math.BigDecimal;
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
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.outbox.Outbox;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

@EnabledIf("dockerIsAvailable")
class ConfirmarParametrosPersistenciaTests {

	private static final UUID USUARIO = CriarJobControllerTests.USUARIO;

	private static final JsonMapper JSON = new JsonMapper();

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static JobService service;

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
				VALUES (?, 'rh-t041', 'x', 'RH', 'profissional_rh', '2026-01-02T00:00:00Z')
				""", USUARIO);
		contexto = new AnnotationConfigApplicationContext();
		contexto.registerBean(DataSource.class, () -> dataSource);
		contexto.registerBean(JdbcTemplate.class, () -> jdbc);
		contexto.registerBean(PlatformTransactionManager.class, () -> new DataSourceTransactionManager(dataSource));
		contexto.registerBean(EmissoresSse.class, () -> mock(EmissoresSse.class));
		contexto.register(Config.class);
		contexto.refresh();
		service = contexto.getBean(JobService.class);
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
	@Import({ JobRepository.class, JobService.class, MaquinaDeEstadosDoJob.class, Outbox.class, VersoesDaRegra.class,
			CorrelationContext.class })
	static class Config {

	}

	@Test
	void confirmarComEdicaoGravaVersaoNovaEventoETrilha() {
		UUID jobId = criarJob();
		JobCriadoDto confirmado = confirmar(jobId, corpo("0.03"));

		assertThat(confirmado.status()).isEqualTo("gerando_regra");
		assertThat(confirmado.regra().versao()).isEqualTo(2);
		assertThat(confirmado.regra().representacao().nucleo().percentual()).isEqualByComparingTo("0.03");

		assertThat(versoes(jobId)).isEqualTo(2);
		assertThat(percentual(jobId, 1)).isEqualTo("0.025");
		assertThat(percentual(jobId, 2)).isEqualTo("0.03");
		assertThat(jdbc.queryForObject("SELECT regra_origem_id FROM regras WHERE job_id = ? AND versao = 2", UUID.class,
				jobId))
			.isNotNull();

		assertThat(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId))
			.isEqualTo("gerando_regra");
		assertThat(jdbc.queryForObject("""
				SELECT count(*) FROM job_transicoes
				WHERE job_id = ? AND status_anterior = 'aguardando_confirmacao_parametros'
				AND status_novo = 'gerando_regra' AND ator = 'usuario'
				""", Integer.class, jobId)).isEqualTo(1);

		assertThat(jdbc.queryForObject("""
				SELECT count(*) FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'
				""", Integer.class, jobId)).isEqualTo(1);
		assertThat(jdbc.queryForObject("""
				SELECT payload->>'regra_id' FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'
				""", String.class, jobId)).isEqualTo(confirmado.regra().id().toString());

		assertThat(jdbc.queryForObject("SELECT no FROM trilhas_auditoria WHERE job_id = ?", String.class, jobId))
			.isEqualTo("confirmacao");
		assertThat(
				jdbc.queryForObject("SELECT conclusao->>'editado_pelo_usuario' FROM trilhas_auditoria WHERE job_id = ?",
						String.class, jobId))
			.isEqualTo("true");
		assertThat(jdbc.queryForObject("SELECT conclusao->'campos_corrigidos' FROM trilhas_auditoria WHERE job_id = ?",
				String.class, jobId))
			.contains("nucleo.percentual");
	}

	/**
	 * Uma versão anterior com parâmetros - o caso de um job de texto reprocessado, cujo
	 * row 1 chega com {@code parametros} e um hash que os cobre - não pode parecer
	 * editada quando o usuário confirma a mesma representação. Sem carregar os parâmetros
	 * anteriores para o cálculo do hash novo, ele nunca bateria com o hash salvo, e toda
	 * confirmação sem edição criaria uma versão espúria com a trilha dizendo que houve
	 * correção.
	 */
	@Test
	void confirmarSemEdicaoNaoCriaVersaoQuandoAAnteriorTemParametros() {
		UUID jobId = criarJob();
		RepresentacaoRegraDto repr = CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao();
		ParametrosDaSimulacao params = new ParametrosDaSimulacao(new BigDecimal("500000"), null,
				List.of("2025-09", "2025-10"));
		String hashComParametros = HashDaRegra.calcular(repr, params);
		comoDono().update("UPDATE regras SET hash = ?, parametros = ?::jsonb WHERE job_id = ? AND versao = 1",
				hashComParametros, "{\"orcamento\":500000,\"competencias\":[\"2025-09\",\"2025-10\"]}", jobId);

		JobCriadoDto confirmado = confirmar(jobId, corpo("0.025"));

		assertThat(confirmado.regra().versao()).isEqualTo(1);
		assertThat(versoes(jobId)).isEqualTo(1);
		assertThat(parametros(jobId, 1))
			.isEqualTo(JSON.readTree("{\"orcamento\":500000,\"competencias\":[\"2025-09\",\"2025-10\"]}"));
		assertThat(
				jdbc.queryForObject("SELECT conclusao->>'editado_pelo_usuario' FROM trilhas_auditoria WHERE job_id = ?",
						String.class, jobId))
			.isEqualTo("false");
	}

	/**
	 * A mesma versão anterior com parâmetros, agora editada: a versão nova carrega os
	 * parâmetros da anterior inalterados (T-217 ainda não existe para mudá-los por aqui),
	 * e o hash os cobre, consistente com a coluna.
	 */
	@Test
	void confirmarComEdicaoCarregaOsParametrosDaVersaoAnteriorParaANova() {
		UUID jobId = criarJob();
		RepresentacaoRegraDto repr = CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao();
		ParametrosDaSimulacao params = new ParametrosDaSimulacao(new BigDecimal("500000"), null,
				List.of("2025-09", "2025-10"));
		comoDono().update("UPDATE regras SET hash = ?, parametros = ?::jsonb WHERE job_id = ? AND versao = 1",
				HashDaRegra.calcular(repr, params), "{\"orcamento\":500000,\"competencias\":[\"2025-09\",\"2025-10\"]}",
				jobId);

		JobCriadoDto confirmado = confirmar(jobId, corpo("0.03"));

		assertThat(confirmado.regra().versao()).isEqualTo(2);
		assertThat(parametros(jobId, 2))
			.isEqualTo(JSON.readTree("{\"orcamento\":500000,\"competencias\":[\"2025-09\",\"2025-10\"]}"));
		assertThat(jdbc.queryForObject("SELECT hash FROM regras WHERE job_id = ? AND versao = 2", String.class, jobId))
			.isEqualTo(
					HashDaRegra.calcular(ConfirmarParametrosRequisicao.deJson(corpo("0.03")).representacao(), params));
	}

	private static JdbcTemplate comoDono() {
		return new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
	}

	@Test
	void confirmarSemEdicaoNaoCriaNovaVersao() {
		UUID jobId = criarJob();
		JobCriadoDto confirmado = confirmar(jobId, corpo("0.025"));

		assertThat(confirmado.regra().versao()).isEqualTo(1);
		assertThat(versoes(jobId)).isEqualTo(1);
		assertThat(jdbc.queryForObject("""
				SELECT payload->>'regra_id' FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'
				""", String.class, jobId)).isEqualTo(confirmado.regra().id().toString());
		assertThat(
				jdbc.queryForObject("SELECT conclusao->>'editado_pelo_usuario' FROM trilhas_auditoria WHERE job_id = ?",
						String.class, jobId))
			.isEqualTo("false");
	}

	@Test
	void confirmarDuasVezesProduzVersoesDistintasComAPrimeiraIntacta() {
		UUID jobId = criarJob();
		confirmar(jobId, corpo("0.03"));
		voltarParaConfirmacao(jobId);
		confirmar(jobId, corpo("0.04"));

		assertThat(versoes(jobId)).isEqualTo(3);
		assertThat(percentual(jobId, 1)).isEqualTo("0.025");
		assertThat(percentual(jobId, 2)).isEqualTo("0.03");
		assertThat(percentual(jobId, 3)).isEqualTo("0.04");
	}

	@Test
	void confirmarEmEstadoInvalidoERecusadoSemEfeito() {
		UUID jobId = criarJob();
		confirmar(jobId, corpo("0.03"));

		int versoesAntes = versoes(jobId);
		Integer outboxAntes = jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class,
				jobId);

		assertThatThrownBy(() -> confirmar(jobId, corpo("0.04")))
			.isInstanceOf(TransicaoDeStatusInvalidaException.class);

		assertThat(versoes(jobId)).isEqualTo(versoesAntes);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(outboxAntes);
		assertThat(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId))
			.isEqualTo("gerando_regra");
	}

	@Test
	void confirmarAjustaOrcamentoECompetencias() {
		UUID jobId = criarJob();
		JobCriadoDto confirmado = confirmar(jobId, """
				{"regra":{"nucleo":{"vigencia":{"inicio":"2025-11","fim":"2025-11"},
				"loja":["13"],"marca":["10","20"],"cargo":["100","300"],"percentual":0.03},"especificacoes":[]},
				"orcamento":600000.0,"competencias":["2025-10","2025-09"]}
				""");

		assertThat(confirmado.orcamento()).isEqualByComparingTo("600000.0");
		assertThat(confirmado.competencias()).containsExactly("2025-09", "2025-10");
		assertThat(jdbc.queryForObject("SELECT orcamento FROM jobs WHERE id = ?", BigDecimal.class, jobId))
			.isEqualByComparingTo("600000.0");
		assertThat(jdbc.queryForList("SELECT unnest(competencias) FROM jobs WHERE id = ?", String.class, jobId))
			.containsExactly("2025-09", "2025-10");
	}

	@Test
	void versaoDeRegraNaoPodeSerAlteradaNemRemovidaPelaApi() {
		UUID jobId = criarJob();
		UUID versaoId = Objects.requireNonNull(
				jdbc.queryForObject("SELECT id FROM regras WHERE job_id = ? AND versao = 1", UUID.class, jobId));

		assertThatThrownBy(() -> jdbc.update("UPDATE regras SET hash = ? WHERE id = ?", "0".repeat(64), versaoId))
			.isInstanceOf(DataAccessException.class);
		assertThatThrownBy(() -> jdbc.update("DELETE FROM regras WHERE id = ?", versaoId))
			.isInstanceOf(DataAccessException.class);

		assertThat(percentual(jobId, 1)).isEqualTo("0.025");
	}

	// Submissão de formulário não passa mais por aguardando_confirmacao_parametros;
	// voltarParaConfirmacao simula o estado de uma origem que ainda precisa dela.
	private static UUID criarJob() {
		UUID jobId = service.criar(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO)).id();
		voltarParaConfirmacao(jobId);
		return jobId;
	}

	private static JobCriadoDto confirmar(UUID jobId, String corpo) {
		return service.confirmar(jobId, ConfirmarParametrosRequisicao.deJson(corpo));
	}

	private static String corpo(String percentual) {
		return """
				{"regra":{"nucleo":{"vigencia":{"inicio":"2025-11","fim":"2025-11"},
				"loja":["13"],"marca":["10","20"],"cargo":["100","300"],"percentual":%s},"especificacoes":[]}}
				""".formatted(percentual);
	}

	private static int versoes(UUID jobId) {
		Integer total = jdbc.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Integer.class, jobId);
		return (total != null) ? total : 0;
	}

	private static String percentual(UUID jobId, int versao) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT nucleo->>'percentual' FROM regras WHERE job_id = ? AND versao = ?",
						String.class, jobId, versao));
	}

	/** Comparado como árvore, nunca como texto: jsonb não preserva a ordem das chaves. */
	private static JsonNode parametros(UUID jobId, int versao) {
		return JSON.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"SELECT parametros::text FROM regras WHERE job_id = ? AND versao = ?", String.class, jobId, versao)));
	}

	private static void voltarParaConfirmacao(UUID jobId) {
		jdbc.update("UPDATE jobs SET status = 'aguardando_confirmacao_parametros' WHERE id = ?", jobId);
	}

}
