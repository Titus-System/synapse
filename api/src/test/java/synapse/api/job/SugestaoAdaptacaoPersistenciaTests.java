package synapse.api.job;

import java.sql.Connection;
import java.sql.DriverManager;
import java.util.ArrayList;
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
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.outbox.Outbox;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.JobEventosService.SugestaoAplicada;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatExceptionOfType;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

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

	private static JdbcTemplate artefatos;

	private static JobService criarService;

	private static JobEventosService sugestaoService;

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
		artefatos = dono;
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
		contexto.registerBean(EmissoresSse.class, () -> mock(EmissoresSse.class));
		contexto.register(Config.class);
		contexto.refresh();
		criarService = contexto.getBean(JobService.class);
		sugestaoService = contexto.getBean(JobEventosService.class);
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
			VersoesDaRegra.class, CorrelationContext.class })
	static class Config {

	}

	@Test
	void gravaUmaAlternativaEPublicaEntradaCompletaNoContratoOficial() throws Exception {
		UUID jobId = jobInviavel();
		UUID origem = versaoId(jobId, 1);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		SugestaoAplicada aplicada = Objects.requireNonNull(
				sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246")));
		assertThat(aplicada.versao().versao()).isEqualTo(2);
		assertThat(aplicada.versao().origem()).isEqualTo("sugestao_adaptacao");
		assertThat(jdbc.queryForObject("SELECT regra_origem_id FROM regras WHERE job_id = ? AND versao = 2", UUID.class,
				jobId))
			.isEqualTo(origem);
		assertThat(percentual(jobId, 1)).isEqualTo("0.025");
		assertThat(percentual(jobId, 2)).isEqualTo("0.0246");
		assertThat(status(jobId)).isEqualTo("gerando_regra");
		String payload = Objects.requireNonNull(jdbc.queryForObject("""
				SELECT payload::text FROM outbox_events
				WHERE job_id = ? AND tipo = 'regra-submetida' AND payload->>'regra_id' = ?
				""", String.class, jobId, aplicada.versao().id().toString()));
		ContratoDeEvento.validar("regra-submetida", payload);
		var evento = new tools.jackson.databind.json.JsonMapper().readValue(payload, RegraSubmetidaDto.class);
		assertThat(evento.origem()).isEqualTo("formulario");
		assertThat(evento.competencias()).containsExactly("2025-11");
		assertThat(evento.orcamento()).isEqualByComparingTo("485000.1234567890123456789");
	}

	/**
	 * A versão de origem com parâmetros - o caso de um job de texto que chegou inviável -
	 * tem o hash cobrindo-os; a sugestão precisa carregar os mesmos parâmetros, com o
	 * mesmo hash coberto, para a versão nova, e não apenas ajustar o percentual.
	 */
	@Test
	void sugestaoCarregaOsParametrosDaVersaoDeOrigemParaAVersaoNova() {
		UUID jobId = jobInviavel();
		UUID origem = versaoId(jobId, 1);
		RepresentacaoRegraDto regraOrigem = representacao("0.025");
		ParametrosDaSimulacao params = new ParametrosDaSimulacao(new java.math.BigDecimal("500000"), null,
				List.of("2025-11"));
		artefatos.update("UPDATE regras SET hash = ?, parametros = ?::jsonb WHERE id = ?",
				HashDaRegra.calcular(regraOrigem, params), "{\"orcamento\":500000,\"competencias\":[\"2025-11\"]}",
				origem);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");

		SugestaoAplicada aplicada = Objects.requireNonNull(
				sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246")));

		assertThat(aplicada.versao().versao()).isEqualTo(2);
		tools.jackson.databind.json.JsonMapper json = new tools.jackson.databind.json.JsonMapper();
		assertThat(json.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"SELECT parametros::text FROM regras WHERE job_id = ? AND versao = 2", String.class, jobId))))
			.isEqualTo(json.readTree("{\"orcamento\":500000,\"competencias\":[\"2025-11\"]}"));
		assertThat(jdbc.queryForObject("SELECT hash FROM regras WHERE job_id = ? AND versao = 2", String.class, jobId))
			.isEqualTo(HashDaRegra.calcular(representacao("0.0246"), params));
	}

	@Test
	void duasSimulacoesMantemOsResultadosAssociadosAsSuasRegras() {
		UUID jobId = jobInviavel();
		UUID original = versaoId(jobId, 1);
		UUID resultadoOriginal = resultado(jobId, original, "inviavel", "492100");
		SugestaoAplicada aplicada = Objects.requireNonNull(
				sugestaoService.aplicarSugestaoAdaptacao(jobId, original, resultadoOriginal, representacao("0.0246")));
		UUID alternativa = aplicada.versao().id();
		UUID resultadoAlternativa = resultado(jobId, alternativa, "viavel", "484226.40");
		contexto.getBean(JobEventosService.class)
			.concluirSimulacao(jobId, resultadoAlternativa, DesfechoDaSimulacao.VIAVEL);
		JobDetalhadoDto job = contexto.getBean(JobService.class).buscar(jobId);
		assertThat(job.status()).isEqualTo("aguardando_decisao_usuario");
		assertThat(job.simulacoes()).extracting(SimulacaoDto::regra_id).containsExactly(original, alternativa);
		assertThat(job.simulacoes()).extracting(SimulacaoDto::veredito).containsExactly("inviavel", "viavel");
		assertThat(job.simulacao()).isEqualTo(job.simulacoes().getLast());
		assertThat(Objects.requireNonNull(Objects.requireNonNull(job.simulacoes().getFirst().resultado()).totais())
			.simulado()).isEqualByComparingTo("492100");
		assertThat(Objects.requireNonNull(Objects.requireNonNull(job.simulacoes().getLast().resultado()).totais())
			.simulado()).isEqualByComparingTo("484226.40");
	}

	@Test
	void sugestaoDeJobTextualPreservaOrigemTexto() throws Exception {
		UUID jobId = jobInviavel();
		artefatos.update(
				"UPDATE submissoes SET tipo = 'texto', conteudo = NULL, transcricao = 'descricao' WHERE id = (SELECT submissao_id FROM jobs WHERE id = ?)",
				jobId);
		UUID origem = versaoId(jobId, 1);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		SugestaoAplicada aplicada = Objects.requireNonNull(
				sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246")));
		String payload = Objects.requireNonNull(jdbc.queryForObject(
				"SELECT payload::text FROM outbox_events WHERE job_id = ? AND payload->>'regra_id' = ?", String.class,
				jobId, aplicada.versao().id().toString()));
		ContratoDeEvento.validar("regra-submetida", payload);
		assertThat(new JsonMapper().readTree(payload).path("origem").asString()).isEqualTo("texto");
	}

	@Test
	void reentregasNaoReabremOCicloMesmoQuandoAlternativaTambemEInviavel() {
		UUID jobId = jobInviavel();
		UUID original = versaoId(jobId, 1);
		UUID resultadoOriginal = resultado(jobId, original, "inviavel", "492100");
		SugestaoAplicada aplicada = Objects.requireNonNull(
				sugestaoService.aplicarSugestaoAdaptacao(jobId, original, resultadoOriginal, representacao("0.0246")));
		var conclusao = contexto.getBean(JobEventosService.class);
		assertThat(conclusao.concluirSimulacao(jobId, resultadoOriginal, DesfechoDaSimulacao.INVIAVEL)).isNull();
		assertThat(status(jobId)).isEqualTo("gerando_regra");
		UUID resultadoAlternativa = resultado(jobId, aplicada.versao().id(), "inviavel", "490000");
		conclusao.concluirSimulacao(jobId, resultadoAlternativa, DesfechoDaSimulacao.INVIAVEL);
		assertThat(
				sugestaoService.aplicarSugestaoAdaptacao(jobId, original, resultadoOriginal, representacao("0.0246")))
			.isNull();
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, aplicada.versao().id(), resultadoAlternativa,
				representacao("0.023")))
			.isNull();
		assertThat(versoes(jobId)).isEqualTo(2);
		assertThat(status(jobId)).isEqualTo("simulacao_inviavel");
		assertThat(contexto.getBean(JobService.class).buscar(jobId).motivo())
			.isEqualTo(DesfechoDaSimulacao.INVIAVEL.razaoLocalizada());
		assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(2);
	}

	@Test
	void propostaAntesDoEventoDoWorkerAplicaDesfechoEReabreNaMesmaTransacao() {
		UUID jobId = jobInviavel();
		jdbc.update("UPDATE jobs SET status = 'simulando' WHERE id = ?", jobId);
		UUID origem = versaoId(jobId, 1);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246")))
			.isNotNull();
		assertThat(status(jobId)).isEqualTo("gerando_regra");
		// A inviabilidade e a reabertura confirmam juntas: o estado corrente é o do novo
		// ciclo, e a causa do ciclo anterior não vira o seu motivo.
		assertThat(contexto.getBean(JobService.class).buscar(jobId).motivo()).isNull();
		assertThat(jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ? AND motivo = 'inviavel'",
				Integer.class, jobId))
			.isEqualTo(1);
	}

	@ParameterizedTest
	@CsvSource({ "true,false", "true,true", "false,false" })
	void preservaEventosOriginaisNasDuasOrdensDeEntrega(boolean propostaPrimeiro, boolean resultadoJaVinculado) {
		UUID jobId = jobInviavel();
		UUID regraId = versaoId(jobId, 1);
		UUID resultadoId = resultado(jobId, regraId, "inviavel", "492100");
		UUID simulacaoId = Objects.requireNonNull(
				jdbc.queryForObject("SELECT id FROM simulacoes WHERE resultado_id = ?", UUID.class, resultadoId));
		if (!resultadoJaVinculado) {
			jdbc.update("UPDATE simulacoes SET resultado_id = NULL WHERE id = ?", simulacaoId);
		}
		jdbc.update("UPDATE jobs SET status = 'gerando_regra' WHERE id = ?", jobId);
		List<EventoSse> eventos = new ArrayList<>();
		EmissoresSse emissores = mock(EmissoresSse.class);
		doAnswer(chamada -> {
			assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
			eventos.add(chamada.getArgument(1, EventoSse.class));
			return null;
		}).when(emissores).emitir(eq(jobId), any());
		var sugestoes = new SugestaoAdaptacaoConsumidor(sugestaoService, emissores, new CorrelationContext());
		var conclusoes = new SimulacaoConcluidaConsumidor(contexto.getBean(JobEventosService.class), emissores,
				new CorrelationContext());
		var proposta = new SugestaoAdaptacaoPropostaDto(jobId, regraId, resultadoId, representacao("0.0099"));
		var conclusao = new SimulacaoConcluidaDto(jobId, resultadoId, "sucesso", "inviavel", null, null, null, null);

		if (propostaPrimeiro) {
			sugestoes.receber(proposta);
			conclusoes.receber(conclusao);
		}
		else {
			conclusoes.receber(conclusao);
			sugestoes.receber(proposta);
		}
		sugestoes.receber(proposta);
		conclusoes.receber(conclusao);

		assertThat(eventos).containsExactly(
				EventoSse.de("estado",
						EventoEstadoDto.transicao(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, null)),
				EventoSse.de("resultado", new EventoResultadoDto(jobId, simulacaoId, "sucesso", "inviavel")),
				EventoSse.de("estado",
						EventoEstadoDto.transicao(jobId, JobStatus.SIMULANDO, JobStatus.SIMULACAO_INVIAVEL,
								DesfechoDaSimulacao.INVIAVEL.razaoLocalizada())),
				EventoSse.de("estado",
						EventoEstadoDto.transicao(jobId, JobStatus.SIMULACAO_INVIAVEL, JobStatus.GERANDO_REGRA, null)));
		assertThat(status(jobId)).isEqualTo("gerando_regra");
		assertThat(versoes(jobId)).isEqualTo(2);
	}

	@Test
	void naoAceitaResultadoDeOutroJobOuAlteracaoAlemDoPercentual() {
		UUID jobId = jobInviavel();
		UUID outro = jobInviavel();
		UUID origem = versaoId(jobId, 1);
		UUID resultadoOutro = resultado(outro, versaoId(outro, 1), "inviavel", "492100");
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultadoOutro, representacao("0.0246")))
			.isNull();
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		var nova = representacao("0.0246");
		var diferente = new RepresentacaoRegraDto(nova.nucleo(),
				List.of(new tools.jackson.databind.json.JsonMapper().readTree("{\"tipo\":\"outro\"}")));
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, diferente)).isNull();
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.025"))).isNull();
		assertThat(versoes(jobId)).isEqualTo(1);
	}

	@Test
	void propostaIgualAVersaoAnteriorNaoReabreCheckpointJaConcluido() {
		UUID jobId = jobInviavel();
		var agora = java.time.Instant.now();
		var regra = representacao("0.03");
		var atual = contexto.getBean(VersoesDaRegra.class)
			.resolver(jobId, regra, null, HashDaRegra.calcular(regra), "confirmacao_usuario", versaoId(jobId, 1),
					java.sql.Timestamp.from(agora), agora);
		UUID resultado = resultado(jobId, atual.id(), "inviavel", "492100");
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, atual.id(), resultado, representacao("0.025")))
			.isNull();
		assertThat(status(jobId)).isEqualTo("simulacao_inviavel");
		assertThat(versoes(jobId)).isEqualTo(2);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(1);
	}

	@ParameterizedTest
	@ValueSource(strings = { "cancelado", "arquivado", "liberado", "erro", "aguardando_decisao_usuario" })
	void naoReabreJobForaDaAdaptacao(String estado) {
		UUID jobId = jobInviavel();
		UUID origem = versaoId(jobId, 1);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		jdbc.update("UPDATE jobs SET status = ? WHERE id = ?", estado, jobId);
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246")))
			.isNull();
		assertThat(status(jobId)).isEqualTo(estado);
		assertThat(versoes(jobId)).isEqualTo(1);
	}

	@Test
	void falhaNoOutboxReverteDesfechoVinculoVersaoEReaberturaSemEmitirSse() {
		UUID jobId = jobInviavel();
		UUID regraId = versaoId(jobId, 1);
		UUID resultadoId = resultado(jobId, regraId, "inviavel", "492100");
		jdbc.update("UPDATE jobs SET status = 'gerando_regra' WHERE id = ?", jobId);
		jdbc.update("UPDATE simulacoes SET resultado_id = NULL WHERE job_id = ?", jobId);
		var antes = jdbc.queryForMap("SELECT status, iniciado_em, finalizado_em FROM jobs WHERE id = ?", jobId);
		Integer transicoes = jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class,
				jobId);
		EmissoresSse emissores = mock(EmissoresSse.class);
		var consumidor = new SugestaoAdaptacaoConsumidor(sugestaoService, emissores, new CorrelationContext());
		var proposta = new SugestaoAdaptacaoPropostaDto(jobId, regraId, resultadoId, representacao("0.0246"));
		artefatos.execute("REVOKE INSERT ON outbox_events FROM synapse_api");
		try {
			try (var anterior = new CorrelationContext().abrir("contexto-anterior", null)) {
				assertThatExceptionOfType(DataAccessException.class).isThrownBy(() -> consumidor.receber(proposta));
				assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			}
		}
		finally {
			artefatos.execute("GRANT INSERT ON outbox_events TO synapse_api");
		}
		assertThat(jdbc.queryForMap("SELECT status, iniciado_em, finalizado_em FROM jobs WHERE id = ?", jobId))
			.isEqualTo(antes);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(transicoes);
		assertThat(jdbc.queryForObject("SELECT resultado_id FROM simulacoes WHERE job_id = ?", UUID.class, jobId))
			.isNull();
		assertThat(versoes(jobId)).isEqualTo(1);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(1);
		verifyNoInteractions(emissores);
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void conclusaoPreservaLoggerCorrelacaoEAdvertenciaQuandoNaoHaSimulacao(boolean semSimulacao) throws Exception {
		UUID jobId = jobInviavel();
		UUID resultadoId = resultado(jobId, versaoId(jobId, 1), "viavel", "484000");
		jdbc.update("UPDATE jobs SET status = 'gerando_regra' WHERE id = ?", jobId);
		if (semSimulacao) {
			artefatos.update("DELETE FROM simulacoes WHERE job_id = ?", jobId);
		}
		else {
			jdbc.update("UPDATE simulacoes SET resultado_id = NULL WHERE job_id = ?", jobId);
		}
		var consumidor = new SimulacaoConcluidaConsumidor(contexto.getBean(JobEventosService.class),
				mock(EmissoresSse.class), new CorrelationContext());
		try (var anterior = new CorrelationContext().abrir("contexto-anterior", null);
				var captura = new CapturaDeLog("synapse.api.job.SimulacaoConcluidaService")) {
			consumidor
				.receber(new SimulacaoConcluidaDto(jobId, resultadoId, "sucesso", "viavel", null, null, null, null));
			assertThat(status(jobId)).isEqualTo("aguardando_decisao_usuario");
			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			assertThat(captura.eventos()).hasSize(semSimulacao ? 1 : 0);
			if (semSimulacao) {
				String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
				ContratoDeEvento.validarLog(linha);
				var log = new JsonMapper().readTree(linha);
				assertThat(log.path("logger").asString()).isEqualTo("synapse.api.job.SimulacaoConcluidaService");
				assertThat(log.path("level").asString()).isEqualTo("WARN");
				assertThat(log.path("job_id").asString()).isEqualTo(jobId.toString());
				assertThat(log.path("extra").path("resultado_id").asString()).isEqualTo(resultadoId.toString());
				assertThat(log.path("message").asString())
					.isEqualTo("nenhuma simulação amarrada ao resultado; evento \"resultado\" não será emitido");
				assertThat(linha).doesNotContain("fixture", "484000", "representacao", "conteudo", "fonte");
			}
		}
	}

	@Test
	void sugestaoDescartadaPreservaLogCorrelacionadoSemEmitirSse() throws Exception {
		UUID jobId = jobInviavel();
		UUID regraId = versaoId(jobId, 1);
		UUID resultadoId = resultado(jobId, regraId, "inviavel", "492100");
		EmissoresSse emissores = mock(EmissoresSse.class);
		var consumidor = new SugestaoAdaptacaoConsumidor(sugestaoService, emissores, new CorrelationContext());
		try (var anterior = new CorrelationContext().abrir("contexto-anterior", null);
				var captura = new CapturaDeLog(SugestaoAdaptacaoConsumidor.class)) {
			consumidor.receber(new SugestaoAdaptacaoPropostaDto(jobId, regraId, resultadoId, representacao("0")));
			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			var log = new JsonMapper().readTree(linha);
			assertThat(log.path("logger").asString()).isEqualTo(SugestaoAdaptacaoConsumidor.class.getName());
			assertThat(log.path("level").asString()).isEqualTo("WARN");
			assertThat(log.path("job_id").asString()).isEqualTo(jobId.toString());
			assertThat(log.path("extra").path("resultado_id").asString()).isEqualTo(resultadoId.toString());
			assertThat(log.path("message").asString())
				.isEqualTo("sugestão descartada: origem inválida ou tentativa já realizada");
			assertThat(linha).doesNotContain("fixture", "492100", "representacao", "conteudo", "fonte");
		}
		assertThat(status(jobId)).isEqualTo("simulacao_inviavel");
		assertThat(versoes(jobId)).isEqualTo(1);
		verifyNoInteractions(emissores);
	}

	private static UUID jobInviavel() {
		UUID jobId = criarService.criar(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO)).id();
		jdbc.update("UPDATE jobs SET status = 'simulacao_inviavel' WHERE id = ?", jobId);
		return jobId;
	}

	private static String status(UUID jobId) {
		return Objects.requireNonNull(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId));
	}

	private static UUID resultado(UUID jobId, UUID regraId, String veredito, String simulado) {
		UUID prompt = UUID.randomUUID();
		UUID codigo = UUID.randomUUID();
		UUID resultado = UUID.randomUUID();
		artefatos.update("""
				INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
				VALUES (?, ?, 'geracao_codigo', 'fixture', '{}'::jsonb, now())
				""", prompt, jobId);
		artefatos.update("""
				INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES (?, ?, ?, 'python', 'fixture', ?, now())
				""", codigo, jobId, regraId, prompt);
		artefatos.update(
				"""
						INSERT INTO resultados_simulacao (id, job_id, codigo_gerado_id, status, veredito, totais, assercoes, criado_em)
						VALUES (?, ?, ?, 'sucesso', ?, jsonb_build_object('baseline', 480000, 'simulado', ?::numeric,
						    'diferenca_abs', 0, 'diferenca_pct', 0, 'orcamento', 485000), '[]'::jsonb, now())
						""",
				resultado, jobId, codigo, veredito, simulado);
		jdbc.update("""
				INSERT INTO simulacoes (criado_em, regra_id, job_id, codigo_gerado_id, resultado_id)
				VALUES (now(), ?, ?, ?, ?)
				""", regraId, jobId, codigo, resultado);
		return resultado;
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
