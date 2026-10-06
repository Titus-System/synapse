package synapse.api.job;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import javax.sql.DataSource;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
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
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.support.SqlArrayValue;
import org.springframework.test.web.servlet.MockMvc;
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
import synapse.api.job.JobEventosService.DesfechoDaExtracao;
import synapse.api.job.JobEventosService.ExtracaoAplicada;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * O consumo de {@code regra-extraida} contra PostgreSQL real: a extração que o codegen
 * deixa em {@code extracoes_regras} vira a versão raiz do job, copiada como foi gravada,
 * e o {@code regra-submetida} que reabre o ciclo entra no outbox na mesma transação. As
 * extrações que não cabem no job são descartadas sem gravar nada, e a reentrega não
 * repete efeito algum.
 */
@EnabledIf("dockerIsAvailable")
class RegraExtraidaPersistenciaTests {

	private static final UUID USUARIO = UUID.fromString("66666666-6666-4666-8666-666666666666");

	/**
	 * Núcleo parcial, como a extração de um texto que não citou loja nem percentual: o
	 * schema aceita, e a falta é assunto da validação de domínio do ciclo seguinte.
	 */
	private static final String REPRESENTACAO_PARCIAL = """
			{"nucleo":{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"marca":["10"],"cargo":["100"]},
			 "especificacoes":[{"ref":"elem.1","construto":"generico",
			   "descricao":"dobrar a comissão no aniversário da loja","campos":{"multiplicador":2}}]}
			""";

	private static final String REPRESENTACAO_COMPLETA = """
			{"nucleo":{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"loja":[],"marca":["10"],"cargo":["100"],
			 "percentual":0.025000000000000000001},"especificacoes":[]}
			""";

	private static final JsonMapper JSON = new JsonMapper();

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static JdbcTemplate dono;

	private static JobEventosService eventos;

	private static MaquinaDeEstadosDoJob maquina;

	private static MockMvc mvc;

	private SimpleMeterRegistry registry;

