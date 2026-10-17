package synapse.api.job;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
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
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.CsvSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@EnabledIf("dockerIsAvailable")
class ConfirmarParametrosPersistenciaTests {

	private static final UUID USUARIO = CriarJobControllerTests.USUARIO;

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(tools.jackson.databind.DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

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
	@Import({ JobRepository.class, JobService.class, RodadasRepository.class, MaquinaDeEstadosDoJob.class, Outbox.class,
			VersoesDaRegra.class, CorrelationContext.class })
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
	 * parâmetros da anterior inalterados quando só a representação foi editada, e o hash
	 * os cobre, consistente com a coluna.
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

	@ParameterizedTest
	@ValueSource(strings = { "gerando_regra", "simulando" })
	void confirmarEmEstadoInvalidoERecusadoSemEfeito(String estado) {
		UUID jobId = criarJob();
		confirmar(jobId, corpo("0.03"));
		jdbc.update("UPDATE jobs SET status = ? WHERE id = ?", estado, jobId);

		int versoesAntes = versoes(jobId);
		Integer outboxAntes = jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class,
				jobId);

		assertThatThrownBy(() -> confirmar(jobId, corpo("0.04")))
			.isInstanceOf(TransicaoDeStatusInvalidaException.class);

		assertThat(versoes(jobId)).isEqualTo(versoesAntes);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(outboxAntes);
		assertThat(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId)).isEqualTo(estado);
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

	@ParameterizedTest
	@CsvSource({ "485000.1234567890123456789,12000000.9876543210987654321", ",", "0,0" })
	void eventoLevaParametrosEfetivosSemInventarOsAusentes(String orcamento, String meta) throws Exception {
		UUID job = criarJob();
		jdbc.update("UPDATE jobs SET orcamento = ?::numeric, meta_venda = ?::numeric WHERE id = ?", orcamento, meta,
				job);

		JobCriadoDto confirmado = confirmar(job, corpo("0.03"));

		JsonNode evento = eventoConfirmado(job);
		assertThat(evento.path("regra_id").asString()).isEqualTo(confirmado.regra().id().toString());
		assertThat(evento.path("competencias")).isEqualTo(JSON.valueToTree(confirmado.competencias()));
		assertThat(evento.has("orcamento")).isEqualTo(orcamento != null);
		assertThat(evento.has("meta_venda")).isEqualTo(meta != null);
		if (orcamento != null) {
			assertThat(evento.path("orcamento").decimalValue()).isEqualByComparingTo(orcamento);
		}
		if (meta != null) {
			assertThat(evento.path("meta_venda").decimalValue()).isEqualByComparingTo(meta);
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "pendente", "em_reextracao" })
	void confirmacaoFechaSomenteARodadaAbertaDaVersaoAtual(String estado) throws Exception {
		UUID job = criarJob();
		UUID origem = regraId(job, 1);
		UUID rodada = inserirRodada(job, origem, estado);
		UUID outroJob = criarJob();
		UUID outraRodada = inserirRodada(outroJob, regraId(outroJob, 1), "pendente");
		JsonNode antes = rodada(rodada);
		JsonNode outraAntes = rodada(outraRodada);

		JobCriadoDto confirmado = confirmar(job, corpo("0.03"));

		JsonNode depois = rodada(rodada);
		assertThat(depois.path("estado").asString()).isEqualTo("corrigida");
		assertThat(depois.path("regra_resultante_id").asString()).isEqualTo(confirmado.regra().id().toString());
		assertThat(depois.path("regra_analisada_id")).isEqualTo(antes.path("regra_analisada_id"));
		for (String campo : List.of("conflitos", "submissao_correcao_id", "rodada_anterior_id", "criada_em")) {
			assertThat(depois.path(campo)).isEqualTo(antes.path(campo));
		}
		assertThat(Instant.parse(depois.path("atualizada_em").asString()))
			.isAfter(Instant.parse(antes.path("atualizada_em").asString()));
		assertThat(rodada(outraRodada)).isEqualTo(outraAntes);
		assertThat(confirmado.status()).isEqualTo("gerando_regra");
		assertThat(eventoConfirmado(job).path("regra_id").asString()).isEqualTo(confirmado.regra().id().toString());
	}

