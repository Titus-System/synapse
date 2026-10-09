package synapse.api.job;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Timestamp;
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
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.support.SqlArrayValue;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.outbox.Outbox;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.security.UsuarioAtual;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Prova contra PostgreSQL real que a consulta de um job produz uma única resposta com
 * várias versões de regra, que ela recupera o motivo da parada corrente e que cada
 * resposta valida contra {@code JobDetalhado}. Os jobs avançam pelos serviços de produção
 * - a máquina de estados, {@code etapa-alterada} e {@code simulacao-concluida} - e os
 * artefatos de codegen e worker entram como esses serviços os gravariam.
 */
@EnabledIf("dockerIsAvailable")
class BuscarJobPersistenciaTests {

	private static final UUID USUARIO = UUID.fromString("55555555-5555-4555-8555-555555555555");

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static JdbcTemplate dono;

	private static JobService service;

	private static MaquinaDeEstadosDoJob maquina;

	private static JobEventosService eventos;

	private static MockMvc mvc;

	private static final JsonMapper JSON = new JsonMapper();

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
		contexto.registerBean(EmissoresSse.class, () -> mock(EmissoresSse.class));
		contexto.register(Config.class);
		contexto.refresh();
		service = contexto.getBean(JobService.class);
		maquina = contexto.getBean(MaquinaDeEstadosDoJob.class);
		eventos = contexto.getBean(JobEventosService.class);
		UsuarioAtual usuarioAtual = mock(UsuarioAtual.class);
		when(usuarioAtual.obter()).thenReturn(new AcessoDoUsuario(USUARIO, PapelDoUsuario.PROFISSIONAL_RH));
		mvc = MockMvcBuilders
			.standaloneSetup(new JobController(service, mock(EmissoresSse.class), new CorrelationContext()))
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

	@BeforeEach
	void limpar() {
		dono.execute("TRUNCATE submissoes CASCADE");
	}

	@TestConfiguration(proxyBeanMethods = false)
	@Import({ JobRepository.class, JobService.class, AutorizadorDeJob.class, CorrelationContext.class,
			MaquinaDeEstadosDoJob.class, JobEventosService.class, Outbox.class, VersoesDaRegra.class })
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

		JsonNode resposta = consultar(jobId);

