package synapse.api.job;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.util.List;
import java.util.UUID;
import java.util.Objects;

import javax.sql.DataSource;

import liquibase.Contexts;
import liquibase.Liquibase;
import liquibase.database.DatabaseFactory;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.ClassLoaderResourceAccessor;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.outbox.Outbox;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.security.UsuarioAtual;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@EnabledIf("dockerIsAvailable")
class RenomearJobPersistenciaTests {

	private static final UUID A = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final UUID B = UUID.fromString("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");

	private static final String TEXTO_LONGO = "  Bônus de   vendas\n\n para o\ttrimestre com meta ambiciosa e comissão extra para a equipe  ";

	private static final String NOME_PADRAO_LONGO = "Bônus de vendas para o trimestre com meta ambicios";

	private static final JsonMapper JSON = JsonMapper.builder().build();

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate dono;

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
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		// O serviço roda com o usuário real da api, para provar que ele tem permissão de
		// gravar nome.
		DataSource dataSource = new DriverManagerDataSource(postgres.getJdbcUrl(), "synapse_api", "senha-de-teste");
		JdbcTemplate jdbc = new JdbcTemplate(dataSource);
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
	@Import({ JobRepository.class, JobService.class, MaquinaDeEstadosDoJob.class, Outbox.class, JobAdvice.class,
			VersoesDaRegra.class, CorrelationContext.class, RodadasRepository.class })
	static class Config {

	}

