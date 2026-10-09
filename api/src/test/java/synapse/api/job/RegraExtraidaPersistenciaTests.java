package synapse.api.job;

import java.math.BigDecimal;
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
import org.jspecify.annotations.Nullable;
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
import tools.jackson.databind.DeserializationFeature;
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

	/** Os três parâmetros, com a precisão decimal que um valor monetário exige. */
	private static final String PARAMETROS_COMPLETOS = """
			{"orcamento":500000.1234567890123456789,"meta_venda":12000000.5,
			 "competencias":["2025-09","2025-10"]}
			""";

	/**
	 * Lê número como {@code BigDecimal}, como a api lê os artefatos: por {@code double},
	 * uma afirmação sobre a precisão de um valor monetário passaria sem significar nada.
	 */
	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

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
		// A versão nascida de texto sempre tem parâmetros, ainda que vazios, e o hash os
		// cobre: é o que faz uma correção que muda só o orçamento gerar versão nova.
		assertThat(linha.get("hash")).isEqualTo(
				HashDaRegra.calcular(Objects.requireNonNull(RepresentacaoExtraida.validada(REPRESENTACAO_PARCIAL)),
						ParametrosDaSimulacao.NENHUM));
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

	// --- Parâmetros da simulação ------------------------------------------------------

	@Test
	void parametrosExtraidosVaoParaOJobParaAVersaoEParaOEventoRepublicado() throws Exception {
		Job job = criarJob("texto", "gerando_regra", null);
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL, PARAMETROS_COMPLETOS);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(valor(job.id(), "orcamento")).isEqualTo("500000.1234567890123456789");
		assertThat(valor(job.id(), "meta_venda")).isEqualTo("12000000.5");
		assertThat(competencias(job.id())).containsExactly("2025-09", "2025-10");

		// A versão raiz leva os parâmetros como o codegen os gravou, sem a api
		// reescrevê-los.
		String parametros = parametrosDaVersao(job.id());
		ContratoDeEvento.validarDominio("parametros-simulacao.schema.json", parametros);
		assertThat(JSON.readTree(parametros)).isEqualTo(JSON.readTree(PARAMETROS_COMPLETOS));

		String payload = unicoRegraSubmetida(job.id());
		ContratoDeEvento.validar("regra-submetida", payload);
		RegraSubmetidaDto evento = JSON.readValue(payload, RegraSubmetidaDto.class);
		assertThat(evento.orcamento()).isEqualByComparingTo("500000.1234567890123456789");
		assertThat(evento.meta_venda()).isEqualByComparingTo("12000000.5");
		assertThat(evento.competencias()).containsExactly("2025-09", "2025-10");

		JsonNode detalhe = consultar(job.id());
		assertThat(detalhe.path("orcamento").decimalValue()).isEqualByComparingTo("500000.1234567890123456789");
		assertThat(detalhe.path("meta_venda").decimalValue()).isEqualByComparingTo("12000000.5");
		JsonNode resumo = resumoNaListagem(job.id());
		assertThat(resumo.path("orcamento").decimalValue()).isEqualByComparingTo("500000.1234567890123456789");
		assertThat(resumo.path("meta_venda").decimalValue()).isEqualByComparingTo("12000000.5");
	}

	/**
	 * O texto que não disse parâmetro algum deixa o job como nasceu: sem orçamento, sem
	 * meta e com todas as competências publicadas. A versão guarda o objeto vazio, que é
	 * "nenhum parâmetro foi dito", e não nulo, que é "esta versão não nasceu de texto".
	 */
	@Test
	void extracaoSemParametrosDeixaOJobComoNasceu() throws Exception {
		Job job = criarJob("texto", "gerando_regra", null);
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(valor(job.id(), "orcamento")).isNull();
		assertThat(valor(job.id(), "meta_venda")).isNull();
		assertThat(competencias(job.id())).containsExactly("2025-08", "2025-11");
		assertThat(parametrosDaVersao(job.id())).isEqualTo("{}");

		String payload = unicoRegraSubmetida(job.id());
		ContratoDeEvento.validar("regra-submetida", payload);
		assertThat(JSON.readTree(payload).propertyNames()).containsExactlyInAnyOrder("job_id", "origem", "competencias",
				"submissao_id", "regra_id");

		JsonNode detalhe = consultar(job.id());
		assertThat(detalhe.has("orcamento")).isFalse();
		assertThat(detalhe.has("meta_venda")).isFalse();
		assertThat(resumoNaListagem(job.id()).has("orcamento")).isFalse();
	}

	/**
	 * O parâmetro que o texto não disse não é apagado nem recebe padrão: um job que já
	 * tem orçamento o conserva quando a extração só traz a meta.
	 */
	@Test
	void parametroAusenteNaExtracaoNaoApagaOQueOJobJaTem() throws Exception {
		Job job = criarJob("texto", "gerando_regra");
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL, """
				{"meta_venda": 26000000.0}
				""");

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(valor(job.id(), "orcamento")).isEqualTo("485000.1234567890123456789");
		assertThat(valor(job.id(), "meta_venda")).isEqualTo("26000000.0");
		assertThat(competencias(job.id())).containsExactly("2025-08", "2025-11");
		RegraSubmetidaDto evento = JSON.readValue(unicoRegraSubmetida(job.id()), RegraSubmetidaDto.class);
		assertThat(evento.orcamento()).isEqualByComparingTo("485000.1234567890123456789");
		assertThat(evento.meta_venda()).isEqualByComparingTo("26000000.0");
	}

	/**
	 * Valor inválido é gravado como veio, e o evento republicado o leva: é a validação de
	 * domínio do ciclo seguinte que o aponta como conflito, com a referência
	 * {@code parametros.<campo>}. O banco não tem restrição de faixa justamente para
	 * isso.
	 */
	@Test
	void orcamentoNegativoEMetaZeradaSaoGravadosComoVieram() throws Exception {
		Job job = criarJob("texto", "gerando_regra", null);
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL, """
				{"orcamento": -1000.0, "meta_venda": 0}
				""");

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(valor(job.id(), "orcamento")).isEqualTo("-1000.0");
		assertThat(valor(job.id(), "meta_venda")).isEqualTo("0");
		String payload = unicoRegraSubmetida(job.id());
		ContratoDeEvento.validar("regra-submetida", payload);
		RegraSubmetidaDto evento = JSON.readValue(payload, RegraSubmetidaDto.class);
		assertThat(evento.orcamento()).isEqualByComparingTo("-1000.0");
		assertThat(evento.meta_venda()).isEqualByComparingTo("0");
		assertThat(contagem("persistida", "nenhum")).isEqualTo(1.0);
	}

	/**
	 * Uma competência fora das publicadas também é gravada: o período é o que o texto
	 * disse, e quem o recusa é a validação de domínio, não esta gravação.
	 */
	@Test
	void periodoForaDasCompetenciasPublicadasEGravadoComoVeio() throws Exception {
		Job job = criarJob("texto", "gerando_regra", null);
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL, """
				{"competencias": ["2026-03"]}
				""");

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(competencias(job.id())).containsExactly("2026-03");
		String payload = unicoRegraSubmetida(job.id());
		ContratoDeEvento.validar("regra-submetida", payload);
		assertThat(JSON.readValue(payload, RegraSubmetidaDto.class).competencias()).containsExactly("2026-03");
	}

	/**
	 * O artefato evolui de forma aditiva: um parâmetro que esta versão da api ainda não
	 * conhece não derruba o consumo nem impede os que ela conhece de chegarem ao job. A
	 * versão guarda o artefato inteiro, com o campo novo.
	 */
	@Test
	void parametroQueAApiAindaNaoConheceNaoImpedeOConsumo() throws Exception {
		Job job = criarJob("texto", "gerando_regra", null);
		String comCampoNovo = """
				{"orcamento":500000.0,"parametro_de_amanha":"qualquer coisa"}
				""";
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL, comCampoNovo);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(valor(job.id(), "orcamento")).isEqualTo("500000.0");
		assertThat(JSON.readTree(parametrosDaVersao(job.id()))).isEqualTo(JSON.readTree(comCampoNovo));
		assertThat(contagem("persistida", "nenhum")).isEqualTo(1.0);
	}

	/**
	 * A coluna do job guarda o período na forma canônica que o modelo de dados declara -
	 * ordem crescente, sem repetição -, e o artefato do codegen fica como ele o gravou. A
	 * ordem é forma, não valor: os meses simulados são os mesmos.
	 */
	@Test
	void periodoEntraNoJobNaFormaCanonicaSemMexerNoArtefato() throws Exception {
		Job job = criarJob("texto", "gerando_regra", null);
		String comoVeio = """
				{"competencias":["2025-11","2025-09","2025-09"]}
				""";
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL, comoVeio);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(competencias(job.id())).containsExactly("2025-09", "2025-11");
		assertThat(JSON.readValue(unicoRegraSubmetida(job.id()), RegraSubmetidaDto.class).competencias())
			.containsExactly("2025-09", "2025-11");
		assertThat(JSON.readTree(parametrosDaVersao(job.id()))).isEqualTo(JSON.readTree(comoVeio));
	}

	/**
	 * A reentrega não regrava parâmetro: se regravasse, desfaria uma correção posterior
	 * do usuário sobre o mesmo job.
	 */
	@Test
	void reentregaNaoRegravaOsParametrosDoJob() throws Exception {
		Job job = criarJob("texto", "gerando_regra", null);
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL, PARAMETROS_COMPLETOS);
		var evento = new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId);
		this.consumidor.receber(evento);
		dono.update("UPDATE jobs SET orcamento = 600000, meta_venda = NULL WHERE id = ?", job.id());

		this.consumidor.receber(evento);

		assertThat(valor(job.id(), "orcamento")).isEqualTo("600000");
		assertThat(valor(job.id(), "meta_venda")).isNull();
		assertThat(versoes(job.id())).isEqualTo(1);
		unicoRegraSubmetida(job.id());
		assertThat(contagem("duplicada", "reentrega")).isEqualTo(1.0);
	}

	/**
	 * Parâmetros fora do contrato são artefato inválido, não parâmetro inválido: a
	 * reentrega os repetiria para sempre, então o descarte é definitivo e nada é gravado.
	 */
	@ParameterizedTest
	@ValueSource(strings = { """
			{"orcamento": "quinhentos mil"}
			""", """
			{"orcamento": null}
			""", """
			{"competencias": []}
			""", """
			{"competencias": ["2025-13"]}
			""", """
			{"competencias": "2025-09"}
			""", """
			[]
			""" })
	void parametrosForaDoContratoSaoDescartadosSemGravarNada(String parametros) throws Exception {
		Job job = criarJob("texto", "gerando_regra", null);
		UUID extracaoId = criarExtracao(job, REPRESENTACAO_PARCIAL, parametros);

		this.consumidor.receber(new RegraExtraidaDto(job.id(), job.submissaoId(), extracaoId));

		assertThat(versoes(job.id())).isZero();
		assertThat(eventosNoOutbox(job.id())).isZero();
		assertThat(valor(job.id(), "orcamento")).isNull();
		assertThat(competencias(job.id())).containsExactly("2025-08", "2025-11");
		assertThat(contagem("descartada", "parametros_invalidos")).isEqualTo(1.0);
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
		return criarJob(tipo, statusDoJob, new BigDecimal("485000.1234567890123456789"));
	}

	/**
	 * O job de texto ou voz nasce sem orçamento (T-231) e só o recebe se a extração o
	 * trouxer; {@code orcamento} nulo é esse job.
	 */
	private static Job criarJob(String tipo, String statusDoJob, @Nullable BigDecimal orcamento) {
		UUID submissaoId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em)
				VALUES (?, ?, 'dobrar a comissão dos vendedores da marca 10 no aniversário da loja', now())
				RETURNING id
				""", UUID.class, USUARIO, tipo));
		UUID jobId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, criado_em)
				VALUES ('gerando_regra', ?, ?, ?, ?, now()) RETURNING id
				""", UUID.class, USUARIO, submissaoId,
				new SqlArrayValue("text", List.of("2025-08", "2025-11").toArray()), orcamento));
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
		return criarExtracao(job, representacao, "{}");
	}

	private static UUID criarExtracao(Job job, String representacao, String parametros) {
		UUID prompt = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
				VALUES (?, 'extracao_parametros', 'fixture', '{}'::jsonb, now()) RETURNING id
				""", UUID.class, job.id()));
		UUID resposta = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO respostas_modelo (job_id, prompt_id, conteudo, criado_em)
				VALUES (?, ?, 'fixture', now()) RETURNING id
				""", UUID.class, job.id(), prompt));
		return Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO extracoes_regras
					(job_id, submissao_id, resposta_id, representacao, rebaixamentos, parametros, criado_em)
				VALUES (?, ?, ?, ?::jsonb, '[]'::jsonb, ?::jsonb, now()) RETURNING id
				""", UUID.class, job.id(), job.submissaoId(), resposta, representacao, parametros));
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

	/**
	 * O valor de uma coluna numérica do job como o banco o guarda, em texto: comparar
	 * {@code numeric} por texto é o que mostra a escala preservada, que um {@code double}
	 * perderia.
	 */
	private static @Nullable String valor(UUID jobId, String coluna) {
		return jdbc.queryForObject("SELECT %s::text FROM jobs WHERE id = ?".formatted(coluna), String.class, jobId);
	}

	private static List<String> competencias(UUID jobId) {
		return jdbc.queryForList("SELECT unnest(competencias) FROM jobs WHERE id = ?", String.class, jobId);
	}

	private static String parametrosDaVersao(UUID jobId) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT parametros::text FROM regras WHERE job_id = ?", String.class, jobId));
	}

	/** O item deste job na listagem, conferido contra {@code JobResumo}. */
	private static JsonNode resumoNaListagem(UUID jobId) throws Exception {
		JsonNode itens = JSON.readTree(listar()).path("itens");
		for (JsonNode item : itens) {
			if (jobId.toString().equals(item.path("id").asString())) {
				ContratoDeEvento.validarRespostaHttp("JobResumo", item.toString());
				return item;
			}
		}
		throw new AssertionError("job %s não apareceu na listagem".formatted(jobId));
	}

	private double contagem(String resultado, String motivo) {
		Counter contador = this.registry.find("regra.extraida.consumo")
			.tag("resultado", resultado)
			.tag("motivo", motivo)
			.counter();
		return (contador != null) ? contador.count() : 0;
	}

}