		assertThat(resposta.path("id").asString()).isEqualTo(jobId.toString());
		assertThat(resposta.path("status").asString()).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(resposta.path("regras")).hasSize(2);
		assertThat(resposta.path("regras").get(0).path("id").asString()).isEqualTo(regraV1.toString());
		assertThat(resposta.path("regras").get(0).path("versao").asInt()).isEqualTo(1);
		assertThat(resposta.path("regras").get(1).path("id").asString()).isEqualTo(regraV2.toString());
		assertThat(resposta.path("regras").get(1).path("versao").asInt()).isEqualTo(2);
		assertThat(resposta.propertyNames()).doesNotContain("regra", "iniciado_em", "finalizado_em", "motivo",
				"simulacao");
		assertThat(resposta.path("simulacoes")).isEmpty();
	}

	@Test
	void jobEmProcessamentoNaoTemMotivoNemFimNemSimulacaoSemDesfecho() throws Exception {
		UUID jobId = criarJobEmProcessamento();
		UUID regra = criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		criarExecucaoPendente(jobId, regra);
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.DELEGACAO_WORKER, "iniciada");

		JsonNode resposta = consultar(jobId);

		assertThat(resposta.path("status").asString()).isEqualTo("simulando");
		assertThat(resposta.propertyNames()).contains("iniciado_em");
		assertThat(resposta.propertyNames()).doesNotContain("finalizado_em", "motivo", "simulacao");
		assertThat(resposta.path("simulacoes")).isEmpty();
		assertThat(Instant.parse(resposta.path("iniciado_em").asString()))
			.isEqualTo(instanteDaPrimeiraTransicao(jobId));
	}

	@Test
	void simulacaoConcluidaComSucessoTrazOResultadoENaoTemMotivo() throws Exception {
		UUID jobId = criarJobEmProcessamento();
		UUID regra = criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		UUID codigo = criarExecucaoPendente(jobId, regra);
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.DELEGACAO_WORKER, "iniciada");
		UUID resultado = criarResultado(jobId, codigo, "sucesso", "viavel", true);
		eventos.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.VIAVEL);

		JsonNode resposta = consultar(jobId);

		assertThat(resposta.path("status").asString()).isEqualTo("aguardando_decisao_usuario");
		assertThat(resposta.propertyNames()).doesNotContain("motivo", "finalizado_em");
		JsonNode simulacao = resposta.path("simulacao");
		assertThat(simulacao.path("status").asString()).isEqualTo("sucesso");
		assertThat(simulacao.path("veredito").asString()).isEqualTo("viavel");
		assertThat(simulacao.path("resultado").path("totais").path("simulado").decimalValue())
			.isEqualByComparingTo("484226.40");
		assertThat(simulacao.path("resultado").path("assercoes").get(0).has("detalhe")).isTrue();
		assertThat(simulacao.path("resultado").path("assercoes").get(0).path("detalhe").isNull()).isTrue();
		assertThat(resposta.path("simulacoes")).hasSize(1);
	}

	@Test
	void decomposicaoTrazAsQuebrasAbsolutasGravadasENaoTrazODetalhamento() throws Exception {
		UUID jobId = criarJobEmProcessamento();
		UUID regra = criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		UUID codigo = criarExecucaoPendente(jobId, regra);
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.DELEGACAO_WORKER, "iniciada");
		UUID resultado = criarResultadoComDetalhamento(jobId, codigo);
		eventos.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.VIAVEL);

		JsonNode resposta = consultar(jobId);

		JsonNode decomposicao = resposta.path("simulacao").path("resultado").path("decomposicao");
		assertThat(decomposicao.path("matricula").path("MATRIC-422").decimalValue()).isEqualByComparingTo("484226.40");
		assertThat(decomposicao.path("loja_absoluto").path("13").decimalValue()).isEqualByComparingTo("484226.40");
		assertThat(decomposicao.path("competencia_absoluto").path("2025-11").decimalValue())
			.isEqualByComparingTo("484226.40");
		assertThat(resposta.toString()).doesNotContain("\"linhas\"", "comissao_baseline", "contribuicoes");
	}

	@Test
	void decomposicaoSemQuebrasAbsolutasAsOmite() throws Exception {
		UUID jobId = criarJobEmProcessamento();
		UUID regra = criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		UUID codigo = criarExecucaoPendente(jobId, regra);
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.DELEGACAO_WORKER, "iniciada");
		UUID resultado = criarResultado(jobId, codigo, "sucesso", "viavel", true);
		eventos.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.VIAVEL);

		JsonNode resposta = consultar(jobId);

		JsonNode decomposicao = resposta.path("simulacao").path("resultado").path("decomposicao");
		assertThat(decomposicao.propertyNames()).containsExactlyInAnyOrder("elemento", "loja", "marca", "cargo",
				"competencia");
	}

	@ParameterizedTest
	@EnumSource(value = DesfechoDaSimulacao.class, names = { "ERRO_CODIGO", "ERRO_INFRA", "ASSERCAO_VIOLADA" })
	void falhaDeExecucaoTrazAMesmaRazaoDoSseESimulacaoSemResultado(DesfechoDaSimulacao desfecho) throws Exception {
		UUID jobId = criarJobEmProcessamento();
		UUID regra = criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		UUID codigo = criarExecucaoPendente(jobId, regra);
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.DELEGACAO_WORKER, "iniciada");
		String statusDoResultado = Objects.requireNonNull(desfecho.motivoDaTrilha());
		// O sandbox não devia deixar número nem veredito num status de falha; se
		// deixasse, a consulta não pode repassá-los.
		UUID resultado = criarResultado(jobId, codigo, statusDoResultado, "viavel", true);
		eventos.concluirSimulacao(jobId, resultado, desfecho);

		JsonNode resposta = consultar(jobId);

		assertThat(resposta.path("status").asString()).isEqualTo("erro");
		assertThat(resposta.path("motivo").asString()).isEqualTo(desfecho.razaoLocalizada());
		assertThat(resposta.propertyNames()).contains("iniciado_em", "finalizado_em");
		JsonNode simulacao = resposta.path("simulacao");
		assertThat(simulacao.path("status").asString()).isEqualTo(statusDoResultado);
		assertThat(simulacao.propertyNames()).doesNotContain("veredito", "resultado");
		assertThat(resposta.path("simulacoes")).hasSize(1);
		assertThat(resposta.path("simulacoes").get(0).propertyNames()).doesNotContain("veredito", "resultado");

		// A reentrega do mesmo desfecho é recusada e não mexe nos timestamps.
		String iniciadoEm = resposta.path("iniciado_em").asString();
		String finalizadoEm = resposta.path("finalizado_em").asString();
		assertThatThrownBy(() -> eventos.concluirSimulacao(jobId, resultado, desfecho))
			.isInstanceOf(TransicaoDeStatusInvalidaException.class);
		JsonNode depois = consultar(jobId);
		assertThat(depois.path("iniciado_em").asString()).isEqualTo(iniciadoEm);
		assertThat(depois.path("finalizado_em").asString()).isEqualTo(finalizadoEm);
		assertThat(depois.path("motivo").asString()).isEqualTo(desfecho.razaoLocalizada());
	}

	@Test
	void inviabilidadeOrcamentariaTrazMotivoEVereditoSemFinalizarOJob() throws Exception {
		UUID jobId = criarJobEmProcessamento();
		UUID regra = criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		UUID codigo = criarExecucaoPendente(jobId, regra);
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.DELEGACAO_WORKER, "iniciada");
		UUID resultado = criarResultado(jobId, codigo, "sucesso", "inviavel", true);
		eventos.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.INVIAVEL);

		JsonNode resposta = consultar(jobId);

		assertThat(resposta.path("status").asString()).isEqualTo("simulacao_inviavel");
		assertThat(resposta.path("motivo").asString()).isEqualTo(DesfechoDaSimulacao.INVIAVEL.razaoLocalizada());
		assertThat(resposta.propertyNames()).doesNotContain("finalizado_em");
		assertThat(resposta.path("simulacao").path("veredito").asString()).isEqualTo("inviavel");
		assertThat(resposta.path("simulacao").has("resultado")).isTrue();
	}

	@ParameterizedTest
	@EnumSource(value = EtapaDoGrafo.class, names = { "VALIDACAO_DOMINIO", "GERACAO_CODIGO", "DELEGACAO_WORKER" })
	void falhaAnteriorASimulacaoTemMotivoConsultavel(EtapaDoGrafo etapa) throws Exception {
		UUID jobId = criarJobEmProcessamento();
		criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		EventoEstadoDto evento = Objects.requireNonNull(eventos.aplicarEtapaAlterada(jobId, etapa, "erro"));

		JsonNode resposta = consultar(jobId);

		assertThat(resposta.path("status").asString()).isEqualTo("erro");
		assertThat(resposta.path("motivo").asString()).isEqualTo(MotivoDaParada.FALHA_ANTES_DA_SIMULACAO)
			.isEqualTo(evento.motivo());
		assertThat(resposta.propertyNames()).contains("iniciado_em", "finalizado_em");
		assertThat(resposta.propertyNames()).doesNotContain("simulacao");
		assertThat(resposta.path("simulacoes")).isEmpty();
	}

	@Test
	void novoCicloNaoHerdaOMotivoDaParadaAnterior() throws Exception {
		UUID jobId = criarJobEmProcessamento();
		UUID regraV1 = criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		UUID codigoV1 = criarExecucaoPendente(jobId, regraV1);
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.DELEGACAO_WORKER, "iniciada");
		eventos.concluirSimulacao(jobId, criarResultado(jobId, codigoV1, "sucesso", "inviavel", true),
				DesfechoDaSimulacao.INVIAVEL);
		JsonNode parado = consultar(jobId);
		assertThat(parado.path("motivo").asString()).isEqualTo(DesfechoDaSimulacao.INVIAVEL.razaoLocalizada());
		String iniciadoEm = parado.path("iniciado_em").asString();

		maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "evento", "sugestao_adaptacao_proposta");
		JsonNode reaberto = consultar(jobId);
		assertThat(reaberto.path("status").asString()).isEqualTo("gerando_regra");
		assertThat(reaberto.propertyNames()).doesNotContain("motivo", "finalizado_em");

		UUID regraV2 = criarRegra(jobId, 2, "0.0199", "hash-v2", "2026-01-01T10:05:00Z");
		UUID codigoV2 = criarExecucaoPendente(jobId, regraV2);
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.DELEGACAO_WORKER, "iniciada");
		JsonNode simulando = consultar(jobId);
		assertThat(simulando.path("status").asString()).isEqualTo("simulando");
		assertThat(simulando.propertyNames()).doesNotContain("motivo");

		eventos.concluirSimulacao(jobId, criarResultado(jobId, codigoV2, "sucesso", "viavel", true),
				DesfechoDaSimulacao.VIAVEL);
		JsonNode decidindo = consultar(jobId);
		assertThat(decidindo.path("status").asString()).isEqualTo("aguardando_decisao_usuario");
		assertThat(decidindo.propertyNames()).doesNotContain("motivo", "finalizado_em");
		assertThat(decidindo.path("iniciado_em").asString()).isEqualTo(iniciadoEm);
		assertThat(decidindo.path("simulacoes")).extracting((item) -> item.path("veredito").asString())
			.containsExactly("inviavel", "viavel");
	}

	@Test
	void arquivarUmJobInviavelNaoDevolveOMotivoDaInviabilidade() throws Exception {
		UUID jobId = criarJobEmProcessamento();
		UUID regra = criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		UUID codigo = criarExecucaoPendente(jobId, regra);
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.DELEGACAO_WORKER, "iniciada");
		eventos.concluirSimulacao(jobId, criarResultado(jobId, codigo, "sucesso", "inviavel", true),
				DesfechoDaSimulacao.INVIAVEL);
		maquina.transicionar(jobId, JobStatus.ARQUIVADO, "usuario", null);

		JsonNode resposta = consultar(jobId);

		assertThat(resposta.path("status").asString()).isEqualTo("arquivado");
		assertThat(resposta.propertyNames()).contains("finalizado_em").doesNotContain("motivo");
	}

	@Test
	void jobParadoSemMotivoReconhecivelResponde200SemMotivoELogaAdvertencia() throws Exception {
		UUID jobId = criarJobEmProcessamento();
		criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		maquina.transicionar(jobId, JobStatus.ERRO, "evento", "causa_que_a_api_nao_conhece");

		try (CapturaDeLog captura = new CapturaDeLog("synapse.api.job.BuscarJobService")) {
			JsonNode resposta = consultar(jobId);

			assertThat(resposta.path("status").asString()).isEqualTo("erro");
			assertThat(resposta.propertyNames()).doesNotContain("motivo");
			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			JsonNode log = JSON.readTree(linha);
			assertThat(log.path("level").asString()).isEqualTo("WARN");
			assertThat(log.path("logger").asString()).isEqualTo("synapse.api.job.BuscarJobService");
			assertThat(log.path("service.name").asString()).isEqualTo("synapse-api");
			assertThat(log.path("job_id").asString()).isEqualTo(jobId.toString());
			assertThat(log.path("extra").path("status").asString()).isEqualTo("erro");
			assertThat(log.path("extra").path("motivo_registrado").asBoolean()).isTrue();
			assertThat(linha).doesNotContain("causa_que_a_api_nao_conhece");
		}
	}

	@Test
	void jobParadoComMotivoReconhecidoNaoLogaNada() throws Exception {
		UUID jobId = criarJobEmProcessamento();
		criarRegra(jobId, 1, "0.02", "hash-v1", "2026-01-01T10:01:00Z");
		eventos.aplicarEtapaAlterada(jobId, EtapaDoGrafo.GERACAO_CODIGO, "erro");

		try (CapturaDeLog captura = new CapturaDeLog("synapse.api.job.BuscarJobService")) {
			consultar(jobId);

			assertThat(captura.eventos()).isEmpty();
		}
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

	private static Instant instanteDaPrimeiraTransicao(UUID jobId) {
		return Objects.requireNonNull(jdbc.queryForObject(
				"SELECT ocorrido_em FROM job_transicoes WHERE job_id = ? ORDER BY ocorrido_em LIMIT 1", Timestamp.class,
				jobId))
			.toInstant();
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

	/** Como {@code JobService}: a linha do job e depois a transição inicial. */
	private static UUID criarJobEmProcessamento() {
		UUID submissaoId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, conteudo, criado_em)
				VALUES (?, 'formulario', '{}'::jsonb, '2026-01-01T10:00:00Z') RETURNING id
				""", UUID.class, USUARIO));
		UUID jobId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES ('gerando_regra', ?, ?, ?, 485000, '2026-01-01T10:00:00Z') RETURNING id
				""", UUID.class, USUARIO, submissaoId, new SqlArrayValue("text", List.of("2025-11").toArray())));
		maquina.registrarCriacao(jobId, JobStatus.GERANDO_REGRA, "usuario");
		return jobId;
	}

	/**
	 * O que o codegen deixa ao gerar o código: prompt, código e a linha de
	 * {@code simulacoes} ainda sem resultado. Devolve o id do código gerado.
	 */
	private static UUID criarExecucaoPendente(UUID jobId, UUID regraId) {
		UUID prompt = UUID.randomUUID();
		UUID codigo = UUID.randomUUID();
		dono.update("""
				INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
				VALUES (?, ?, 'geracao_codigo', 'fixture', '{}'::jsonb, now())
				""", prompt, jobId);
		dono.update("""
				INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES (?, ?, ?, 'python', 'fixture', ?, now())
				""", codigo, jobId, regraId, prompt);
		dono.update("""
				INSERT INTO simulacoes (criado_em, regra_id, job_id, codigo_gerado_id)
				VALUES (now(), ?, ?, ?)
				""", regraId, jobId, codigo);
		return codigo;
	}

	/**
	 * O que o worker grava. Com {@code comNumeros}, totais e decomposição vêm
	 * preenchidos.
	 */
	private static UUID criarResultado(UUID jobId, UUID codigoGeradoId, String status, String veredito,
			boolean comNumeros) {
		String totais = comNumeros
				? """
						{"baseline":480000.00,"simulado":484226.40,"diferenca_abs":4226.40,"diferenca_pct":0.0088,"orcamento":485000.00}
						"""
				: null;
		String decomposicao = comNumeros ? """
				{"elemento":{"nucleo.percentual":4226.40},"loja":{"13":4226.40},"marca":{"10":4226.40},
				 "cargo":{"100":4226.40},"competencia":{"2025-11":4226.40}}
				""" : null;
		return Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, totais, veredito, assercoes,
				                                  decomposicao, criado_em)
				VALUES (?, ?, ?, ?::jsonb, ?, ?::jsonb, ?::jsonb, now()) RETURNING id
				""", UUID.class, jobId, codigoGeradoId, status, totais, veredito,
				"[{\"nome\":\"sem_comissao_negativa\",\"resultado\":\"ok\",\"detalhe\":null}]", decomposicao));
	}

	/** O sucesso com as quebras absolutas e o detalhamento, gravados no mesmo INSERT. */
	private static UUID criarResultadoComDetalhamento(UUID jobId, UUID codigoGeradoId) {
		String totais = """
				{"baseline":480000.00,"simulado":484226.40,"diferenca_abs":4226.40,"diferenca_pct":0.0088,"orcamento":485000.00}
				""";
		String decomposicao = """
				{"elemento":{"nucleo.percentual":4226.40},"loja":{"13":4226.40},"marca":{"10":4226.40},
				 "cargo":{"100":4226.40},"competencia":{"2025-11":4226.40},"matricula":{"MATRIC-422":484226.40},
				 "loja_absoluto":{"13":484226.40},"competencia_absoluto":{"2025-11":484226.40}}
				""";
		String linhas = """
				{"2025-11":{"MATRIC-422":{"cod_loja":"13","cod_marca":"10","cod_cargo":"100",
				 "comissao_baseline":480000.00,"comissao_simulada":484226.40,"diferenca":4226.40,
				 "contribuicoes":{"nucleo.percentual":4226.40}}}}
				""";
		return Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, totais, veredito, assercoes,
				                                  decomposicao, linhas, criado_em)
				VALUES (?, ?, 'sucesso', ?::jsonb, 'viavel', ?::jsonb, ?::jsonb, ?::jsonb, now()) RETURNING id
				""", UUID.class, jobId, codigoGeradoId, totais,
				"[{\"nome\":\"sem_comissao_negativa\",\"resultado\":\"ok\",\"detalhe\":null}]", decomposicao, linhas));
	}

}
