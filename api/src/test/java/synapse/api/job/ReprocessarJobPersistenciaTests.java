package synapse.api.job;

import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.DriverManager;
import java.util.ArrayList;
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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import synapse.api.core.outbox.Outbox;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.security.UsuarioAtual;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@EnabledIf("dockerIsAvailable")
class ReprocessarJobPersistenciaTests {

	private static final UUID USUARIO = CriarJobControllerTests.USUARIO;

	private static final UUID DONO_ORIGINAL = UUID.fromString("99999999-9999-4999-8999-999999999999");

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static final String ESPECIFICACOES = """
			[{"ref":"elem.1","construto":"faixa_valor","limite_inferior":40000.123456789,
			  "limite_superior":50000,"efeito":{"tipo":"bonus_fixo","valor":3500.125},
			  "extensao":{"criterios":["a","b"],"ativo":true,"fator":0.123456789012345678901}}]
			""";

	private static PostgreSQLContainer postgres;

	private static AnnotationConfigApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static JdbcTemplate dono;

	private static ReprocessarJobService service;

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
				VALUES (?, 'rh-t079', 'x', 'RH', 'profissional_rh', '2026-01-02T00:00:00Z')
				""", USUARIO);
		contexto = new AnnotationConfigApplicationContext();
		contexto.registerBean(DataSource.class, () -> dataSource);
		contexto.registerBean(JdbcTemplate.class, () -> jdbc);
		contexto.registerBean(PlatformTransactionManager.class, () -> new DataSourceTransactionManager(dataSource));
		contexto.register(Config.class);
		contexto.refresh();
		service = contexto.getBean(ReprocessarJobService.class);
		UsuarioAtual usuarioAtual = mock(UsuarioAtual.class);
		when(usuarioAtual.obter()).thenReturn(new AcessoDoUsuario(DONO_ORIGINAL, PapelDoUsuario.PROFISSIONAL_RH));
		mvc = MockMvcBuilders
			.standaloneSetup(contexto.getBean(ReprocessarJobController.class),
					new BuscarJobController(contexto.getBean(BuscarJobService.class)),
					contexto.getBean(ConfirmarParametrosController.class))
			.addInterceptors(new AutorizacaoJobsInterceptor(usuarioAtual, new AutorizadorDeJob(jdbc)))
			.setControllerAdvice(new ReprocessarJobAdvice(), new ConfirmarParametrosAdvice())
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
	@Import({ CriarJobService.class, ReprocessarJobService.class, BuscarJobService.class,
			ConfirmarParametrosService.class, ExecutarAcaoService.class, MaquinaDeEstadosDoJob.class, Outbox.class,
			ReprocessarJobController.class, AutorizadorDeJob.class, ConfirmarParametrosController.class })
	static class Config {

	}

	@BeforeEach
	void limpar() {
		dono.execute("TRUNCATE submissoes CASCADE");
		jdbc.update("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, ativo, criado_em)
				VALUES (?, 'dono-t079', 'x', 'Dono original', 'profissional_rh', false, '2026-02-01T00:00:00Z')
				ON CONFLICT (id) DO NOTHING
				""", DONO_ORIGINAL);
	}

	@ParameterizedTest
	@ValueSource(strings = { "", "{}" })
	void criaNovoJobHerdandoParametrosEUltimaRegraSemAlterarOriginal(String corpo) throws Exception {
		UUID origem = criarOrigem(true);
		String antes = retrato(origem);
		JsonNode novo = reprocessar(origem, corpo);
		UUID novoId = UUID.fromString(novo.path("id").asString());
		assertThat(novoId).isNotEqualTo(origem);
		assertThat(novo.propertyNames()).containsExactlyInAnyOrder("id", "status", "origem", "competencias",
				"orcamento", "criado_em", "job_origem_id", "regra");
		assertThat(novo.path("status").asString()).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(novo.path("origem").asString()).isEqualTo("reprocessamento");
		assertThat(novo.path("job_origem_id").asString()).isEqualTo(origem.toString());
		assertThat(novo.path("orcamento").decimalValue()).isEqualByComparingTo("485000.1234567890123456789");
		assertThat(novo.path("competencias")).isEqualTo(JSON.readTree("[\"2025-11\"]"));
		Map<String, Object> job = jdbc.queryForMap("SELECT * FROM jobs WHERE id = ?", novoId);
		assertThat(job).containsEntry("usuario_id", DONO_ORIGINAL)
			.containsEntry("submissao_id", null)
			.containsEntry("job_origem_id", origem)
			.containsEntry("status", "aguardando_confirmacao_parametros")
			.containsEntry("tentativas", 0)
			.containsEntry("iniciado_em", null)
			.containsEntry("finalizado_em", null);
		assertThat(job.get("orcamento")).isEqualTo(new BigDecimal("485000.1234567890123456789"));
		assertThat(competencias(novoId)).containsExactlyElementsOf(competencias(origem));
		assertThat(jdbc.queryForObject("SELECT count(*) FROM job_transicoes WHERE job_id = ?", Integer.class, novoId))
			.isEqualTo(1);
		assertThat(jdbc.queryForMap("SELECT status_anterior, status_novo, ator FROM job_transicoes WHERE job_id = ?",
				novoId))
			.containsEntry("status_anterior", null)
			.containsEntry("status_novo", "aguardando_confirmacao_parametros")
			.containsEntry("ator", "usuario");
		Map<String, Object> anterior = jdbc.queryForMap("SELECT * FROM regras WHERE job_id = ? AND versao = 7", origem);
		Map<String, Object> regra = jdbc.queryForMap("SELECT * FROM regras WHERE job_id = ?", novoId);
		assertThat(regra).containsEntry("versao", 1)
			.containsEntry("origem", "reprocessamento")
			.containsEntry("regra_origem_id", anterior.get("id"))
			.containsEntry("nucleo", anterior.get("nucleo"))
			.containsEntry("especificacoes", anterior.get("especificacoes"))
			.containsEntry("hash", anterior.get("hash"))
			.containsEntry("criada_em", job.get("criado_em"));
		assertThat(regra.get("id")).isNotEqualTo(anterior.get("id"));
		assertThat(novo.path("regra").path("id").asString())
			.isEqualTo(Objects.requireNonNull(regra.get("id")).toString());
		assertThat(novo.path("regra").path("versao").asInt()).isEqualTo(1);
		assertThat(novo.path("regra").path("representacao").path("especificacoes"))
			.isEqualTo(JSON.readTree(ESPECIFICACOES));
		assertThat(JSON.readTree(Objects.requireNonNull(regra.get("especificacoes")).toString()))
			.isEqualTo(JSON.readTree(ESPECIFICACOES));
		verificarEvento(novoId, UUID.fromString(novo.path("regra").path("id").asString()), List.of("2025-11"),
				"485000.1234567890123456789");
		assertThat(retrato(origem)).isEqualTo(antes);
		assertThat(jdbc.queryForObject("SELECT count(*) FROM submissoes", Integer.class)).isEqualTo(1);
	}

	@Test
	void overridesMudamSomenteONovoJobESeuEvento() throws Exception {
		UUID origem = criarOrigem(true);
		String antes = retrato(origem);
		JsonNode novo = reprocessar(origem, """
				{"orcamento":600000.1234567890123456789,"competencias":["2025-12","2025-08","2025-09"]}
				""");
		UUID novoId = UUID.fromString(novo.path("id").asString());
		assertThat(novo.path("orcamento").decimalValue()).isEqualByComparingTo("600000.1234567890123456789");
		assertThat(jdbc.queryForObject("SELECT orcamento FROM jobs WHERE id = ?", BigDecimal.class, novoId))
			.isEqualByComparingTo("600000.1234567890123456789");
		assertThat(competencias(novoId)).containsExactly("2025-08", "2025-09", "2025-12");
		verificarEvento(novoId, UUID.fromString(novo.path("regra").path("id").asString()), competencias(novoId),
				"600000.1234567890123456789");
		assertThat(retrato(origem)).isEqualTo(antes);
	}

	@ParameterizedTest
	@ValueSource(strings = { "{\"orcamento\":-1.125}", "{\"competencias\":[\"2025-08\"]}" })
	void overrideIsoladoPreservaOutroParametro(String corpo) throws Exception {
		UUID origem = criarOrigem(false);
		JsonNode novo = reprocessar(origem, corpo);
		boolean mudaOrcamento = corpo.contains("orcamento");
		assertThat(novo.path("orcamento").decimalValue())
			.isEqualByComparingTo(mudaOrcamento ? "-1.125" : "485000.1234567890123456789");
		assertThat(novo.path("competencias"))
			.isEqualTo(JSON.readTree(mudaOrcamento ? "[\"2025-11\"]" : "[\"2025-08\"]"));
	}

	@ParameterizedTest
	@EnumSource(value = JobStatus.class, names = "ARQUIVADO", mode = EnumSource.Mode.EXCLUDE)
	void recusaTodosOsDemaisEstadosSemEfeitos(JobStatus estado) throws Exception {
		UUID origem = criarOrigem(false);
		jdbc.update("UPDATE jobs SET status = ? WHERE id = ?", estado.paraColuna(), origem);
		Map<String, Object> antes = contagens();
		String original = retrato(origem);
		mvc.perform(post("/jobs/{id}/reprocessar", origem))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.codigo").value("estado_invalido"))
			.andExpect(jsonPath("$.mensagem").value("Somente um job arquivado pode ser reprocessado."));
		assertThat(contagens()).isEqualTo(antes);
		assertThat(retrato(origem)).isEqualTo(original);
	}

	@Test
	void inexistenteNaoTemEfeitosColaterais() throws Exception {
		Map<String, Object> antes = contagens();
		mvc.perform(post("/jobs/{id}/reprocessar", UUID.randomUUID()))
			.andExpect(status().isNotFound())
			.andExpect(jsonPath("$.codigo").value("job_nao_encontrado"));
		assertThat(contagens()).isEqualTo(antes);
	}

	@Test
	void arquivadoSemRegraNaoCriaJobParcial() throws Exception {
		UUID origem = criarOrigem(false);
		dono.update("DELETE FROM trilhas_auditoria WHERE job_id = ?", origem);
		dono.update("DELETE FROM regras WHERE job_id = ?", origem);
		Map<String, Object> antes = contagens();
		mvc.perform(post("/jobs/{id}/reprocessar", origem))
			.andExpect(status().isConflict())
			.andExpect(jsonPath("$.codigo").value("estado_invalido"))
			.andExpect(
					jsonPath("$.mensagem").value("O job arquivado não possui uma regra formada para reprocessamento."));
		assertThat(contagens()).isEqualTo(antes);
	}

	@Test
	void getPosteriorEncontraJobSemSubmissaoEComRegraSemeada() throws Exception {
		UUID origem = criarOrigem(true);
		JsonNode novo = reprocessar(origem, "");
		String resposta = assertDoesNotThrow(() -> mvc.perform(get("/jobs/{id}", novo.path("id").asString())))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.origem").value("reprocessamento"))
			.andExpect(jsonPath("$.job_origem_id").value(origem.toString()))
			.andExpect(jsonPath("$.status").value("aguardando_confirmacao_parametros"))
			.andExpect(jsonPath("$.regras.length()").value(1))
			.andExpect(jsonPath("$.regras[0].versao").value(1))
			.andExpect(jsonPath("$.regras[0].id").value(novo.path("regra").path("id").asString()))
			.andReturn()
			.getResponse()
			.getContentAsString();
		assertThat(JSON.readTree(resposta).has("submissao_id")).isFalse();
		assertThat(JSON.readTree(resposta).path("regras").path(0).path("representacao").path("especificacoes"))
			.isEqualTo(JSON.readTree(ESPECIFICACOES));
		mvc.perform(get("/jobs/{id}", origem))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.origem").value("formulario"))
			.andExpect(jsonPath("$.submissao_id").isNotEmpty())
			.andExpect(jsonPath("$.job_origem_id").doesNotExist());
	}

	@ParameterizedTest
	@ValueSource(strings = { "nenhuma", "nucleo", "especificacoes", "ambos", "parametros", "adicionar", "remover" })
	void confirmaRepresentacaoDoGetPreservandoVersoesEOriginal(String edicao) throws Exception {
		UUID origem = criarOrigem(true);
		String original = retrato(origem);
		JsonNode novo = reprocessar(origem, "");
		UUID novoId = UUID.fromString(novo.path("id").asString());
		Map<String, Object> semeada = jdbc.queryForMap("SELECT * FROM regras WHERE job_id = ?", novoId);
		JsonNode representacaoOriginal = consultar(novoId).path("regras").path(0).path("representacao");
		ObjectNode enviada = (ObjectNode) representacaoOriginal.deepCopy();
		boolean mudaNucleo = edicao.equals("nucleo") || edicao.equals("ambos");
		boolean mudaEspecificacoes = List.of("especificacoes", "ambos", "adicionar", "remover").contains(edicao);
		boolean editado = mudaNucleo || mudaEspecificacoes;
		if (mudaNucleo) {
			((ObjectNode) enviada.path("nucleo")).put("percentual", new BigDecimal("0.04"));
		}
		if (edicao.equals("especificacoes") || edicao.equals("ambos")) {
			((ObjectNode) enviada.path("especificacoes").path(0).path("efeito")).put("valor",
					new BigDecimal("3500.123456789012345678901"));
		}
		if (edicao.equals("adicionar")) {
			enviada.withArray("especificacoes").add(JSON.readTree("""
					{"ref":"elem.2","construto":"generico","descricao":"bonus de aniversario",
					"campos":{"fator":0.123456789012345678901}}
					"""));
		}
		if (edicao.equals("remover")) {
			enviada.putArray("especificacoes");
		}
		ObjectNode pedido = JSON.createObjectNode();
		pedido.set("regra", enviada);
		if (edicao.equals("parametros")) {
			pedido.put("orcamento", new BigDecimal("700000.123456789012345678901"));
			pedido.set("competencias", JSON.readTree("[\"2025-10\",\"2025-08\"]"));
		}
		String corpo = JSON.writeValueAsString(pedido);
		assertThat(JSON.<JsonNode>valueToTree(ConfirmarParametrosRequisicao.deJson(corpo).representacao()))
			.isEqualTo(enviada);
		String resposta = mvc
			.perform(post("/jobs/{id}/parameters", novoId).contentType(MediaType.APPLICATION_JSON).content(corpo))
			.andExpect(status().isAccepted())
			.andExpect(jsonPath("$.status").value("gerando_regra"))
			.andExpect(jsonPath("$.origem").value("reprocessamento"))
			.andExpect(jsonPath("$.job_origem_id").value(origem.toString()))
			.andExpect(jsonPath("$.regra.versao").value(editado ? 2 : 1))
			.andExpect(jsonPath("$.regra.origem").value(editado ? "confirmacao_usuario" : "reprocessamento"))
			.andReturn()
			.getResponse()
			.getContentAsString();
		JsonNode confirmado = JSON.readTree(resposta);
		assertThat(confirmado.has("submissao_id")).isFalse();
		assertThat(confirmado.path("regra").path("representacao")).isEqualTo(enviada);
		assertThat(jdbc.queryForMap("SELECT * FROM regras WHERE job_id = ? AND versao = 1", novoId)).isEqualTo(semeada);
		assertThat(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, novoId))
			.isEqualTo("gerando_regra");
		assertThat(jdbc.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Integer.class, novoId))
			.isEqualTo(editado ? 2 : 1);
		Map<String, Object> utilizada = jdbc.queryForMap("SELECT * FROM regras WHERE job_id = ? AND versao = ?", novoId,
				editado ? 2 : 1);
		assertThat(JSON.readTree(Objects.requireNonNull(utilizada.get("nucleo")).toString()))
			.isEqualTo(enviada.path("nucleo"));
		assertThat(JSON.readTree(Objects.requireNonNull(utilizada.get("especificacoes")).toString()))
			.isEqualTo(enviada.path("especificacoes"));
		assertThat(Objects.requireNonNull(utilizada.get("id")).toString())
			.isEqualTo(confirmado.path("regra").path("id").asString());
		assertThat(utilizada.get("hash"))
			.isEqualTo(HashDaRegra.calcular(ConfirmarParametrosRequisicao.deJson(corpo).representacao()));
		if (editado) {
			assertThat(utilizada.get("regra_origem_id")).isEqualTo(semeada.get("id"));
			assertThat(utilizada.get("hash")).isNotEqualTo(semeada.get("hash"));
		}
		else {
			assertThat(utilizada).isEqualTo(semeada);
		}
		if (edicao.equals("parametros")) {
			assertThat(jdbc.queryForObject("SELECT orcamento FROM jobs WHERE id = ?", BigDecimal.class, novoId))
				.isEqualByComparingTo("700000.123456789012345678901");
			assertThat(competencias(novoId)).containsExactly("2025-08", "2025-10");
			assertThat(confirmado.path("orcamento")).isEqualTo(pedido.path("orcamento"));
			assertThat(confirmado.path("competencias")).isEqualTo(JSON.readTree("[\"2025-08\",\"2025-10\"]"));
		}
		else {
			assertThat(confirmado.path("orcamento")).isEqualTo(novo.path("orcamento"));
			assertThat(confirmado.path("competencias")).isEqualTo(novo.path("competencias"));
		}
		JsonNode regras = consultar(novoId).path("regras");
		assertThat(regras.size()).isEqualTo(editado ? 2 : 1);
		assertThat(regras.path(0).path("representacao")).isEqualTo(representacaoOriginal);
		assertThat(regras.path(editado ? 1 : 0).path("representacao")).isEqualTo(enviada);
		String payload = Objects.requireNonNull(jdbc.queryForObject(
				"SELECT payload::text FROM outbox_events WHERE job_id = ? AND tipo = 'parametros-confirmados'",
				String.class, novoId));
		ContratoDeEvento.validar("parametros-confirmados", payload);
		assertThat(JSON.readTree(payload).path("regra_id")).isEqualTo(confirmado.path("regra").path("id"));
		JsonNode trilha = JSON.readTree(Objects.requireNonNull(jdbc.queryForObject(
				"SELECT conclusao::text FROM trilhas_auditoria WHERE job_id = ? AND no = 'confirmacao'", String.class,
				novoId)));
		assertThat(trilha.path("editado_pelo_usuario").asBoolean()).isEqualTo(editado);
		List<String> corrigidos = new ArrayList<>();
		if (mudaNucleo) {
			corrigidos.add("nucleo.percentual");
		}
		if (mudaEspecificacoes) {
			corrigidos.add(edicao.equals("adicionar") ? "elem.2" : "elem.1");
		}
		assertThat(trilha.path("campos_corrigidos")).isEqualTo(JSON.valueToTree(corrigidos));
		assertThat(trilha.path("resumo").asString())
			.isEqualTo(editado ? "usuário corrigiu " + String.join(", ", corrigidos) + " antes de confirmar"
					: "usuário confirmou os parâmetros");
		assertThat(retrato(origem)).isEqualTo(original);
	}

	private static JsonNode consultar(UUID jobId) throws Exception {
		return JSON.readTree(mvc.perform(get("/jobs/{id}", jobId))
			.andExpect(status().isOk())
			.andReturn()
			.getResponse()
			.getContentAsString());
	}

	@Test
	void falhaNoOutboxReverteJobRegraETransicao() {
		UUID origem = criarOrigem(true);
		Map<String, Object> antes = contagens();
		String original = retrato(origem);
		dono.execute("REVOKE INSERT ON outbox_events FROM synapse_api");
		try {
			assertThatThrownBy(() -> service.reprocessar(origem, ReprocessarJobRequisicao.deJson(null)))
				.isInstanceOf(DataAccessException.class)
				.hasMessageContaining("INSERT INTO outbox_events");
		}
		finally {
			dono.execute("GRANT INSERT ON outbox_events TO synapse_api");
		}
		assertThat(contagens()).isEqualTo(antes);
		assertThat(retrato(origem)).isEqualTo(original);
	}

	private static UUID criarOrigem(boolean extensoes) {
		JobCriadoDto job = contexto.getBean(CriarJobService.class)
			.criar(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO));
		var representacao = ConfirmarParametrosRequisicao.deJson(ConfirmarParametrosControllerTests.CONFIRMAR)
			.representacao();
		var completa = JSON.readValue("{\"nucleo\":" + JSON.writeValueAsString(representacao.nucleo())
				+ ",\"especificacoes\":" + (extensoes ? ESPECIFICACOES : "[]") + "}", RepresentacaoRegraDto.class);
		UUID regraId = Objects.requireNonNull(jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, regra_origem_id, nucleo, especificacoes, hash, criada_em)
				VALUES (?, 7, 'confirmacao_usuario', ?, ?::jsonb, ?::jsonb, ?, now()) RETURNING id
				""", UUID.class, job.id(), job.regra().id(), JSON.writeValueAsString(representacao.nucleo()),
				extensoes ? ESPECIFICACOES : "[]", HashDaRegra.calcular(completa)));
		var maquina = contexto.getBean(MaquinaDeEstadosDoJob.class);
		maquina.transicionar(job.id(), JobStatus.SIMULANDO, "evento", null);
		maquina.transicionar(job.id(), JobStatus.AGUARDANDO_DECISAO_USUARIO, "evento", null);
		contexto.getBean(ExecutarAcaoService.class).aplicar(job.id(), AcaoJob.ARQUIVAR);
		jdbc.update("UPDATE jobs SET usuario_id = ?, tentativas = 3, iniciado_em = criado_em WHERE id = ?",
				DONO_ORIGINAL, job.id());
		jdbc.update("""
				INSERT INTO trilhas_auditoria (evento_id, job_id, no, concluido_em, regra_id, conclusao)
				VALUES (?, ?, 'confirmacao', now(), ?, '{"resumo":"confirmação anterior"}'::jsonb)
				""", UUID.randomUUID(), job.id(), regraId);
		return job.id();
	}

	private static JsonNode reprocessar(UUID origem, String corpo) throws Exception {
		var pedido = post("/jobs/{id}/reprocessar", origem);
		if (!corpo.isEmpty()) {
			pedido.contentType(MediaType.APPLICATION_JSON).content(corpo);
		}
		var resposta = mvc.perform(pedido).andExpect(status().isCreated()).andReturn().getResponse();
		JsonNode novo = JSON.readTree(resposta.getContentAsString());
		assertThat(resposta.getHeader("Location")).isEqualTo("/api/jobs/" + novo.path("id").asString());
		return novo;
	}

	private static void verificarEvento(UUID jobId, UUID regraId, List<String> competencias, String orcamento)
			throws Exception {
		Map<String, Object> evento = jdbc
			.queryForMap("SELECT tipo, payload::text AS payload FROM outbox_events WHERE job_id = ?", jobId);
		assertThat(evento).containsEntry("tipo", "regra-submetida");
		String payload = Objects.requireNonNull((String) evento.get("payload"));
		ContratoDeEvento.validar("regra-submetida", payload);
		ObjectNode arvore = (ObjectNode) JSON.readTree(payload);
		// Fora da comparação estrita: um valor monetário se confere por precisão, não por
		// tipo de nó JSON.
		assertThat(arvore.path("orcamento").isNumber()).isTrue();
		assertThat(arvore.path("orcamento").decimalValue()).isEqualByComparingTo(orcamento);
		arvore.remove("orcamento");
		assertThat(arvore).isEqualTo(JSON.valueToTree(Map.of("job_id", jobId.toString(), "origem", "reprocessamento",
				"competencias", competencias, "regra_id", regraId.toString())));
	}

	private static List<String> competencias(UUID jobId) {
		return jdbc.queryForList("SELECT unnest(competencias) FROM jobs WHERE id = ?", String.class, jobId);
	}

	private static Map<String, Object> contagens() {
		return jdbc.queryForMap("""
				SELECT (SELECT count(*) FROM jobs) AS jobs, (SELECT count(*) FROM regras) AS regras,
				       (SELECT count(*) FROM submissoes) AS submissoes, (SELECT count(*) FROM outbox_events) AS eventos,
				       (SELECT count(*) FROM job_transicoes) AS transicoes, (SELECT count(*) FROM job_acoes) AS acoes,
				       (SELECT count(*) FROM trilhas_auditoria) AS trilhas
				""");
	}

	private static String retrato(UUID jobId) {
		return Objects.requireNonNull(jdbc.queryForObject(
				"""
						SELECT jsonb_build_object('job', to_jsonb(j), 'submissao', to_jsonb(s),
						    'regras', (SELECT jsonb_agg(to_jsonb(r) ORDER BY r.id) FROM regras r WHERE r.job_id = j.id),
						    'transicoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id) FROM job_transicoes t WHERE t.job_id = j.id),
						    'acoes', (SELECT jsonb_agg(to_jsonb(a) ORDER BY a.id) FROM job_acoes a WHERE a.job_id = j.id),
						    'trilhas', (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id) FROM trilhas_auditoria t WHERE t.job_id = j.id),
						    'eventos', (SELECT jsonb_agg(to_jsonb(e) ORDER BY e.id) FROM outbox_events e WHERE e.job_id = j.id),
						    'simulacoes', (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id) FROM simulacoes s WHERE s.job_id = j.id))::text
						FROM jobs j LEFT JOIN submissoes s ON s.id = j.submissao_id WHERE j.id = ?
						""",
				String.class, jobId));
	}

}
