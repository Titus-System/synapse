package synapse.api.job;

import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.DriverManager;
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
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@EnabledIf("dockerIsAvailable")
class CriarJobPersistenciaTests {

	private static final UUID USUARIO = CriarJobControllerTests.USUARIO;

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static JdbcTemplate dono;

	private static CriarJobService service;

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
				VALUES (?, 'rh-t037', 'x', 'RH', 'profissional_rh', now())
				""", USUARIO);
		contexto = new AnnotationConfigApplicationContext();
		contexto.registerBean(DataSource.class, () -> dataSource);
		contexto.registerBean(JdbcTemplate.class, () -> jdbc);
		contexto.registerBean(PlatformTransactionManager.class, () -> new DataSourceTransactionManager(dataSource));
		contexto.register(Config.class);
		contexto.refresh();
		service = contexto.getBean(CriarJobService.class);
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
	@Import({ CriarJobService.class, MaquinaDeEstadosDoJob.class, CriarJobController.class, CriarJobAdvice.class })
	static class Config {

	}

	@Test
	void httpCriaAsTresLinhasComUsuarioDoPrincipalEFormularioOriginal() throws Exception {
		String corpo = CriarJobControllerTests.FORMULARIO
			.replace("\"origem\"", "\"user_id\":\"99999999-9999-4999-8999-999999999999\",\"origem\"")
			.replace("\"texto_livre\":null", "\"texto_livre\":\"Observação recebida\",\"extra\":{\"preservar\":true}")
			.replace("0.025", "0.025000000000000000001");
		var mvc = MockMvcBuilders.standaloneSetup(contexto.getBean(CriarJobController.class))
			.setControllerAdvice(contexto.getBean(CriarJobAdvice.class))
			.build();
		var resposta = mvc
			.perform(post("/jobs").principal(USUARIO::toString).contentType(MediaType.APPLICATION_JSON).content(corpo))
			.andExpect(status().isCreated())
			.andReturn()
			.getResponse();
		var job = JSON.readTree(resposta.getContentAsString());
		UUID jobId = UUID.fromString(job.path("id").asString());
		UUID submissaoId = UUID.fromString(job.path("submissao_id").asString());
		UUID regraId = UUID.fromString(job.path("regra").path("id").asString());
		assertThat(resposta.getHeader("Location")).isEqualTo("/api/jobs/" + jobId);

		Map<String, Object> submissao = jdbc.queryForMap("SELECT * FROM submissoes WHERE id = ?", submissaoId);
		assertThat(submissao).containsEntry("usuario_id", USUARIO)
			.containsEntry("tipo", "formulario")
			.containsEntry("binario", null)
			.containsEntry("formato", null)
			.containsEntry("transcricao", null)
			.containsEntry("transcrito_em", null);
		assertThat(JSON.readTree(Objects.requireNonNull(submissao.get("conteudo")).toString()))
			.isEqualTo(JSON.readTree(corpo).path("conteudo"));

		Map<String, Object> persistido = jdbc.queryForMap("SELECT * FROM jobs WHERE id = ?", jobId);
		assertThat(persistido).containsEntry("usuario_id", USUARIO)
			.containsEntry("submissao_id", submissaoId)
			.containsEntry("status", "aguardando_confirmacao_parametros")
			.containsEntry("tentativas", 0)
			.containsEntry("iniciado_em", null)
			.containsEntry("finalizado_em", null)
			.containsEntry("job_origem_id", null);
		assertThat(persistido.get("orcamento")).isEqualTo(new BigDecimal("485000.1234567890123456789"));
		assertThat(job.path("orcamento").decimalValue()).isEqualByComparingTo("485000.1234567890123456789");
		assertThat(competencias(jobId)).containsExactly("2025-11");

		Map<String, Object> regra = jdbc.queryForMap("SELECT * FROM regras WHERE id = ?", regraId);
		assertThat(regra).containsEntry("job_id", jobId)
			.containsEntry("versao", 1)
			.containsEntry("origem", "confirmacao_usuario")
			.containsEntry("regra_origem_id", null)
			.containsEntry("criada_em", persistido.get("criado_em"));
		assertThat(JSON.readTree(Objects.requireNonNull(regra.get("nucleo")).toString()))
			.isEqualTo(JSON.readTree(corpo).path("conteudo").path("nucleo"));
		assertThat(Objects.requireNonNull(regra.get("especificacoes")).toString()).isEqualTo("[]");
		assertThat(regra.get("hash")).isEqualTo(HashDaRegra.calcular(CriarJobRequisicao.deJson(corpo).representacao()));
		assertThat(submissao.get("criado_em")).isEqualTo(persistido.get("criado_em"));
		assertThat(jdbc.queryForObject(
				"SELECT count(*) FROM job_transicoes WHERE job_id = ? AND status_anterior IS NULL AND ator = 'usuario'",
				Integer.class, jobId))
			.isEqualTo(1);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId))
			.isZero();
	}

	@Test
	void ausenciaDeCompetenciasPersisteOsSeisMeses() {
		JobCriadoDto job = service.criar(USUARIO, CriarJobRequisicao
			.deJson(CriarJobControllerTests.FORMULARIO.replace("\"competencias\":[\"2025-11\"],", "")));
		assertThat(competencias(job.id())).containsExactly("2025-07", "2025-08", "2025-09", "2025-10", "2025-11",
				"2025-12");
		assertThat(job.competencias()).containsExactlyElementsOf(competencias(job.id()));
	}

	@Test
	void ordenaCompetenciasAntesDePersistir() {
		JobCriadoDto job = service.criar(USUARIO, CriarJobRequisicao.deJson(
				CriarJobControllerTests.FORMULARIO.replace("[\"2025-11\"]", "[\"2025-12\",\"2025-07\",\"2025-09\"]")));
		assertThat(competencias(job.id())).containsExactly("2025-07", "2025-09", "2025-12");
	}

	@Test
	void listasVaziasRepresentamTodosConformeSchema() {
		JobCriadoDto job = service.criar(USUARIO,
				CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO.replace("[\"13\"]", "[]")
					.replace("[\"10\",\"20\"]", "[]")
					.replace("[\"100\",\"300\"]", "[]")));
		assertThat(job.regra().representacao().nucleo().loja()).isEmpty();
		assertThat(job.regra().representacao().nucleo().marca()).isEmpty();
		assertThat(job.regra().representacao().nucleo().cargo()).isEmpty();
	}

	@Test
	void falhaNoInsertDaRegraReverteSubmissaoJobETransicao() {
		Map<String, Object> antes = contagens();
		dono.execute("REVOKE INSERT ON regras FROM synapse_api");
		try {
			assertThatThrownBy(
					() -> service.criar(USUARIO, CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO)))
				.isInstanceOf(DataAccessException.class)
				.hasMessageContaining("INSERT INTO regras");
		}
		finally {
			dono.execute("GRANT INSERT ON regras TO synapse_api");
		}
		assertThat(contagens()).isEqualTo(antes);
	}

	private static List<String> competencias(UUID jobId) {
		return jdbc.queryForList("SELECT unnest(competencias) FROM jobs WHERE id = ?", String.class, jobId);
	}

	private static Map<String, Object> contagens() {
		return jdbc.queryForMap("""
				SELECT (SELECT count(*) FROM submissoes) AS submissoes,
				       (SELECT count(*) FROM jobs) AS jobs,
				       (SELECT count(*) FROM regras) AS regras,
				       (SELECT count(*) FROM job_transicoes) AS transicoes
				""");
	}

}