	@ParameterizedTest
	@ValueSource(strings = { "corrigida", "abandonada", "reextracao_falhou" })
	void confirmacaoNaoReescreveRodadasEncerradas(String estado) throws Exception {
		UUID job = criarJob();
		UUID id = inserirRodada(job, regraId(job, 1), estado);
		JsonNode antes = rodada(id);

		confirmar(job, corpo("0.03"));

		assertThat(rodada(id)).isEqualTo(antes);
		assertThat(eventoConfirmado(job).path("competencias")).isEqualTo(JSON.valueToTree(competencias(job)));
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void rodadaComVersaoDeOutroJobOuSuperadaImpedeConfirmacao(boolean outroJob) {
		UUID job = criarJob();
		UUID origem = regraId(job, 1);
		if (outroJob) {
			origem = regraId(criarJob(), 1);
		}
		else {
			confirmar(job, corpo("0.03"));
			voltarParaConfirmacao(job);
		}
		UUID id = inserirRodada(job, origem, "pendente");
		JsonNode antes = rodada(id);
		JsonNode persistido = fotografia(job);

		assertThatThrownBy(() -> confirmar(job, corpo("0.04"))).isInstanceOf(ConfirmarParametrosException.class);

		assertThat(rodada(id)).isEqualTo(antes);
		assertThat(fotografia(job)).isEqualTo(persistido);
	}

	@ParameterizedTest
	@ValueSource(strings = { "null", "{}",
			"{\"orcamento\":485000.1234567890123456789,\"meta_venda\":12000000.9876543210987654321,\"competencias\":[\"2025-11\"],\"extensao\":{\"fonte\":\"original\"}}" })
	void edicaoSoDeParametrosAlinhaVersaoHashEventoETrilha(String parametrosAnteriores) throws Exception {
		UUID job = criarJob();
		String anteriores = "null".equals(parametrosAnteriores) ? null : parametrosAnteriores;
		var representacao = ConfirmarParametrosRequisicao.deJson(corpo("0.025")).representacao();
		comoDono().update("UPDATE regras SET parametros = ?::jsonb, hash = ? WHERE job_id = ?", anteriores,
				HashDaRegra.calcular(representacao, ParametrosExtraidos.deVersaoExistente(anteriores)), job);
		if (!"{}".equals(anteriores)) {
			jdbc.update("UPDATE jobs SET meta_venda = 12000000.9876543210987654321 WHERE id = ?", job);
		}
		JsonNode versaoAntes = versao(job, 1);

		JobCriadoDto confirmado = confirmar(job, comParametros("0.025", "600000.1234567890123456789"));

		assertThat(confirmado.regra().versao()).isEqualTo(2);
		JsonNode params = parametros(job, 2);
		assertThat(params.path("orcamento").decimalValue()).isEqualByComparingTo("600000.1234567890123456789");
		assertThat(params.path("competencias")).isEqualTo(JSON.readTree("[\"2025-09\",\"2025-10\"]"));
		if (anteriores == null || !"{}".equals(anteriores)) {
			assertThat(params.path("meta_venda").decimalValue()).isEqualByComparingTo("12000000.9876543210987654321");
		}
		else {
			assertThat(params.has("meta_venda")).isFalse();
		}
		if (anteriores != null && JSON.readTree(anteriores).has("extensao")) {
			assertThat(params.path("extensao")).isEqualTo(JSON.readTree(anteriores).path("extensao"));
		}
		assertThat(versao(job, 2).path("hash").asString()).isEqualTo(HashDaRegra.calcular(representacao,
				Objects.requireNonNull(ParametrosExtraidos.validados(params.toString()))));
		assertThat(versao(job, 1)).isEqualTo(versaoAntes);
		JsonNode evento = eventoConfirmado(job);
		assertThat(evento.path("competencias")).isEqualTo(params.path("competencias"));
		assertThat(evento.path("orcamento").decimalValue())
			.isEqualByComparingTo(params.path("orcamento").decimalValue());
		if (!"{}".equals(anteriores)) {
			assertThat(evento.path("meta_venda").decimalValue()).isEqualByComparingTo("12000000.9876543210987654321");
		}
		else {
			assertThat(evento.has("meta_venda")).isFalse();
		}
		assertThat(jdbc.queryForObject("SELECT conclusao->'campos_corrigidos' FROM trilhas_auditoria WHERE job_id = ?",
				String.class, job))
			.isEqualTo("[\"parametros.orcamento\", \"parametros.competencias\"]");
		assertThat(jdbc.queryForObject(
				"SELECT conclusao->>'editado_pelo_usuario' FROM trilhas_auditoria WHERE job_id = ?", String.class, job))
			.isEqualTo("true");
	}

	@Test
	void parametroRepetidoNaoMaterializaArtefatoLegadoNemCriaVersao() throws Exception {
		UUID job = criarJob();
		JsonNode antes = versao(job, 1);
		var requisicao = new ConfirmarParametrosRequisicao(
				ConfirmarParametrosRequisicao.deJson(corpo("0.025")).representacao(),
				new BigDecimal("485000.123456789012345678900"), competencias(job));

		JobCriadoDto confirmado = service.confirmar(job, requisicao);

		assertThat(confirmado.regra().versao()).isEqualTo(1);
		assertThat(versao(job, 1)).isEqualTo(antes);
		assertThat(eventoConfirmado(job).path("competencias")).isEqualTo(JSON.valueToTree(competencias(job)));
		assertThat(jdbc.queryForObject("SELECT conclusao->'campos_corrigidos' FROM trilhas_auditoria WHERE job_id = ?",
				String.class, job))
			.isEqualTo("[]");
		UUID eventoId = UUID
			.nameUUIDFromBytes(("confirmacao:" + confirmado.regra().id()).getBytes(StandardCharsets.UTF_8));
		assertThat(jdbc.queryForObject("SELECT evento_id FROM trilhas_auditoria WHERE job_id = ?", UUID.class, job))
			.isEqualTo(eventoId);

		voltarParaConfirmacao(job);
		assertThat(service.confirmar(job, requisicao).regra().id()).isEqualTo(confirmado.regra().id());
		assertThat(versao(job, 1)).isEqualTo(antes);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM trilhas_auditoria WHERE job_id = ?", Integer.class, job))
			.isEqualTo(1);
	}

	@Test
	void falhaNoFechamentoDesfazVersaoParametrosEstadoTrilhaEOutbox() {
		UUID job = criarJob();
		UUID id = inserirRodada(job, regraId(job, 1), "pendente");
		JsonNode antes = fotografia(job);
		JsonNode rodadaAntes = rodada(id);
		JdbcTemplate dono = comoDono();
		dono.execute(
				"CREATE FUNCTION t217_recusar_fechamento() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''conteudo reservado T217''; END'");
		dono.execute(
				"CREATE TRIGGER t217_falha BEFORE UPDATE ON rodadas_correcao FOR EACH ROW EXECUTE FUNCTION t217_recusar_fechamento()");
		try {
			assertThatThrownBy(() -> confirmar(job, comParametros("0.03", "600000")))
				.isInstanceOf(DataAccessException.class);
			assertThat(fotografia(job)).isEqualTo(antes);
			assertThat(rodada(id)).isEqualTo(rodadaAntes);
		}
		finally {
			dono.execute("DROP TRIGGER t217_falha ON rodadas_correcao");
			dono.execute("DROP FUNCTION t217_recusar_fechamento()");
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "pendente", "em_reextracao", "corrigida", "abandonada", "reextracao_falhou" })
	void versaoJaAnalisadaNaoReabreCicloNemModificaHistorico(String estado) throws Exception {
		UUID job = criarJob();
		UUID id = inserirRodada(job, regraId(job, 1), estado);
		JsonNode antes = fotografia(job);
		JsonNode rodadaAntes = rodada(id);

		assertThatThrownBy(() -> confirmar(job, corpo("0.025"))).isInstanceOfSatisfying(
				ConfirmarParametrosException.class,
				ex -> assertThat(ex.status()).isEqualTo(org.springframework.http.HttpStatus.CONFLICT));
		var mvc = MockMvcBuilders
			.standaloneSetup(new JobController(service, contexto.getBean(EmissoresSse.class), new CorrelationContext(),
					new synapse.api.core.metrics.AppMetrics(
							new io.micrometer.core.instrument.simple.SimpleMeterRegistry())))
			.setControllerAdvice(new JobAdvice())
			.build();
		mvc.perform(
				post("/jobs/" + job + "/parameters").contentType(MediaType.APPLICATION_JSON).content(corpo("0.025")))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.codigo").value("estado_invalido"))
			.andExpect(jsonPath("$.mensagem")
				.value("Esta versão já foi analisada. Altere a regra ou os parâmetros antes de confirmar."));

		assertThat(fotografia(job)).isEqualTo(antes);
		assertThat(rodada(id)).isEqualTo(rodadaAntes);
	}

	@Test
	void hashDeVersaoAnteriorJaAnalisadaTambemERecusado() {
		UUID job = criarJob();
		UUID antiga = regraId(job, 1);
		confirmar(job, corpo("0.03"));
		voltarParaConfirmacao(job);
		UUID id = inserirRodada(job, antiga, "corrigida");
		JsonNode antes = fotografia(job);
		JsonNode rodadaAntes = rodada(id);

		assertThatThrownBy(() -> confirmar(job, corpo("0.025"))).isInstanceOfSatisfying(
				ConfirmarParametrosException.class,
				ex -> assertThat(ex.status()).isEqualTo(org.springframework.http.HttpStatus.CONFLICT));

		assertThat(fotografia(job)).isEqualTo(antes);
		assertThat(rodada(id)).isEqualTo(rodadaAntes);
	}

	private static String comParametros(String percentual, String orcamento) {
		var pedido = (tools.jackson.databind.node.ObjectNode) JSON.readTree(corpo(percentual));
		pedido.put("orcamento", new BigDecimal(orcamento));
		pedido.set("competencias", JSON.valueToTree(List.of("2025-10", "2025-09")));
		return JSON.writeValueAsString(pedido);
	}

	private static UUID regraId(UUID job, int numero) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT id FROM regras WHERE job_id = ? AND versao = ?", UUID.class, job, numero));
	}

