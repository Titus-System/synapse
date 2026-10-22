package synapse.api.job;

import java.sql.Connection;
import java.sql.DriverManager;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Stream;

import javax.sql.DataSource;

import ch.qos.logback.classic.spi.ILoggingEvent;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import liquibase.Contexts;
import liquibase.Liquibase;
import liquibase.database.DatabaseFactory;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.ClassLoaderResourceAccessor;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.DeserializationFeature;
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
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.outbox.Outbox;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.JobEventosService.DesfechoAplicado;
import synapse.api.job.JobEventosService.FimDaIteracao;
import synapse.api.job.JobEventosService.SugestaoAplicada;
import synapse.api.job.VersoesDaRegra.VersaoRegra;

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

	private static final JsonMapper DECIMAIS = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

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
		contexto.registerBean(JsonMapper.class, () -> new JsonMapper());
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
	@Import({ JobRepository.class, JobService.class, RodadasRepository.class, JobEventosService.class,
			MaquinaDeEstadosDoJob.class, Outbox.class, RodadasCorrecaoRepository.class, VersoesDaRegra.class,
			CorrelationContext.class })
	static class Config {

	}

	@Test
	void gravaUmaAlternativaEPublicaEntradaCompletaNoContratoOficial() throws Exception {
		UUID jobId = jobInviavel();
		UUID origem = versaoId(jobId, 1);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		SugestaoAplicada aplicada = Objects.requireNonNull(
				sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246"), 1));
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
				sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246"), 1));

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
		SugestaoAplicada aplicada = Objects.requireNonNull(sugestaoService.aplicarSugestaoAdaptacao(jobId, original,
				resultadoOriginal, representacao("0.0246"), 1));
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
				sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246"), 1));
		String payload = Objects.requireNonNull(jdbc.queryForObject(
				"SELECT payload::text FROM outbox_events WHERE job_id = ? AND payload->>'regra_id' = ?", String.class,
				jobId, aplicada.versao().id().toString()));
		ContratoDeEvento.validar("regra-submetida", payload);
		assertThat(new JsonMapper().readTree(payload).path("origem").asString()).isEqualTo("texto");
	}

	/**
	 * A alternativa que não coube não é desfecho: a proposta seguinte parte dela, e cada
	 * reentrega encontra a versão que a primeira entrega criou. A api não conta
	 * tentativas, só registra o número que o codegen informou.
	 */
	@Test
	void reentregasNaoReabremOCicloNemDuplicamAsTentativas() {
		UUID jobId = jobInviavel();
		UUID original = versaoId(jobId, 1);
		UUID resultadoOriginal = resultado(jobId, original, "inviavel", "492100");
		SugestaoAplicada primeira = Objects.requireNonNull(sugestaoService.aplicarSugestaoAdaptacao(jobId, original,
				resultadoOriginal, representacao("0.0246"), 1));
		var conclusao = contexto.getBean(JobEventosService.class);
		assertThat(conclusao.concluirSimulacao(jobId, resultadoOriginal, DesfechoDaSimulacao.INVIAVEL)).isNull();
		assertThat(status(jobId)).isEqualTo("gerando_regra");
		UUID resultadoPrimeira = resultado(jobId, primeira.versao().id(), "inviavel", "490000");

		DesfechoAplicado intermediario = Objects
			.requireNonNull(conclusao.concluirSimulacao(jobId, resultadoPrimeira, DesfechoDaSimulacao.INVIAVEL));
		assertThat(intermediario.intermediario()).isTrue();
		assertThat(status(jobId)).isEqualTo("simulando");
		assertThat(conclusao.concluirSimulacao(jobId, resultadoPrimeira, DesfechoDaSimulacao.INVIAVEL))
			.extracting(DesfechoAplicado::intermediario)
			.isEqualTo(true);
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, original, resultadoOriginal, representacao("0.0246"),
				1))
			.isNull();

		SugestaoAplicada segunda = Objects.requireNonNull(sugestaoService.aplicarSugestaoAdaptacao(jobId,
				primeira.versao().id(), resultadoPrimeira, representacao("0.023"), 2));
		assertThat(segunda.origem()).isEqualTo(JobStatus.SIMULANDO);
		assertThat(segunda.versao().versao()).isEqualTo(3);
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, primeira.versao().id(), resultadoPrimeira,
				representacao("0.023"), 2))
			.isNull();
		assertThat(conclusao.concluirSimulacao(jobId, resultadoPrimeira, DesfechoDaSimulacao.INVIAVEL)).isNull();

		assertThat(status(jobId)).isEqualTo("gerando_regra");
		assertThat(jdbc.queryForList("SELECT tentativa FROM regras WHERE job_id = ? ORDER BY versao", Integer.class,
				jobId))
			.containsExactly(null, 1, 2);
		assertThat(jdbc.queryForObject("SELECT regra_origem_id FROM regras WHERE id = ?", UUID.class,
				segunda.versao().id()))
			.isEqualTo(primeira.versao().id());
		assertThat(transicoes(jobId)).containsExactly("simulacao_inviavel>gerando_regra:sugestao_adaptacao_proposta",
				"gerando_regra>simulando:simulacao_concluida_antecipada",
				"simulando>gerando_regra:sugestao_adaptacao_proposta");
		assertThat(jdbc.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(3);
	}

	/**
	 * Cada alternativa é simulada nas condições da regra original: o
	 * {@code regra-submetida} repete o orçamento e a meta do job em toda tentativa.
	 */
	@Test
	void regraSubmetidaDeCadaTentativaLevaOOrcamentoEAMetaDoJob() throws Exception {
		UUID jobId = jobInviavel();
		jdbc.update("UPDATE jobs SET meta_venda = 26000000.77 WHERE id = ?", jobId);
		List<VersaoRegra> alternativas = iterar(jobId, 3);

		for (VersaoRegra alternativa : alternativas) {
			String payload = Objects.requireNonNull(jdbc.queryForObject("""
					SELECT payload::text FROM outbox_events
					WHERE job_id = ? AND tipo = 'regra-submetida' AND payload->>'regra_id' = ?
					""", String.class, jobId, alternativa.id().toString()));
			ContratoDeEvento.validar("regra-submetida", payload);
			var evento = new JsonMapper().readValue(payload, RegraSubmetidaDto.class);
			assertThat(evento.orcamento()).isEqualByComparingTo("485000.1234567890123456789");
			assertThat(evento.meta_venda()).isEqualByComparingTo("26000000.77");
			assertThat(evento.competencias()).containsExactly("2025-11");
		}
		assertThat(alternativas).extracting(VersaoRegra::versao).containsExactly(2, 3, 4);
		assertThat(jdbc.queryForList("SELECT tentativa FROM regras WHERE job_id = ? ORDER BY versao", Integer.class,
				jobId))
			.containsExactly(null, 1, 2, 3);
	}

	@Test
	void alternativaInviavelDeixaOJobEmProcessamentoSemMotivoNemSimulacaoInviavelNaTrilha() {
		UUID jobId = jobInviavel();
		VersaoRegra alternativa = iterar(jobId, 1).getFirst();
		UUID resultado = resultado(jobId, alternativa.id(), "inviavel", "490000");

		contexto.getBean(JobEventosService.class).concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.INVIAVEL);

		JobDetalhadoDto job = contexto.getBean(JobService.class).buscar(jobId);
		assertThat(job.status()).isEqualTo("simulando");
		assertThat(job.motivo()).isNull();
		assertThat(transicoes(jobId)).last().isEqualTo("gerando_regra>simulando:simulacao_concluida_antecipada");
		assertThat(jdbc.queryForObject("SELECT resultado_id FROM simulacoes WHERE regra_id = ?", UUID.class,
				alternativa.id()))
			.isEqualTo(resultado);
	}

	/**
	 * A proposta seguinte pode chegar antes do resultado da alternativa de que ela parte:
	 * as filas não têm ordem entre si. Nas duas ordens o usuário não vê a alternativa que
	 * não coube - nenhum {@code resultado} sai -, e o resultado atrasado é de uma versão
	 * anterior.
	 */
	@ParameterizedTest
	@ValueSource(booleans = { true, false })
	void propostaSeguinteNasDuasOrdensDeEntrega(boolean propostaPrimeiro) {
		UUID jobId = jobInviavel();
		VersaoRegra alternativa = iterar(jobId, 1).getFirst();
		UUID resultado = resultado(jobId, alternativa.id(), "inviavel", "490000");
		jdbc.update("UPDATE simulacoes SET resultado_id = NULL WHERE resultado_id = ?", resultado);
		jdbc.update("UPDATE jobs SET status = 'simulando' WHERE id = ?", jobId);
		List<EventoSse> eventos = new ArrayList<>();
		EmissoresSse emissores = emissoresQueGuardam(jobId, eventos);
		SimpleMeterRegistry registro = new SimpleMeterRegistry();
		var sugestoes = new SugestaoAdaptacaoConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(registro));
		var conclusoes = new SimulacaoConcluidaConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(registro));
		var proposta = new SugestaoAdaptacaoPropostaDto(jobId, alternativa.id(), resultado, representacao("0.023"), 2);
		var conclusao = new SimulacaoConcluidaDto(jobId, resultado, "sucesso", "inviavel", null, null, null, null);

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

		assertThat(eventos).containsExactly(EventoSse.de("estado",
				EventoEstadoDto.transicao(jobId, JobStatus.SIMULANDO, JobStatus.GERANDO_REGRA, null)));
		assertThat(status(jobId)).isEqualTo("gerando_regra");
		assertThat(versoes(jobId)).isEqualTo(3);
		assertThat(transicoes(jobId)).last().isEqualTo("simulando>gerando_regra:sugestao_adaptacao_proposta");
		assertThat(jdbc.queryForObject("SELECT resultado_id FROM simulacoes WHERE regra_id = ?", UUID.class,
				alternativa.id()))
			.isEqualTo(resultado);
		assertThat(contagem(registro, "sugestao.adaptacao.proposta.consumo", "tentativa", "2", "resultado", "aplicada"))
			.isEqualTo(1.0);
		assertThat(
				contagem(registro, "sugestao.adaptacao.proposta.consumo", "tentativa", "2", "resultado", "descartada"))
			.isEqualTo(1.0);
		assertThat(contagem(registro, "simulacao.concluida.consumo", "desfecho", "inviavel", "resultado",
				"versao_anterior"))
			.isEqualTo(propostaPrimeiro ? 2.0 : 1.0);
		assertThat(
				contagem(registro, "simulacao.concluida.consumo", "desfecho", "inviavel", "resultado", "intermediaria"))
			.isEqualTo(propostaPrimeiro ? 0.0 : 1.0);
	}

	/**
	 * O fim das tentativas pode chegar antes do resultado da terceira, que ele mesmo
	 * amarra. Nas duas ordens o job termina inviável uma vez só, e o resultado atrasado
	 * ou reentregue encontra o job fora do processamento.
	 */
	@ParameterizedTest
	@ValueSource(booleans = { true, false })
	void semAlternativaNasDuasOrdensDeEntrega(boolean semAlternativaPrimeiro) throws Exception {
		UUID jobId = jobInviavel();
		VersaoRegra terceira = iterar(jobId, 3).getLast();
		UUID resultado = resultado(jobId, terceira.id(), "inviavel", "486000");
		jdbc.update("UPDATE simulacoes SET resultado_id = NULL WHERE resultado_id = ?", resultado);
		jdbc.update("UPDATE jobs SET status = 'simulando' WHERE id = ?", jobId);
		List<EventoSse> eventos = new ArrayList<>();
		EmissoresSse emissores = emissoresQueGuardam(jobId, eventos);
		SimpleMeterRegistry registro = new SimpleMeterRegistry();
		var etapas = new EtapaAlteradaConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(registro));
		var conclusoes = new SimulacaoConcluidaConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(registro));
		var fim = new EtapaAlteradaDto(jobId, "sugestao_adaptacao", "sem_alternativa", null, null, null);
		var conclusao = new SimulacaoConcluidaDto(jobId, resultado, "sucesso", "inviavel", null, null, null, null);

		List<ILoggingEvent> logs;
		try (var captura = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			if (semAlternativaPrimeiro) {
				etapas.receber(fim);
				conclusoes.receber(conclusao);
			}
			else {
				conclusoes.receber(conclusao);
				etapas.receber(fim);
			}
			etapas.receber(fim);
			conclusoes.receber(conclusao);
			logs = captura.eventos();
		}

		EventoSse etapa = EventoSse.de("etapa", new EventoEtapaDto(jobId, "sugestao_adaptacao", "sem_alternativa"));
		assertThat(eventos).containsExactly(etapa, EventoSse.de("estado", EventoEstadoDto.transicao(jobId,
				JobStatus.SIMULANDO, JobStatus.SIMULACAO_INVIAVEL, MotivoDaParada.NENHUMA_TAXA_COUBE)), etapa);
		JobDetalhadoDto job = contexto.getBean(JobService.class).buscar(jobId);
		assertThat(job.status()).isEqualTo("simulacao_inviavel");
		assertThat(job.motivo()).isEqualTo(MotivoDaParada.NENHUMA_TAXA_COUBE);
		assertThat(transicoes(jobId)).filteredOn(transicao -> transicao.startsWith("simulando>simulacao_inviavel"))
			.containsExactly("simulando>simulacao_inviavel:sem_alternativa");
		assertThat(jdbc.queryForObject("SELECT resultado_id FROM simulacoes WHERE regra_id = ?", UUID.class,
				terceira.id()))
			.isEqualTo(resultado);
		assertThat(versoes(jobId)).isEqualTo(4);
		assertThat(contagem(registro, "sugestao.adaptacao.encerramento", "causa", "sem_alternativa", "resultado",
				"aplicado"))
			.isEqualTo(1.0);
		assertThat(contagem(registro, "sugestao.adaptacao.encerramento", "causa", "sem_alternativa", "resultado",
				"sem_efeito"))
			.isEqualTo(1.0);
		assertThat(contagem(registro, "simulacao.concluida.consumo", "desfecho", "inviavel", "resultado",
				"estado_incompativel"))
			.isEqualTo(semAlternativaPrimeiro ? 2.0 : 1.0);
		assertThat(logs).extracting(ILoggingEvent::getFormattedMessage)
			.contains("tentativas de taxa nova encerradas sem alternativa; job inviável",
					"sem_alternativa sem iteração em curso; estado do job mantido");
		for (ILoggingEvent registroDeLog : logs) {
			String linha = CapturaDeLog.emJson(registroDeLog);
			ContratoDeEvento.validarLog(linha);
			var registroJson = new JsonMapper().readTree(linha);
			assertThat(registroJson.path("job_id").asString()).isEqualTo(jobId.toString());
			for (String campo : List.of("message", "extra", "exception")) {
				assertThat(registroJson.path(campo).toString()).doesNotContain("486000", "percentual", "0.02");
			}
		}
	}

	/**
	 * As lojas fora da regra ficam no baseline qualquer que seja a taxa: quando só elas
	 * já custam mais que o orçamento, a razão do fim diz isso, no stream e na consulta.
	 */
	@ParameterizedTest(name = "{0}")
	@MethodSource("pisosDasLojasForaDaRegra")
	void semAlternativaExplicaOPisoDasLojasForaDaRegra(String caso, @Nullable String decomposicao,
			boolean regraParaTodasAsLojas, String esperado) {
		UUID jobId = jobInviavel();
		VersaoRegra alternativa = iterar(jobId, 1).getFirst();
		UUID resultado = resultado(jobId, alternativa.id(), "inviavel", "486000");
		if (decomposicao != null) {
			artefatos.update("UPDATE resultados_simulacao SET decomposicao = ?::jsonb WHERE id = ?", decomposicao,
					resultado);
		}
		if (regraParaTodasAsLojas) {
			artefatos.update("UPDATE regras SET nucleo = nucleo || '{\"loja\": []}'::jsonb WHERE id = ?",
					alternativa.id());
		}
		jdbc.update("UPDATE simulacoes SET resultado_id = NULL WHERE resultado_id = ?", resultado);
		jdbc.update("UPDATE jobs SET status = 'simulando' WHERE id = ?", jobId);
		List<EventoSse> eventos = new ArrayList<>();
		EmissoresSse emissores = emissoresQueGuardam(jobId, eventos);
		SimpleMeterRegistry registro = new SimpleMeterRegistry();
		var etapas = new EtapaAlteradaConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(registro));
		var conclusoes = new SimulacaoConcluidaConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(registro));

		conclusoes.receber(new SimulacaoConcluidaDto(jobId, resultado, "sucesso", "inviavel", null, null, null, null));
		etapas.receber(new EtapaAlteradaDto(jobId, "sugestao_adaptacao", "sem_alternativa", null, null, null));

		assertThat(eventos).contains(EventoSse.de("estado",
				EventoEstadoDto.transicao(jobId, JobStatus.SIMULANDO, JobStatus.SIMULACAO_INVIAVEL, esperado)));
		JobDetalhadoDto job = contexto.getBean(JobService.class).buscar(jobId);
		assertThat(job.status()).isEqualTo("simulacao_inviavel");
		assertThat(job.motivo()).isEqualTo(esperado);
	}

	static Stream<Arguments> pisosDasLojasForaDaRegra() {
		String explicito = "O orçamento de R$ 485.000,00 é menor que as comissões das lojas fora da regra (R$ 550.000,00), que a sugestão não altera. Nenhuma redução de taxa faz a regra caber: aumente o orçamento ou revise o alcance da regra.";
		String lojas = "{\"loja_absoluto\": {\"13\": 40000.00, \"98\": 250000.50, \"99\": 299999.50}}";
		return Stream.of(Arguments.of("piso acima do orçamento", lojas, false, explicito),
				Arguments.of("piso abaixo do orçamento", "{\"loja_absoluto\": {\"13\": 40000.00, \"99\": 299999.50}}",
						false, MotivoDaParada.NENHUMA_TAXA_COUBE),
				Arguments.of("piso igual ao orçamento", "{\"loja_absoluto\": {\"13\": 1.00, \"99\": 485000.00}}", false,
						MotivoDaParada.NENHUMA_TAXA_COUBE),
				Arguments.of("regra para todas as lojas", lojas, true, MotivoDaParada.NENHUMA_TAXA_COUBE),
				Arguments.of("sem quebra absoluta por loja", "{\"loja\": {\"13\": 10.00}}", false,
						MotivoDaParada.NENHUMA_TAXA_COUBE),
				Arguments.of("sem decomposição", null, false, MotivoDaParada.NENHUMA_TAXA_COUBE));
	}

	/**
	 * Sem alternativa na regra original, quem leva o job a inviável é a
	 * {@code simulacao-concluida} dela, que chega antes ou depois.
	 */
	@ParameterizedTest
	@ValueSource(strings = { "simulacao_inviavel", "simulando" })
	void semAlternativaDaRegraOriginalNaoMoveOJob(String estado) {
		UUID jobId = jobInviavel();
		UUID resultado = resultado(jobId, versaoId(jobId, 1), "inviavel", "492100");
		jdbc.update("UPDATE jobs SET status = ? WHERE id = ?", estado, jobId);
		Integer antes = jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class,
				jobId);

		var aplicada = sugestaoService.aplicarEtapaAlterada(jobId, EtapaDoGrafo.SUGESTAO_ADAPTACAO, "sem_alternativa",
				null);

		assertThat(aplicada.transicao()).isNull();
		assertThat(aplicada.fim()).isEqualTo(FimDaIteracao.SEM_ALTERNATIVA_SEM_EFEITO);
		assertThat(status(jobId)).isEqualTo(estado);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(antes);
		if ("simulando".equals(estado)) {
			sugestaoService.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.INVIAVEL);
			assertThat(status(jobId)).isEqualTo("simulacao_inviavel");
			assertThat(contexto.getBean(JobService.class).buscar(jobId).motivo())
				.isEqualTo(DesfechoDaSimulacao.INVIAVEL.razaoLocalizada());
		}
	}

	@ParameterizedTest
	@CsvSource({ "DECISAO,true,", "DECISAO,false,provedor_indisponivel",
			"SUGESTAO_ADAPTACAO,true,provedor_indisponivel", "SUGESTAO_ADAPTACAO,false," })
	void falhaDoCodegenDuranteAIteracaoPreservaOErro(EtapaDoGrafo etapa, boolean resultadoPrimeiro,
			@org.jspecify.annotations.Nullable String causa) {
		UUID jobId = jobInviavel();
		VersaoRegra alternativa = iterar(jobId, 2).getLast();
		UUID resultado = resultado(jobId, alternativa.id(), "inviavel", "488000");
		if (resultadoPrimeiro) {
			sugestaoService.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.INVIAVEL);
		}

		var aplicada = sugestaoService.aplicarEtapaAlterada(jobId, etapa, "erro", causa);

		assertThat(aplicada.fim()).isEqualTo(FimDaIteracao.FALHA);
		assertThat(aplicada.transicao()).isEqualTo(EventoEstadoDto.transicao(jobId, JobStatus.SIMULANDO, JobStatus.ERRO,
				MotivoDaParada.razaoDaFalha(causa)));
		assertThat(status(jobId)).isEqualTo("erro");
		assertThat(transicoes(jobId)).last().isEqualTo("simulando>erro:" + MotivoDaParada.falhaNaEtapa(etapa, causa));
		assertThat(criarService.buscar(jobId).motivo()).isEqualTo(MotivoDaParada.razaoDaFalha(causa));
		assertThat(sugestaoService.aplicarEtapaAlterada(jobId, etapa, "erro", causa).transicao()).isNull();
	}

	@Test
	void falhaDoCodegenForaDaIteracaoSegueOCaminhoDeQualquerEtapa() {
		UUID inviavel = jobInviavel();
		resultado(inviavel, versaoId(inviavel, 1), "inviavel", "492100");
		var naOriginal = sugestaoService.aplicarEtapaAlterada(inviavel, EtapaDoGrafo.SUGESTAO_ADAPTACAO, "erro", null);
		assertThat(naOriginal.fim()).isNull();
		assertThat(naOriginal.transicao()).isNull();
		assertThat(status(inviavel)).isEqualTo("simulacao_inviavel");

		UUID gerando = jobInviavel();
		jdbc.update("UPDATE jobs SET status = 'gerando_regra' WHERE id = ?", gerando);
		var antesDaSimulacao = sugestaoService.aplicarEtapaAlterada(gerando, EtapaDoGrafo.DECISAO, "erro", null);
		assertThat(antesDaSimulacao.fim()).isNull();
		assertThat(status(gerando)).isEqualTo("erro");
	}

	@ParameterizedTest
	@ValueSource(ints = { 1, 3 })
	void alternativaViavelEmQualquerTentativaVaiADecisaoDoUsuario(int tentativas) {
		UUID jobId = jobInviavel();
		VersaoRegra alternativa = iterar(jobId, tentativas).getLast();
		UUID resultado = resultado(jobId, alternativa.id(), "viavel", "484000");
		jdbc.update("UPDATE simulacoes SET resultado_id = NULL WHERE resultado_id = ?", resultado);

		DesfechoAplicado aplicado = Objects
			.requireNonNull(sugestaoService.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.VIAVEL));

		assertThat(aplicado.intermediario()).isFalse();
		assertThat(aplicado.simulacaoId()).isNotNull();
		JobDetalhadoDto job = contexto.getBean(JobService.class).buscar(jobId);
		assertThat(job.status()).isEqualTo("aguardando_decisao_usuario");
		assertThat(Objects.requireNonNull(job.simulacao()).regra_id()).isEqualTo(alternativa.id());
	}

	@Test
	void alternativaComErroDeExecucaoEncerraOJobEmErro() {
		UUID jobId = jobInviavel();
		VersaoRegra alternativa = iterar(jobId, 2).getLast();
		UUID resultado = resultadoComFalha(jobId, alternativa.id(), "erro_codigo");

		sugestaoService.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.ERRO_CODIGO);

		assertThat(status(jobId)).isEqualTo("erro");
		assertThat(sugestaoService.aplicarEtapaAlterada(jobId, EtapaDoGrafo.SUGESTAO_ADAPTACAO, "sem_alternativa", null)
			.transicao()).isNull();
		assertThat(status(jobId)).isEqualTo("erro");
	}

	@ParameterizedTest
	@ValueSource(strings = { "gerando_regra", "simulando" })
	void resultadoIntermediarioRegistraOLogSemValoresNemSse(String estado) throws Exception {
		UUID jobId = jobInviavel();
		VersaoRegra alternativa = iterar(jobId, 1).getFirst();
		UUID resultado = resultado(jobId, alternativa.id(), "inviavel", "490000");
		jdbc.update("UPDATE jobs SET status = ? WHERE id = ?", estado, jobId);
		EmissoresSse emissores = mock(EmissoresSse.class);
		SimpleMeterRegistry registro = new SimpleMeterRegistry();
		var consumidor = new SimulacaoConcluidaConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(registro));

		try (var anterior = new CorrelationContext().abrir("contexto-anterior", null);
				var captura = new CapturaDeLog(SimulacaoConcluidaConsumidor.class)) {
			consumidor
				.receber(new SimulacaoConcluidaDto(jobId, resultado, "sucesso", "inviavel", null, null, null, null));
			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			var log = new JsonMapper().readTree(linha);
			assertThat(log.path("level").asString()).isEqualTo("INFO");
			assertThat(log.path("job_id").asString()).isEqualTo(jobId.toString());
			assertThat(log.path("message").asString()).isEqualTo(
					"resultado inviável de alternativa registrado; job aguarda a próxima tentativa ou o fim da iteração");
			assertThat(log.path("extra").path("resultado_id").asString()).isEqualTo(resultado.toString());
			assertThat(linha).doesNotContain("490000", "percentual", "fixture");
		}
		verifyNoInteractions(emissores);
		assertThat(status(jobId)).isEqualTo("simulando");
		assertThat(
				contagem(registro, "simulacao.concluida.consumo", "desfecho", "inviavel", "resultado", "intermediaria"))
			.isEqualTo(1.0);
	}

	@Test
	void falhaNoOutboxReverteATentativaSeguinteInteira() {
		UUID jobId = jobInviavel();
		VersaoRegra alternativa = iterar(jobId, 1).getFirst();
		UUID resultado = resultado(jobId, alternativa.id(), "inviavel", "490000");
		sugestaoService.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.INVIAVEL);
		Integer transicoes = jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class,
				jobId);
		artefatos.execute("REVOKE INSERT ON outbox_events FROM synapse_api");
		try {
			assertThatExceptionOfType(DataAccessException.class).isThrownBy(() -> sugestaoService
				.aplicarSugestaoAdaptacao(jobId, alternativa.id(), resultado, representacao("0.023"), 2));
		}
		finally {
			artefatos.execute("GRANT INSERT ON outbox_events TO synapse_api");
		}
		assertThat(status(jobId)).isEqualTo("simulando");
		assertThat(jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(transicoes);
		assertThat(versoes(jobId)).isEqualTo(2);
	}

	@Test
	void propostaAntesDoEventoDoWorkerAplicaDesfechoEReabreNaMesmaTransacao() {
		UUID jobId = jobInviavel();
		jdbc.update("UPDATE jobs SET status = 'simulando' WHERE id = ?", jobId);
		UUID origem = versaoId(jobId, 1);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246"), 1))
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
		var sugestoes = new SugestaoAdaptacaoConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(new SimpleMeterRegistry()));
		var conclusoes = new SimulacaoConcluidaConsumidor(contexto.getBean(JobEventosService.class), emissores,
				new CorrelationContext(), new AppMetrics(new SimpleMeterRegistry()));
		var proposta = new SugestaoAdaptacaoPropostaDto(jobId, regraId, resultadoId, representacao("0.0099"), 1);
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
	void naoAceitaResultadoDeOutroJobOuAlteracaoAlemDasTaxas() {
		UUID jobId = jobInviavel();
		UUID outro = jobInviavel();
		UUID origem = versaoId(jobId, 1);
		UUID resultadoOutro = resultado(outro, versaoId(outro, 1), "inviavel", "492100");
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultadoOutro, representacao("0.0246"), 1))
			.isNull();
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		var nova = representacao("0.0246");
		var diferente = new RepresentacaoRegraDto(nova.nucleo(),
				List.of(new tools.jackson.databind.json.JsonMapper().readTree("{\"tipo\":\"outro\"}")));
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, diferente, 1)).isNull();
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.025"), 1))
			.isNull();
		assertThat(versoes(jobId)).isEqualTo(1);
	}

	@Test
	void gravaAlternativaQueReduzTaxasPorCargoEEfeitosPercentuaisPreservandoAsEspecificacoes() throws Exception {
		UUID jobId = jobInviavel();
		UUID origem = versaoComEspecificacoes(jobId);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		RepresentacaoRegraDto proposta = DECIMAIS.readValue(ReducaoDasTaxasTests.PROPOSTA, RepresentacaoRegraDto.class);

		SugestaoAplicada aplicada = Objects
			.requireNonNull(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, proposta, 1));

		assertThat(aplicada.versao().versao()).isEqualTo(3);
		assertThat(status(jobId)).isEqualTo("gerando_regra");
		assertThat(jdbc.queryForObject("""
				SELECT nucleo = ?::jsonb AND especificacoes = ?::jsonb AND regra_origem_id = ? AND tentativa = 1
				FROM regras WHERE id = ?
				""", Boolean.class, DECIMAIS.writeValueAsString(proposta.nucleo()),
				DECIMAIS.writeValueAsString(proposta.especificacoes()), origem, aplicada.versao().id()))
			.isTrue();
		String payload = Objects.requireNonNull(jdbc.queryForObject("""
				SELECT payload::text FROM outbox_events
				WHERE job_id = ? AND tipo = 'regra-submetida' AND payload->>'regra_id' = ?
				""", String.class, jobId, aplicada.versao().id().toString()));
		ContratoDeEvento.validar("regra-submetida", payload);
	}

	@Test
	void recusaAlternativaDeRegraComEspecificacoesQueMudaAlemDasTaxas() {
		UUID jobId = jobInviavel();
		UUID origem = versaoComEspecificacoes(jobId);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		String proposta = ReducaoDasTaxasTests.PROPOSTA;

		for (String alterada : List.of(proposta.replace("\"valor\":350.00", "\"valor\":300"),
				proposta.replace("\"percentual\":0.0243", "\"percentual\":0.031"),
				proposta.replace("acima de R$ 40.000", "acima de R$ 30.000"))) {
			assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado,
					DECIMAIS.readValue(alterada, RepresentacaoRegraDto.class), 1))
				.isNull();
		}
		assertThat(status(jobId)).isEqualTo("simulacao_inviavel");
		assertThat(versoes(jobId)).isEqualTo(2);
	}

	@Test
	void consumidorContaELogaAAlternativaComTaxasPorCargoSemValores() throws Exception {
		UUID jobId = jobInviavel();
		UUID origem = versaoComEspecificacoes(jobId);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		SimpleMeterRegistry registro = new SimpleMeterRegistry();
		var consumidor = new SugestaoAdaptacaoConsumidor(sugestaoService, mock(EmissoresSse.class),
				new CorrelationContext(), new AppMetrics(registro));
		RepresentacaoRegraDto alterada = DECIMAIS.readValue(
				ReducaoDasTaxasTests.PROPOSTA.replace("\"valor\":350.00", "\"valor\":300"),
				RepresentacaoRegraDto.class);
		RepresentacaoRegraDto reduzida = DECIMAIS.readValue(ReducaoDasTaxasTests.PROPOSTA, RepresentacaoRegraDto.class);

		try (var captura = new CapturaDeLog(SugestaoAdaptacaoConsumidor.class)) {
			consumidor.receber(new SugestaoAdaptacaoPropostaDto(jobId, origem, resultado, alterada, 1));
			consumidor.receber(new SugestaoAdaptacaoPropostaDto(jobId, origem, resultado, reduzida, 1));

			assertThat(captura.eventos()).hasSize(2);
			List<String> mensagens = new ArrayList<>();
			for (ILoggingEvent evento : captura.eventos()) {
				String linha = CapturaDeLog.emJson(evento);
				ContratoDeEvento.validarLog(linha);
				assertThat(new JsonMapper().readTree(linha).path("job_id").asString()).isEqualTo(jobId.toString());
				assertThat(linha).doesNotContain("0.0243", "0.0324", "0.0405", "taxas_por_cargo", "limiar",
						"acima de R$", "representacao");
				mensagens.add(evento.getFormattedMessage());
			}
			assertThat(mensagens).containsExactly("sugestão descartada: origem inválida ou proposta já aplicada",
					"sugestao-adaptacao-proposta aplicada; ciclo do codegen reaberto");
		}
		assertThat(
				contagem(registro, "sugestao.adaptacao.proposta.consumo", "tentativa", "1", "resultado", "descartada"))
			.isEqualTo(1.0);
		assertThat(contagem(registro, "sugestao.adaptacao.proposta.consumo", "tentativa", "1", "resultado", "aplicada"))
			.isEqualTo(1.0);
		assertThat(status(jobId)).isEqualTo("gerando_regra");
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
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, atual.id(), resultado, representacao("0.025"), 1))
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
		assertThat(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado, representacao("0.0246"), 1))
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
		var consumidor = new SugestaoAdaptacaoConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(new SimpleMeterRegistry()));
		var proposta = new SugestaoAdaptacaoPropostaDto(jobId, regraId, resultadoId, representacao("0.0246"), 1);
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
				mock(EmissoresSse.class), new CorrelationContext(), new AppMetrics(new SimpleMeterRegistry()));
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
		var consumidor = new SugestaoAdaptacaoConsumidor(sugestaoService, emissores, new CorrelationContext(),
				new AppMetrics(new SimpleMeterRegistry()));
		try (var anterior = new CorrelationContext().abrir("contexto-anterior", null);
				var captura = new CapturaDeLog(SugestaoAdaptacaoConsumidor.class)) {
			consumidor.receber(new SugestaoAdaptacaoPropostaDto(jobId, regraId, resultadoId, representacao("0"), 1));
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
				.isEqualTo("sugestão descartada: origem inválida ou proposta já aplicada");
			assertThat(linha).doesNotContain("fixture", "492100", "representacao", "conteudo", "fonte");
		}
		assertThat(status(jobId)).isEqualTo("simulacao_inviavel");
		assertThat(versoes(jobId)).isEqualTo(1);
		verifyNoInteractions(emissores);
	}

	@Test
	void resultadoIntermediarioNaoSobrescreveOFimEmitidoDepoisDoSeuCommit() {
		UUID jobId = jobInviavel();
		VersaoRegra alternativa = iterar(jobId, 1).getFirst();
		UUID resultado = resultado(jobId, alternativa.id(), "inviavel", "490000");
		List<EventoSse> eventos = new ArrayList<>();
		EmissoresSse emissores = emissoresQueGuardam(jobId, eventos);
		AppMetrics metricas = new AppMetrics(new SimpleMeterRegistry());
		var etapas = new EtapaAlteradaConsumidor(sugestaoService, emissores, new CorrelationContext(), metricas);
		JobEventosService intercalado = mock(JobEventosService.class);
		doAnswer(chamada -> {
			DesfechoAplicado aplicado = sugestaoService.concluirSimulacao(jobId, resultado,
					DesfechoDaSimulacao.INVIAVEL);
			// Reproduz o outro consumidor depois do commit, antes de o primeiro emitir
			// SSE.
			assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
			etapas.receber(new EtapaAlteradaDto(jobId, "sugestao_adaptacao", "sem_alternativa", null, null, null));
			return aplicado;
		}).when(intercalado).concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.INVIAVEL);
		var conclusoes = new SimulacaoConcluidaConsumidor(intercalado, emissores, new CorrelationContext(), metricas);

		conclusoes.receber(new SimulacaoConcluidaDto(jobId, resultado, "sucesso", "inviavel", null, null, null, null));

		assertThat(status(jobId)).isEqualTo("simulacao_inviavel");
		assertThat(eventos).containsExactly(
				EventoSse.de("etapa", new EventoEtapaDto(jobId, "sugestao_adaptacao", "sem_alternativa")),
				EventoSse.de("estado", EventoEstadoDto.transicao(jobId, JobStatus.SIMULANDO,
						JobStatus.SIMULACAO_INVIAVEL, MotivoDaParada.NENHUMA_TAXA_COUBE)));
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

	/**
	 * Leva o job inviável pelas {@code tentativas} primeiras alternativas, como codegen e
	 * worker as produziriam: cada uma parte da anterior, que não coube. Devolve as
	 * versões criadas; a última ainda não tem resultado.
	 */
	private static List<VersaoRegra> iterar(UUID jobId, int tentativas) {
		List<String> percentuais = List.of("0.0246", "0.0240", "0.0235");
		List<VersaoRegra> alternativas = new ArrayList<>();
		UUID origem = versaoId(jobId, 1);
		UUID resultado = resultado(jobId, origem, "inviavel", "492100");
		for (int tentativa = 1; tentativa <= tentativas; tentativa++) {
			if (tentativa > 1) {
				resultado = resultado(jobId, origem, "inviavel", "490000");
				sugestaoService.concluirSimulacao(jobId, resultado, DesfechoDaSimulacao.INVIAVEL);
			}
			VersaoRegra versao = Objects
				.requireNonNull(sugestaoService.aplicarSugestaoAdaptacao(jobId, origem, resultado,
						representacao(percentuais.get(tentativa - 1)), tentativa))
				.versao();
			alternativas.add(versao);
			origem = versao.id();
		}
		return alternativas;
	}

	/** As transições depois da criação, como {@code anterior>novo:motivo}. */
	private static List<String> transicoes(UUID jobId) {
		return jdbc.queryForList("""
				SELECT status_anterior || '>' || status_novo || ':' || COALESCE(motivo, '') FROM job_transicoes
				WHERE job_id = ? AND status_anterior IS NOT NULL ORDER BY ocorrido_em, id
				""", String.class, jobId);
	}

	private static EmissoresSse emissoresQueGuardam(UUID jobId, List<EventoSse> eventos) {
		EmissoresSse emissores = mock(EmissoresSse.class);
		doAnswer(chamada -> {
			assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
			eventos.add(chamada.getArgument(1, EventoSse.class));
			return null;
		}).when(emissores).emitir(eq(jobId), any());
		return emissores;
	}

	private static double contagem(SimpleMeterRegistry registro, String nome, String tag, String valor, String outraTag,
			String outroValor) {
		Counter contador = registro.find(nome).tag(tag, valor).tag(outraTag, outroValor).counter();
		return (contador != null) ? contador.count() : 0.0;
	}

	private static UUID resultadoComFalha(UUID jobId, UUID regraId, String status) {
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
		artefatos.update("""
				INSERT INTO resultados_simulacao (id, job_id, codigo_gerado_id, status, assercoes, criado_em)
				VALUES (?, ?, ?, ?, '[]'::jsonb, now())
				""", resultado, jobId, codigo, status);
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

	/** A versão 2 do job, com taxas por cargo e especificações, vira a versão atual. */
	private static UUID versaoComEspecificacoes(UUID jobId) {
		RepresentacaoRegraDto regra = DECIMAIS.readValue(ReducaoDasTaxasTests.ORIGEM, RepresentacaoRegraDto.class);
		var agora = java.time.Instant.now();
		return contexto.getBean(VersoesDaRegra.class)
			.resolver(jobId, regra, null, HashDaRegra.calcular(regra), "confirmacao_usuario", versaoId(jobId, 1),
					java.sql.Timestamp.from(agora), agora)
			.id();
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
