package synapse.api.job;

import java.sql.Connection;
import java.sql.DriverManager;
import java.time.Instant;
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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.support.SqlArrayValue;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.security.UsuarioAtual;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Prova contra PostgreSQL real que a consulta de um job continua produzindo uma única
 * resposta quando existem várias versões de regra associadas.
 */
@EnabledIf("dockerIsAvailable")
class BuscarJobPersistenciaTests {

	private static final UUID USUARIO = UUID.fromString("55555555-5555-4555-8555-555555555555");

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static JdbcTemplate dono;

	private static BuscarJobService service;

	private static MockMvc mvc;

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
				VALUES (?, 'rh-t143', 'x', 'RH', 'profissional_rh', '2026-01-01T00:00:00Z')
				""", USUARIO);

		contexto = new AnnotationConfigApplicationContext();
		contexto.registerBean(DataSource.class, () -> dataSource);
		contexto.registerBean(JdbcTemplate.class, () -> jdbc);
		contexto.register(Config.class);
		contexto.refresh();
		service = contexto.getBean(BuscarJobService.class);
		UsuarioAtual usuarioAtual = mock(UsuarioAtual.class);
		when(usuarioAtual.obter()).thenReturn(new AcessoDoUsuario(USUARIO, PapelDoUsuario.PROFISSIONAL_RH));
		mvc = MockMvcBuilders.standaloneSetup(new BuscarJobController(service))
			.addInterceptors(new AutorizacaoJobsInterceptor(usuarioAtual, new AutorizadorDeJob(jdbc)))
			.setControllerAdvice(new BuscarJobAdvice(), new AutorizacaoDeJobAdvice())
			.build();
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
	void limpar() {
		dono.execute("TRUNCATE submissoes CASCADE");
	}

	@TestConfiguration(proxyBeanMethods = false)
	@Import({ BuscarJobService.class, AutorizadorDeJob.class })
	static class Config {

	}

	@Test
	void jobComDuasRegrasRetornaUmaRespostaComTodasAsVersoesOrdenadas() throws Exception {
		UUID jobId = criarJob();
		UUID regraV1 = criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		UUID regraV2 = criarRegra(jobId, 2, "0.03", "hash-v2", "2026-01-01T10:02:00Z");

		JobDetalhadoDto job = service.buscar(jobId);

		assertThat(job.id()).isEqualTo(jobId);
		assertThat(job.status()).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(job.origem()).isEqualTo("formulario");
		assertThat(job.competencias()).containsExactly("2025-11");
		assertThat(job.regras()).extracting(RegraCriadaDto::id).containsExactly(regraV1, regraV2);
		assertThat(job.regras()).extracting(RegraCriadaDto::versao).containsExactly(1, 2);
		assertThat(job.regras().get(0).representacao().nucleo().percentual()).isEqualByComparingTo("0.02");
		assertThat(job.regras().get(1).representacao().nucleo().percentual()).isEqualByComparingTo("0.03");

		mvc.perform(get("/jobs/{id}", jobId).accept(MediaType.APPLICATION_JSON))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.id").value(jobId.toString()))
			.andExpect(jsonPath("$.status").value("aguardando_confirmacao_parametros"))
			.andExpect(jsonPath("$.regras.length()").value(2))
			.andExpect(jsonPath("$.regras[0].id").value(regraV1.toString()))
			.andExpect(jsonPath("$.regras[0].versao").value(1))
			.andExpect(jsonPath("$.regras[1].id").value(regraV2.toString()))
			.andExpect(jsonPath("$.regras[1].versao").value(2))
			.andExpect(jsonPath("$.regra").doesNotExist());
	}

	private static UUID criarJob() {
		UUID submissaoId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, conteudo, criado_em)
				VALUES (?, 'formulario', '{}'::jsonb, '2026-01-01T10:00:00Z') RETURNING id
				""", UUID.class, USUARIO));
		return Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES ('aguardando_confirmacao_parametros', ?, ?, ?, 485000, '2026-01-01T10:00:00Z') RETURNING id
				""", UUID.class, USUARIO, submissaoId, new SqlArrayValue("text", List.of("2025-11").toArray())));
	}

	private static UUID criarRegra(UUID jobId, int versao, String percentual, String hash, String criadaEm) {
		String nucleo = """
				{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"loja":["13"],"marca":["10"],"cargo":["100"],"percentual":%s}
				"""
			.formatted(percentual);
		return Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES (?, ?, 'confirmacao_usuario', ?::jsonb, '[]'::jsonb, ?, ?::timestamptz) RETURNING id
				""", UUID.class, jobId, versao, nucleo, hash, criadaEm));
	}

}