	private static UUID inserirRodada(UUID job, UUID regra, String estado) {
		return Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO rodadas_correcao (job_id, regra_analisada_id, estado, conflitos, criada_em, atualizada_em)
				VALUES (?, ?, ?, '[{"elemento_ref":"nucleo.percentual","motivo":"conflito reservado T217"}]'::jsonb,
				'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z') RETURNING id
				""", UUID.class, job, regra, estado));
	}

	private static JsonNode rodada(UUID id) {
		return JSON.readTree(Objects.requireNonNull(jdbc
			.queryForObject("SELECT row_to_json(r)::text FROM rodadas_correcao r WHERE id = ?", String.class, id)));
	}

	private static JsonNode versao(UUID job, int numero) {
		return JSON.readTree(Objects.requireNonNull(
				jdbc.queryForObject("SELECT row_to_json(r)::text FROM regras r WHERE job_id = ? AND versao = ?",
						String.class, job, numero)));
	}

	private static JsonNode fotografia(UUID job) {
		return JSON.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"""
						SELECT jsonb_build_object('job', to_jsonb(j),
						'versoes', (SELECT jsonb_agg(to_jsonb(r) ORDER BY versao) FROM regras r WHERE job_id = j.id),
						'outbox', (SELECT jsonb_agg(to_jsonb(o) ORDER BY id) FROM outbox_events o WHERE job_id = j.id),
						'trilha', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM trilhas_auditoria t WHERE job_id = j.id),
						'transicoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM job_transicoes t WHERE job_id = j.id))::text
						FROM jobs j WHERE id = ?
						""",
				String.class, job)));
	}

	private static List<String> competencias(UUID job) {
		return jdbc.queryForList("SELECT unnest(competencias) FROM jobs WHERE id = ?", String.class, job);
	}

	private static JsonNode eventoConfirmado(UUID job) throws Exception {
		List<String> eventos = jdbc.queryForList(
				"SELECT payload::text FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'",
				String.class, job);
		assertThat(eventos).hasSize(1);
		ContratoDeEvento.validar("parametros-confirmados", eventos.getFirst());
		return tools.jackson.databind.json.JsonMapper.builder()
			.enable(tools.jackson.databind.DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
			.build()
			.readTree(eventos.getFirst());
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
