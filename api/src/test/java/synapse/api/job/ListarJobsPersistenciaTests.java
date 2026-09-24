package synapse.api.job;

import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.DriverManager;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import javax.sql.DataSource;

import org.jspecify.annotations.Nullable;

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
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.UsuarioAtual;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

/**
 * Sobe um Postgres real e executa {@link ListarJobsService} como {@code synapse_api}, o
 * que também prova os GRANTs concedidos nas migrations de {@code jobs}, {@code
 * simulacoes} e {@code resultados_simulacao} - nenhum é novo desta tarefa.
 */
@EnabledIf("dockerIsAvailable")
class ListarJobsPersistenciaTests {

	private static final UUID USUARIO = UUID.fromString("22222222-2222-4222-8222-222222222222");

	private static final JsonMapper JSON = new JsonMapper();

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static JdbcTemplate dono;

	private static ListarJobsService service;

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
				VALUES (?, 'rh-t078', 'x', 'RH', 'profissional_rh', '2026-01-01T00:00:00Z')
				""", USUARIO);
		contexto = new AnnotationConfigApplicationContext();
		contexto.registerBean(DataSource.class, () -> dataSource);
		contexto.registerBean(JdbcTemplate.class, () -> jdbc);
		contexto.registerBean(PlatformTransactionManager.class, () -> new DataSourceTransactionManager(dataSource));
		contexto.register(Config.class);
		contexto.refresh();
		service = contexto.getBean(ListarJobsService.class);
		UsuarioAtual usuarioAtual = mock(UsuarioAtual.class);
		when(usuarioAtual.obter()).thenReturn(new AcessoDoUsuario(USUARIO, false));
		mvc = MockMvcBuilders.standaloneSetup(new ListarJobsController(service, usuarioAtual))
			.setControllerAdvice(contexto.getBean(ListarJobsAdvice.class))
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
		dono.execute("TRUNCATE jobs CASCADE");
	}

	@TestConfiguration(proxyBeanMethods = false)
	@EnableTransactionManagement
	@Import({ ListarJobsService.class, ListarJobsAdvice.class })
	static class Config {

	}

	@Test
	void devolveVazioComTotalZeroQuandoNaoHaJob() {
		PaginaJobsDto pagina = service.listar(new ListarJobsRequisicao(0, 20));

		assertThat(pagina.itens()).isEmpty();
		assertThat(pagina.total()).isZero();
	}

	@Test
	void percorrerTodasAsPaginasCobreCadaJobUmaVezSemRepetirNemOmitir() {
		List<UUID> criados = List.of(criarJob("2026-01-01T10:00:00Z"), criarJob("2026-01-01T10:00:00Z"),
				criarJob("2026-01-02T10:00:00Z"), criarJob("2026-01-03T10:00:00Z"), criarJob("2026-01-04T10:00:00Z"));

		List<UUID> vistos = new java.util.ArrayList<>();
		for (int pagina = 0; pagina < 3; pagina++) {
			PaginaJobsDto resultado = service.listar(new ListarJobsRequisicao(pagina, 2));
			resultado.itens().forEach(item -> vistos.add(item.id()));
		}

		assertThat(vistos).hasSize(5).doesNotHaveDuplicates().containsExactlyInAnyOrderElementsOf(criados);
	}

	@Test
	void ordenaPorCriadoEmDecrescenteEEDesempataDeFormaEstavelEntreChamadas() {
		UUID a = criarJob("2026-01-01T10:00:00Z");
		UUID b = criarJob("2026-01-01T10:00:00Z");
		UUID c = criarJob("2026-01-02T10:00:00Z");

		List<UUID> primeiraChamada = service.listar(new ListarJobsRequisicao(0, 20))
			.itens()
			.stream()
			.map(JobResumoDto::id)
			.toList();
		List<UUID> segundaChamada = service.listar(new ListarJobsRequisicao(0, 20))
			.itens()
			.stream()
			.map(JobResumoDto::id)
			.toList();

		// c tem o criado_em mais recente e vem primeiro; a e b empatam e o desempate por
		// id
		// é estável entre chamadas - não repete nem troca de posição.
		assertThat(primeiraChamada).first().isEqualTo(c);
		assertThat(primeiraChamada).containsExactlyElementsOf(segundaChamada);
		assertThat(primeiraChamada.subList(1, 3)).containsExactlyInAnyOrder(a, b);
	}

	@Test
	void umaPaginaAlemDoFimDevolveItensVazioComOTotalCorreto() {
		criarJob("2026-01-01T10:00:00Z");

		PaginaJobsDto pagina = service.listar(new ListarJobsRequisicao(5, 20));

		assertThat(pagina.itens()).isEmpty();
		assertThat(pagina.total()).isEqualTo(1);
	}

	@Test
	void jobArquivadoContinuaAparecendoComFinalizadoEm() {
		UUID jobId = criarJob("2026-01-01T10:00:00Z");
		jdbc.update("UPDATE jobs SET status = 'arquivado', finalizado_em = ? WHERE id = ?",
				java.sql.Timestamp.from(Instant.parse("2026-01-01T11:00:00Z")), jobId);

		JobResumoDto item = itemUnico();
		assertThat(item.status()).isEqualTo("arquivado");
		assertThat(item.finalizado_em()).isEqualTo(Instant.parse("2026-01-01T11:00:00Z"));
	}

	@Test
	void semSimulacaoOVereditoFicaAusente() {
		criarJob("2026-01-01T10:00:00Z");

		assertThat(itemUnico().veredito()).isNull();
	}

	@Test
	void simulacaoSemResultadoOVereditoFicaAusente() {
		UUID jobId = criarJob("2026-01-01T10:00:00Z");
		criarSimulacao(jobId, "2026-01-01T10:01:00Z", null);

		assertThat(itemUnico().veredito()).isNull();
	}

	@Test
	void resultadoComSucessoTrazOVeredito() {
		UUID jobId = criarJob("2026-01-01T10:00:00Z");
		UUID resultadoId = criarResultado(jobId, "sucesso", "viavel");
		criarSimulacao(jobId, "2026-01-01T10:01:00Z", resultadoId);

		assertThat(itemUnico().veredito()).isEqualTo("viavel");
	}

	@Test
	void resultadoComErroDeCodigoNaoTemVeredito() {
		UUID jobId = criarJob("2026-01-01T10:00:00Z");
		UUID resultadoId = criarResultado(jobId, "erro_codigo", null);
		criarSimulacao(jobId, "2026-01-01T10:01:00Z", resultadoId);

		assertThat(itemUnico().veredito()).isNull();
	}

	@Test
	void simulacaoMaisNovaPendenteEscondeOVereditoDaMaisAntigaComSucesso() {
		UUID jobId = criarJob("2026-01-01T10:00:00Z");
		UUID resultadoAntigo = criarResultado(jobId, "sucesso", "viavel");
		criarSimulacao(jobId, "2026-01-01T10:01:00Z", resultadoAntigo);
		criarSimulacao(jobId, "2026-01-01T10:05:00Z", null);

		assertThat(itemUnico().veredito()).isNull();
	}

	@Test
	void jobReprocessadoTrazJobOrigemId() {
		UUID original = criarJob("2026-01-01T10:00:00Z");
		UUID reprocessado = criarJobReprocessado("2026-01-02T10:00:00Z", original);

		PaginaJobsDto pagina = service.listar(new ListarJobsRequisicao(0, 20));
		JobResumoDto item = pagina.itens().stream().filter(i -> i.id().equals(reprocessado)).findFirst().orElseThrow();
		assertThat(item.job_origem_id()).isEqualTo(original);

		JobResumoDto itemOriginal = pagina.itens()
			.stream()
			.filter(i -> i.id().equals(original))
			.findFirst()
			.orElseThrow();
		assertThat(itemOriginal.job_origem_id()).isNull();
	}

	@Test
	void httpDeVoltaAoNavegadorOmiteAusentesETrazPresentes() throws Exception {
		UUID jobId = criarJob("2026-01-01T10:00:00Z");
		UUID resultadoId = criarResultado(jobId, "sucesso", "inviavel");
		criarSimulacao(jobId, "2026-01-01T10:01:00Z", resultadoId);

		String resposta = mvc.perform(get("/jobs").accept(MediaType.APPLICATION_JSON))
			.andReturn()
			.getResponse()
			.getContentAsString();
		var no = JSON.readTree(resposta).path("itens").path(0);
		assertThat(no.propertyNames()).containsExactlyInAnyOrder("id", "status", "competencias", "orcamento",
				"veredito", "criado_em");
		assertThat(no.path("veredito").asString()).isEqualTo("inviavel");
	}

	private JobResumoDto itemUnico() {
		List<JobResumoDto> itens = service.listar(new ListarJobsRequisicao(0, 20)).itens();
		assertThat(itens).hasSize(1);
		return itens.getFirst();
	}

	private static UUID criarJob(String criadoEm) {
		return Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, competencias, orcamento, criado_em)
				VALUES ('aguardando_confirmacao_parametros', ?, ARRAY['2025-11'], 485000.0, ?)
				RETURNING id
				""", UUID.class, USUARIO, java.sql.Timestamp.from(Instant.parse(criadoEm))));
	}

	private static UUID criarJobReprocessado(String criadoEm, UUID jobOrigemId) {
		return Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, competencias, orcamento, job_origem_id, criado_em)
				VALUES ('aguardando_confirmacao_parametros', ?, ARRAY['2025-11'], 485000.0, ?, ?)
				RETURNING id
				""", UUID.class, USUARIO, jobOrigemId, java.sql.Timestamp.from(Instant.parse(criadoEm))));
	}

	private static UUID criarResultado(UUID jobId, String status, @Nullable String veredito) {
		UUID regraId = criarRegra(jobId);
		UUID codigoGeradoId = criarCodigoGerado(jobId, regraId);
		// resultados_simulacao só o worker escreve em produção (AGENTS.md); a fixture usa
		// o
		// usuário dono para simular o que ele já teria gravado.
		return Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, veredito, assercoes, criado_em)
				VALUES (?, ?, ?, ?, '[]'::jsonb, ?)
				RETURNING id
				""", UUID.class, jobId, codigoGeradoId, status, veredito, java.sql.Timestamp.from(Instant.now())));
	}

	private static UUID criarRegra(UUID jobId) {
		Integer proximaVersao = jdbc.queryForObject("SELECT COALESCE(MAX(versao), 0) + 1 FROM regras WHERE job_id = ?",
				Integer.class, jobId);
		String hash = String.format("%064x", proximaVersao);
		return Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES (?, ?, 'confirmacao_usuario', '{}'::jsonb, '[]'::jsonb, ?, ?)
				RETURNING id
				""", UUID.class, jobId, proximaVersao, hash, java.sql.Timestamp.from(Instant.now())));
	}

	// prompts e codigos_gerados só o codegen escreve em produção (AGENTS.md); a fixture
	// usa
	// o usuário dono para simular o que ele já teria gravado.
	private static UUID criarCodigoGerado(UUID jobId, UUID regraId) {
		UUID promptId = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
				VALUES (?, 'geracao_codigo', 'x', '{}'::jsonb, ?)
				RETURNING id
				""", UUID.class, jobId, java.sql.Timestamp.from(Instant.now())));
		return Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO codigos_gerados (job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES (?, ?, 'python', 'x', ?, ?)
				RETURNING id
				""", UUID.class, jobId, regraId, promptId, java.sql.Timestamp.from(Instant.now())));
	}

	private static void criarSimulacao(UUID jobId, String criadoEm, @Nullable UUID resultadoId) {
		UUID regraId = criarRegra(jobId);
		UUID codigoGeradoId = criarCodigoGerado(jobId, regraId);
		jdbc.update("""
				INSERT INTO simulacoes (criado_em, regra_id, job_id, codigo_gerado_id, resultado_id)
				VALUES (?, ?, ?, ?, ?)
				""", java.sql.Timestamp.from(Instant.parse(criadoEm)), regraId, jobId, codigoGeradoId, resultadoId);
	}

}