	private RegraExtraidaConsumidor consumidor;

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
				VALUES (?, 'rh-t202', 'x', 'RH', 'profissional_rh', '2026-01-01T00:00:00Z')
				""", USUARIO);

		contexto = new AnnotationConfigApplicationContext();
		contexto.registerBean(DataSource.class, () -> dataSource);
		contexto.registerBean(JdbcTemplate.class, () -> jdbc);
		contexto.registerBean(PlatformTransactionManager.class, () -> new DataSourceTransactionManager(dataSource));
		contexto.registerBean(EmissoresSse.class, () -> mock(EmissoresSse.class));
		contexto.register(Config.class);
		contexto.refresh();
		eventos = contexto.getBean(JobEventosService.class);
		maquina = contexto.getBean(MaquinaDeEstadosDoJob.class);
		UsuarioAtual usuarioAtual = mock(UsuarioAtual.class);
		when(usuarioAtual.obter()).thenReturn(new AcessoDoUsuario(USUARIO, PapelDoUsuario.PROFISSIONAL_RH));
		mvc = MockMvcBuilders
			.standaloneSetup(new JobController(contexto.getBean(JobService.class), mock(EmissoresSse.class),
					new CorrelationContext()))
			.addInterceptors(new AutorizacaoJobsInterceptor(usuarioAtual,
					new AutorizadorDeJob(contexto.getBean(JobRepository.class))))
			.setControllerAdvice(new JobAdvice(), new AutorizacaoDeJobAdvice())
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

	@TestConfiguration(proxyBeanMethods = false)
	@EnableTransactionManagement
	@Import({ JobRepository.class, JobService.class, JobEventosService.class, MaquinaDeEstadosDoJob.class, Outbox.class,
			VersoesDaRegra.class, CorrelationContext.class, AutorizadorDeJob.class })
	static class Config {

	}

	@BeforeEach
	void novoConsumidor() {
		this.registry = new SimpleMeterRegistry();
		this.consumidor = new RegraExtraidaConsumidor(eventos, new CorrelationContext(), new AppMetrics(this.registry));
	}

	// --- Gravação ---------------------------------------------------------------------

	@Test
	void extracaoDeTextoViraAVersaoRaizComoFoiGravadaEReabreOCiclo() throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL);

		JsonNode antes = consultar(job.id());
		assertThat(antes.path("origem").asString()).isEqualTo("texto");
		assertThat(antes.path("regras").isArray()).isTrue();
		assertThat(antes.path("regras")).isEmpty();

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		UUID regraId = Objects.requireNonNull(
				jdbc.queryForObject("SELECT id FROM regras WHERE job_id = ? AND versao = 1", UUID.class, job.id()));
		var linha = jdbc.queryForMap(
				"SELECT origem, regra_origem_id, hash, (nucleo -> 'percentual') IS NOT NULL AS tem_percentual FROM regras WHERE id = ?",
				regraId);
		assertThat(linha.get("origem")).isEqualTo("extracao");
		assertThat(linha.get("regra_origem_id")).isNull();
		assertThat(linha.get("tem_percentual")).isEqualTo(false);
		assertThat(linha.get("hash")).isEqualTo(
				HashDaRegra.calcular(Objects.requireNonNull(RepresentacaoExtraida.validada(REPRESENTACAO_PARCIAL))));
		assertThat(jdbc.queryForObject("""
				SELECT r.nucleo = e.representacao -> 'nucleo' AND r.especificacoes = e.representacao -> 'especificacoes'
				FROM regras r JOIN extracoes_regras e ON e.id = ? WHERE r.id = ?
				""", Boolean.class, extracaoId, regraId)).isTrue();
		assertThat(statusAtual(job.id())).isEqualTo("gerando_regra");
		assertThat(transicoes(job.id())).isEqualTo(1);

		String payload = unicoRegraSubmetida(job.id());
		ContratoDeEvento.validar("regra-submetida", payload);
		RegraSubmetidaDto evento = JSON.readValue(payload, RegraSubmetidaDto.class);
		assertThat(evento.job_id()).isEqualTo(job.id());
		assertThat(evento.origem()).isEqualTo("texto");
		assertThat(evento.submissao_id()).isEqualTo(job.submissaoId());
		assertThat(evento.regra_id()).isEqualTo(regraId);
		assertThat(evento.competencias()).containsExactly("2025-08", "2025-11");
		assertThat(evento.orcamento()).isEqualByComparingTo("485000.1234567890123456789");

		JsonNode depois = consultar(job.id());
		assertThat(depois.path("regras")).hasSize(1);
		JsonNode versao = depois.path("regras").get(0);
		assertThat(versao.path("id").asString()).isEqualTo(regraId.toString());
		assertThat(versao.path("versao").asInt()).isEqualTo(1);
		assertThat(versao.path("origem").asString()).isEqualTo("extracao");
		assertThat(versao.path("representacao").path("nucleo").path("marca").get(0).asString()).isEqualTo("10");
		assertThat(versao.path("representacao").path("especificacoes")).hasSize(1);
		assertThat(listar()).contains(job.id().toString());

		assertThat(contagem("persistida", "nenhum")).isEqualTo(1.0);
	}

	@Test
	void extracaoDeVozRepeteAOrigemVozNoCicloSeguinte() throws Exception {
		Job job = criarJob("voz", "gerando_regra");
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_COMPLETA);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		String payload = unicoRegraSubmetida(job.id());
		ContratoDeEvento.validar("regra-submetida", payload);
		assertThat(JSON.readValue(payload, RegraSubmetidaDto.class).origem()).isEqualTo("voz");
		assertThat(jdbc.queryForObject("SELECT nucleo ->> 'percentual' FROM regras WHERE job_id = ?", String.class,
				job.id()))
			.isEqualTo("0.025000000000000000001");
		assertThat(consultar(job.id()).path("regras").get(0).path("origem").asString()).isEqualTo("extracao");
	}

	// --- Reentrega --------------------------------------------------------------------

	@Test
	void reentregaNaoCriaVersaoNemOutroRegraSubmetida() throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL);
		var evento = new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId);

		this.consumidor.receber(evento);
		this.consumidor.receber(evento);

		assertThat(versoes(job.id())).isEqualTo(1);
		unicoRegraSubmetida(job.id());
		assertThat(contagem("persistida", "nenhum")).isEqualTo(1.0);
		assertThat(contagem("duplicada", "reentrega")).isEqualTo(1.0);
	}

	@Test
	void reentregaDepoisQueOJobAvancouContinuaSendoDuplicada() throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL);
		UUID regraId = Objects
			.requireNonNull(eventos.aplicarRegraExtraida(job.id(), job.submissaoId(), extracaoId).regraId());
		maquina.transicionar(job.id(), JobStatus.SIMULANDO, "evento", null);

		ExtracaoAplicada reentrega = eventos.aplicarRegraExtraida(job.id(), job.submissaoId(), extracaoId);

		assertThat(reentrega.desfecho()).isEqualTo(DesfechoDaExtracao.REENTREGA);
		assertThat(reentrega.regraId()).isEqualTo(regraId);
		assertThat(versoes(job.id())).isEqualTo(1);
		unicoRegraSubmetida(job.id());
	}

	// --- Descarte ---------------------------------------------------------------------

	@Test
	void outraRepresentacaoParaJobQueJaTemVersaoEDescartada() throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL);
		jdbc.update("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES (?, 1, 'extracao', '{"marca":["20"]}'::jsonb, '[]'::jsonb, repeat('a', 64), now())
				""", job.id());

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(versoes(job.id())).isEqualTo(1);
		assertThat(eventosNoOutbox(job.id())).isZero();
		assertThat(contagem("descartada", "versao_existente")).isEqualTo(1.0);
	}

	@ParameterizedTest
	@ValueSource(strings = { "aguardando_confirmacao_parametros", "simulando", "cancelado" })
	void jobForaDeGerandoRegraNaoRecebeVersao(String statusDoJob) throws Exception {
		Job job = criarJob("texto", statusDoJob);
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(versoes(job.id())).isZero();
		assertThat(eventosNoOutbox(job.id())).isZero();
		assertThat(statusAtual(job.id())).isEqualTo(statusDoJob);
		assertThat(contagem("descartada", "estado_incompativel")).isEqualTo(1.0);
	}

	@Test
	void jobInexistenteEDescartado() throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL);

		this.consumidor.receber(new RegraExtraidaDto(UUID.randomUUID(), job.submissaoId(), extracaoId));

		assertThat(versoes(job.id())).isZero();
		assertThat(contagem("descartada", "job_inexistente")).isEqualTo(1.0);
	}

	@Test
	void submissaoQueNaoEADoJobEDescartada() throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		Job outro = criarJob("texto", "gerando_regra");
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), outro.submissaoId(), extracaoId));

		assertThat(versoes(job.id())).isZero();
		assertThat(eventosNoOutbox(job.id())).isZero();
		assertThat(contagem("descartada", "submissao_divergente")).isEqualTo(1.0);
	}

	@Test
	void extracaoInexistenteEDescartada() throws Exception {
		Job job = criarJob("texto", "gerando_regra");

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), UUID.randomUUID()));

		assertThat(versoes(job.id())).isZero();
		assertThat(contagem("descartada", "extracao_inexistente")).isEqualTo(1.0);
	}

	@Test
	void extracaoDeOutroJobEDescartada() throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		Job outro = criarJob("texto", "gerando_regra");
		UUID extracaoDoOutro = criarExtracao(outro, REPRESENTACAO_PARCIAL);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoDoOutro));

		assertThat(versoes(job.id())).isZero();
		assertThat(versoes(outro.id())).isZero();
		assertThat(contagem("descartada", "extracao_divergente")).isEqualTo(1.0);
	}

	@ParameterizedTest
	@ValueSource(strings = { """
			{"nucleo":{"percentual":"2,5%"},"especificacoes":[]}
			""", """
			{"nucleo":{"loja":null},"especificacoes":[]}
			""", """
			{"nucleo":{},"especificacoes":[{"construto":"generico","descricao":"sem ref"}]}
			""", """
			{"especificacoes":[]}
			""" })
	void extracaoForaDoContratoEDescartadaSemGravarNada(String representacao) throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		UUID extracaoId = criarExtracao(job, representacao);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(versoes(job.id())).isZero();
		assertThat(eventosNoOutbox(job.id())).isZero();
		assertThat(contagem("descartada", "representacao_invalida")).isEqualTo(1.0);
	}

	// --- Atomicidade ------------------------------------------------------------------

	@Test
	void falhaNoOutboxDesfazAVersaoEAMensagemVoltaParaAFila() throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL);
		var evento = new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId);
		dono.execute("REVOKE INSERT ON outbox_events FROM synapse_api");
		try {
			try (var anterior = new CorrelationContext().abrir("contexto-anterior", null)) {
				assertThatExceptionOfType(DataAccessException.class).isThrownBy(() -> this.consumidor.receber(evento));
				assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			}
		}
		finally {
			dono.execute("GRANT INSERT ON outbox_events TO synapse_api");
		}

		assertThat(versoes(job.id())).isZero();
		assertThat(eventosNoOutbox(job.id())).isZero();
		assertThat(this.registry.find("regra.extraida.consumo").counters()).isEmpty();
		assertThat(this.registry.get("regra.extraida.consumo.duracao").tag("resultado", "falha").timer().count())
			.isEqualTo(1);

		this.consumidor.receber(evento);

		assertThat(versoes(job.id())).isEqualTo(1);
		unicoRegraSubmetida(job.id());
		assertThat(contagem("persistida", "nenhum")).isEqualTo(1.0);
	}

	// --- Apoio ------------------------------------------------------------------------

	private record Job(UUID id, UUID submissaoId) {
	}

	/**
	 * Como a api grava a entrada por texto ou voz: submissão sem conteúdo, job sem regra.
	 */
	private static Job criarJob(String tipo, String statusDoJob) {
		UUID submissaoId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em)
				VALUES (?, ?, 'dobrar a comissão dos vendedores da marca 10 no aniversário da loja', now())
				RETURNING id
				""", UUID.class, USUARIO, tipo));
		UUID jobId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES ('gerando_regra', ?, ?, ?, 485000.1234567890123456789, now()) RETURNING id
				""", UUID.class, USUARIO, submissaoId,
				new SqlArrayValue("text", List.of("2025-08", "2025-11").toArray())));
		maquina.registrarCriacao(jobId, JobStatus.GERANDO_REGRA, "usuario");
		if (!"gerando_regra".equals(statusDoJob)) {
			dono.update("UPDATE jobs SET status = ? WHERE id = ?", statusDoJob, jobId);
		}
		return new Job(jobId, submissaoId);
	}

	/**
	 * O que o codegen grava ao extrair: prompt, resposta e a extração que aponta para
	 * ela.
	 */
	private static UUID criarExtracao(Job job, String representacao) {
		UUID prompt = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
				VALUES (?, 'extracao_parametros', 'fixture', '{}'::jsonb, now()) RETURNING id
				""", UUID.class, job.id()));
		UUID resposta = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO respostas_modelo (job_id, prompt_id, conteudo, criado_em)
				VALUES (?, ?, 'fixture', now()) RETURNING id
				""", UUID.class, job.id(), prompt));
		return Objects.requireNonNull(dono.queryForObject(
				"""
						INSERT INTO extracoes_regras (job_id, submissao_id, resposta_id, representacao, rebaixamentos, criado_em)
						VALUES (?, ?, ?, ?::jsonb, '[]'::jsonb, now()) RETURNING id
						""",
				UUID.class, job.id(), job.submissaoId(), resposta, representacao));
	}

	/** Consulta pelo HTTP e confere o corpo contra {@code JobDetalhado}. */
	private static JsonNode consultar(UUID jobId) throws Exception {
		String corpo = mvc.perform(get("/jobs/{id}", jobId).accept(MediaType.APPLICATION_JSON))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString(StandardCharsets.UTF_8);
		ContratoDeEvento.validarRespostaHttp("JobDetalhado", corpo);
		return JSON.readTree(corpo);
	}

	private static String listar() throws Exception {
		return mvc.perform(get("/jobs").accept(MediaType.APPLICATION_JSON))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString(StandardCharsets.UTF_8);
	}

	private static String unicoRegraSubmetida(UUID jobId) {
		List<String> payloads = jdbc.queryForList(
				"SELECT payload::text FROM outbox_events WHERE job_id = ? AND tipo = 'regra-submetida'", String.class,
				jobId);
		assertThat(payloads).hasSize(1);
		return payloads.getFirst();
	}

	private static int eventosNoOutbox(UUID jobId) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId));
	}

	private static int versoes(UUID jobId) {
		return Objects
			.requireNonNull(jdbc.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Integer.class, jobId));
	}

	private static int transicoes(UUID jobId) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class, jobId));
	}

	private static String statusAtual(UUID jobId) {
		return Objects.requireNonNull(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId));
	}

	private double contagem(String resultado, String motivo) {
		Counter contador = this.registry.find("regra.extraida.consumo")
			.tag("resultado", resultado)
			.tag("motivo", motivo)
			.counter();
		return (contador != null) ? contador.count() : 0;
	}

}