	@BeforeEach
	void prepararUsuarios() {
		dono.execute("TRUNCATE usuarios CASCADE");
		dono.update("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES (?, 'a', 'x', 'A', 'profissional_rh', now()),
				       (?, 'b', 'x', 'B', 'profissional_rh', now())
				""", A, B);
	}

	// ---- renomeação ----

	@Test
	void renomeiaJobArquivadoSemTocarEstadoTransicoesAcoesTrilhasNemOutbox() throws Exception {
		UUID job = job(A, null, null, "Original");
		String jobAntes = jobSemNome(job);
		String contagensAntes = contagens();

		JsonNode resposta = corpo(renomear(rh(A), job, "{\"nome\":\"  Meu nome  \"}").andExpect(status().isOk()));

		assertThat(resposta.path("id").asString()).isEqualTo(job.toString());
		assertThat(resposta.path("status").asString()).isEqualTo("arquivado");
		assertThat(resposta.path("nome").asString()).isEqualTo("Meu nome");
		assertThat(nomeGravado(job)).isEqualTo("Meu nome");
		assertThat(jobSemNome(job)).isEqualTo(jobAntes);
		assertThat(contagens()).isEqualTo(contagensAntes);
	}

	@Test
	void nomeDefinidoVenceOPadraoNaListagemENaConsulta() throws Exception {
		UUID job = job(A, submissao(A, "texto", TEXTO_LONGO), null, null);
		assertNome(A, job, NOME_PADRAO_LONGO);

		renomear(rh(A), job, "{\"nome\":\"Nome do usuário\"}").andExpect(status().isOk());

		assertNome(A, job, "Nome do usuário");
	}

	@ParameterizedTest
	@ValueSource(strings = { "{}", "{\"nome\":null}", "{\"nome\":123}", "{\"nome\":{}}", "{\"nome\":\"\"}",
			"{\"nome\":\"   \"}", "[]", "{" })
	void recusaNomeInvalidoSemGravarNada(String corpo) throws Exception {
		UUID job = job(A, null, null, "Original");
		String contagensAntes = contagens();

		renomear(rh(A), job, corpo).andExpect(status().isBadRequest());

		assertThat(nomeGravado(job)).isEqualTo("Original");
		assertThat(contagens()).isEqualTo(contagensAntes);
	}

	@Test
	void recusaNomeAcimaDeCemPontosDeCodigoEAceitaCem() throws Exception {
		UUID job = job(A, null, null, "Original");

		renomear(rh(A), job, "{\"nome\":\"" + "a".repeat(101) + "\"}").andExpect(status().isBadRequest());
		assertThat(nomeGravado(job)).isEqualTo("Original");

		String cemEmojis = "😀".repeat(100);
		renomear(rh(A), job, "{\"nome\":\"" + cemEmojis + "\"}").andExpect(status().isOk());
		assertThat(nomeGravado(job)).isEqualTo(cemEmojis);
	}

	@Test
	void jobDeOutroUsuarioEhRecusadoSemGravar() throws Exception {
		UUID job = job(A, null, null, "Original");

		renomear(rh(B), job, "{\"nome\":\"Invasor\"}").andExpect(status().isForbidden());

		assertThat(nomeGravado(job)).isEqualTo("Original");
	}

	@Test
	void usuarioSemPapelDeRhEhRecusadoSemGravar() throws Exception {
		UUID job = job(A, null, null, "Original");

		renomear(new AcessoDoUsuario(A, PapelDoUsuario.AUDITOR), job, "{\"nome\":\"Auditor\"}")
			.andExpect(status().isForbidden());

		assertThat(nomeGravado(job)).isEqualTo("Original");
	}

	@Test
	void jobInexistenteResponde404() throws Exception {
		renomear(rh(A), UUID.randomUUID(), "{\"nome\":\"Qualquer\"}").andExpect(status().isNotFound());
	}

	// ---- resolução do nome padrão ----

	@Test
	void textoLongoDevolveOsCinquentaPrimeirosCaracteresNormalizados() throws Exception {
		UUID job = job(A, submissao(A, "texto", TEXTO_LONGO), null, null);

		assertNome(A, job, NOME_PADRAO_LONGO);
	}

	@Test
	void textoCurtoDevolveOTextoNormalizadoInteiro() throws Exception {
		UUID job = job(A, submissao(A, "texto", "  Texto\tcurto  \n"), null, null);

		assertNome(A, job, "Texto curto");
	}

	@Test
	void emojiNaQuinquagesimaPosicaoNaoEhCortadoAoMeio() throws Exception {
		String texto = "a".repeat(49) + "😀" + "zzz";
		UUID job = job(A, submissao(A, "texto", texto), null, null);

		assertNome(A, job, "a".repeat(49) + "😀");
	}

	@Test
	void jobSemTextoInicialRespondeSemNome() throws Exception {
		UUID formulario = job(A, submissao(A, "formulario", null), null, null);
		UUID vozSemTranscricao = job(A, submissao(A, "voz", null), null, null);
		UUID soEspacos = job(A, submissao(A, "texto", "  \t\n "), null, null);

		assertNome(A, formulario, null);
		assertNome(A, vozSemTranscricao, null);
		assertNome(A, soEspacos, null);
	}

	@Test
	void jobReprocessadoUsaOTextoDoPrimeiroJobDaCadeia() throws Exception {
		UUID raiz = job(A, submissao(A, "texto", TEXTO_LONGO), null, null);
		UUID filho = job(A, null, raiz, null);
		UUID neto = job(A, null, filho, null);

		assertNome(A, raiz, NOME_PADRAO_LONGO);
		assertNome(A, filho, NOME_PADRAO_LONGO);
		assertNome(A, neto, NOME_PADRAO_LONGO);
	}

	@Test
	void correcaoGravadaEmOutraSubmissaoNaoAlteraONomePadraoDoJob() throws Exception {
		UUID job = job(A, submissao(A, "texto", TEXTO_LONGO), null, null);
		UUID analisada = regra(job, 1, "extracao", null);
		UUID correcao = submissao(A, "texto", "Texto de uma correção gravada em outra submissão");
		UUID resultante = regra(job, 2, "correcao", analisada);
		rodadaCorrigida(job, analisada, correcao, resultante);

		assertNome(A, job, NOME_PADRAO_LONGO);
	}

	// ---- reprocessamento ----

	@Test
	void reprocessarCopiaONomeDefinidoEOsDoisPassamAVariarSeparados() throws Exception {
		UUID origem = job(A, submissao(A, "texto", TEXTO_LONGO), null, "Meu teste");
		regra(origem);

		UUID novo = service.reprocessar(origem, ReprocessarJobRequisicao.deJson(null)).id();

		assertThat(nomeGravado(novo)).isEqualTo("Meu teste");
		assertThat(contagem("SELECT count(*) FROM jobs WHERE job_origem_id = ?", origem)).isEqualTo(1);

		renomear(rh(A), novo, "{\"nome\":\"Novo nome\"}").andExpect(status().isOk());
		assertThat(nomeGravado(origem)).isEqualTo("Meu teste");
		assertThat(nomeGravado(novo)).isEqualTo("Novo nome");

		renomear(rh(A), origem, "{\"nome\":\"Outro nome\"}").andExpect(status().isOk());
		assertThat(nomeGravado(origem)).isEqualTo("Outro nome");
		assertThat(nomeGravado(novo)).isEqualTo("Novo nome");
	}

	@Test
	void reprocessarSemNomeDefinidoNaoGravaONomePadrao() throws Exception {
		UUID origem = job(A, submissao(A, "texto", TEXTO_LONGO), null, null);
		regra(origem);

		UUID novo = service.reprocessar(origem, ReprocessarJobRequisicao.deJson(null)).id();

		assertThat(nomeGravado(novo)).isNull();
		assertNome(A, novo, NOME_PADRAO_LONGO);
	}

	// ---- auxiliares ----

	private static AcessoDoUsuario rh(UUID usuario) {
		return new AcessoDoUsuario(usuario, PapelDoUsuario.PROFISSIONAL_RH);
	}

	private static MockMvc mvc(AcessoDoUsuario acesso) {
		UsuarioAtual usuarioAtual = mock(UsuarioAtual.class);
		when(usuarioAtual.obter()).thenReturn(acesso);
		return MockMvcBuilders
			.standaloneSetup(new JobController(service, mock(EmissoresSse.class), new CorrelationContext(),
					mock(AppMetrics.class)))
			.addInterceptors(new AutorizacaoJobsInterceptor(usuarioAtual,
					new AutorizadorDeJob(contexto.getBean(JobRepository.class))))
			.setControllerAdvice(contexto.getBean(JobAdvice.class), new AutorizacaoDeJobAdvice())
			.build();
	}

	private static ResultActions renomear(AcessoDoUsuario acesso, UUID job, String corpo) throws Exception {
		return mvc(acesso)
			.perform(put("/jobs/" + job + "/nome").contentType(MediaType.APPLICATION_JSON).content(corpo));
	}

	private static JsonNode corpo(ResultActions resultado) throws Exception {
		return JSON.readTree(resultado.andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8));
	}

	private static JsonNode itemDaListagem(JsonNode pagina, UUID job) {
		for (JsonNode candidato : pagina.path("itens")) {
			if (candidato.path("id").asString().equals(job.toString())) {
				return candidato;
			}
		}
		throw new AssertionError("job " + job + " ausente da listagem");
	}

	/**
	 * A listagem e a consulta precisam devolver o mesmo nome; {@code null} é o campo
	 * ausente.
	 */
	private static void assertNome(UUID usuario, UUID job, @Nullable String esperado) throws Exception {
		MockMvc mvc = mvc(rh(usuario));
		JsonNode detalhe = corpo(mvc.perform(get("/jobs/" + job)).andExpect(status().isOk()));
		JsonNode pagina = corpo(mvc.perform(get("/jobs")).andExpect(status().isOk()));
		ContratoDeEvento.validarRespostaHttp("PaginaJobs", pagina.toString());
		ContratoDeEvento.validarRespostaHttp("JobDetalhado", detalhe.toString());
		JsonNode item = itemDaListagem(pagina, job);
		if (esperado == null) {
			assertThat(detalhe.has("nome")).isFalse();
			assertThat(item.has("nome")).isFalse();
		}
		else {
			assertThat(detalhe.path("nome").asString()).isEqualTo(esperado);
			assertThat(item.path("nome").asString()).isEqualTo(esperado);
		}
	}

	private static UUID submissao(UUID usuario, String tipo, @Nullable String transcricao) {
		UUID id = UUID.randomUUID();
		dono.update("""
				INSERT INTO submissoes (id, usuario_id, tipo, transcricao, criado_em)
				VALUES (?, ?, ?, ?::text, now())
				""", id, usuario, tipo, transcricao);
		return id;
	}

	private static UUID job(UUID usuario, @Nullable UUID submissao, @Nullable UUID origem, @Nullable String nome) {
		UUID id = UUID.randomUUID();
		dono.update("""
				INSERT INTO jobs (id, status, usuario_id, submissao_id, job_origem_id, nome, competencias, criado_em)
				VALUES (?, 'arquivado', ?, ?::uuid, ?::uuid, ?::text, ARRAY['2025-11'], now())
				""", id, usuario, submissao, origem, nome);
		return id;
	}

	private static void regra(UUID job) {
		regra(job, 1, "confirmacao_usuario", null);
	}

	private static UUID regra(UUID job, int versao, String origem, @Nullable UUID regraOrigem) {
		return Objects.requireNonNull(dono.queryForObject(
				"""
						INSERT INTO regras (job_id, versao, origem, regra_origem_id, nucleo, especificacoes, hash, criada_em)
						VALUES (?, ?, ?, ?::uuid,
						        '{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.03}'::jsonb,
						        '[]'::jsonb, lpad(?::text, 64, 'a'), now())
						RETURNING id
						""",
				UUID.class, job, versao, origem, regraOrigem, versao));
	}

	private static void rodadaCorrigida(UUID job, UUID regraAnalisada, UUID submissaoCorrecao, UUID regraResultante) {
		dono.update("""
				INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado, submissao_correcao_id,
				    regra_resultante_id, criada_em, atualizada_em)
				VALUES (?, ?, '[{"elementos":["nucleo.percentual"],"motivo":"percentual ausente"}]'::jsonb, 'corrigida',
				    ?, ?, now(), now())
				""", job, regraAnalisada, submissaoCorrecao, regraResultante);
	}

	private static @Nullable String nomeGravado(UUID job) {
		List<String> nomes = dono.queryForList("SELECT nome FROM jobs WHERE id = ?", String.class, job);
		return nomes.getFirst();
	}

	private static String jobSemNome(UUID job) {
		return Objects.requireNonNull(
				dono.queryForObject("SELECT (to_jsonb(j) - 'nome')::text FROM jobs j WHERE id = ?", String.class, job));
	}

	private static String contagens() {
		return Objects.requireNonNull(dono.queryForObject("""
				SELECT jsonb_build_object(
				'jobs', (SELECT count(*) FROM jobs),
				'transicoes', (SELECT count(*) FROM job_transicoes),
				'acoes', (SELECT count(*) FROM job_acoes),
				'trilhas', (SELECT count(*) FROM trilhas_auditoria),
				'outbox', (SELECT count(*) FROM outbox_events)
				)::text
				""", String.class));
	}

	private static int contagem(String sql, Object... argumentos) {
		Integer total = dono.queryForObject(sql, Integer.class, argumentos);
		return total == null ? 0 : total;
	}

}