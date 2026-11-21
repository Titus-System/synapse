package synapse.api.auditoria;

import java.math.BigDecimal;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.StreamSupport;

import ch.qos.logback.classic.spi.ILoggingEvent;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.sun.net.httpserver.HttpServer;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import synapse.api.ApiApplication;
import synapse.api.job.CapturaDeLog;
import synapse.api.job.ContratoDeEvento;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@code GET /auditoria/jobs/{id}/resumo} pela cadeia HTTP real, com o banco migrado e
 * tokens assinados.
 */
@EnabledIf("dockerIsAvailable")
class ResumoAuditoriaPersistenciaTests {

	private static final UUID A = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final UUID AUDITOR = UUID.fromString("cccccccc-cccc-4ccc-8ccc-cccccccccccc");

	private static final String ISSUER = "https://emissor-de-teste.invalid/realms/synapse";

	private static final Instant INICIO = Instant.parse("2026-11-10T12:00:00Z");

	private static final String ROTA = "/auditoria/jobs/%s/resumo";

	private static final String NUCLEO_V1 = """
			{"loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.025}""";

	private static final String NUCLEO_V2 = """
			{"loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.030}""";

	private static final String SIMULADO_ANTERIOR = "598000.123456789";

	private static final String SIMULADO_ATUAL = "640000.987654321";

	private static final String PROMPT_PRIVADO = "PROMPT-PRIVADO-DO-TESTE";

	private static final String RESPOSTA_PRIVADA = "RESPOSTA-PRIVADA-DO-TESTE";

	private static final String CODIGO_PRIVADO = "def aplicar(): return 'CODIGO-PRIVADO-DO-TESTE'";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static PostgreSQLContainer postgres;

	private static ConfigurableApplicationContext contexto;

	private static HttpServer jwks;

	private static RSAKey chave;

	private static JdbcTemplate dono;

	private static String base;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void iniciar() throws Exception {
		chave = new RSAKeyGenerator(2048).keyID("teste-resumo").generate();
		jwks = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
		jwks.createContext("/jwks", exchange -> {
			byte[] corpo = new JWKSet(chave.toPublicJWK()).toString().getBytes(StandardCharsets.UTF_8);
			exchange.getResponseHeaders().set("Content-Type", "application/json");
			exchange.sendResponseHeaders(200, corpo.length);
			try (var saida = exchange.getResponseBody()) {
				saida.write(corpo);
			}
		});
		jwks.start();
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.keycloak.enabled=true", "--app.keycloak.issuer-uri=" + ISSUER,
					"--app.keycloak.jwk-set-uri=http://127.0.0.1:" + jwks.getAddress().getPort() + "/jwks",
					"--app.postgres.host=" + postgres.getHost(), "--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
					"--app.postgres.password=senha-de-teste", "--spring.rabbitmq.dynamic=false",
					"--spring.rabbitmq.listener.simple.auto-startup=false", "--management.health.rabbit.enabled=false",
					"--management.health.db.enabled=false", "--app.outbox.enabled=false",
					"--app.transcription.processor.enabled=false");
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		base = "http://localhost:" + contexto.getEnvironment().getProperty("local.server.port");
	}

	@AfterAll
	static void encerrar() {
		if (contexto != null) {
			contexto.close();
		}
		if (postgres != null) {
			postgres.stop();
		}
		if (jwks != null) {
			jwks.stop(0);
		}
	}

	@BeforeEach
	void preparar() {
		dono.execute("TRUNCATE usuarios CASCADE");
		dono.update("""
				INSERT INTO usuarios (id, login, nome, papel, keycloak_sub, criado_em)
				VALUES (?, 'rh.a', 'RH A', 'profissional_rh', 'subject-a', now()),
				       (?, 'auditoria', 'Auditor', 'auditor', 'subject-auditor', now())
				""", A, AUDITOR);
	}

	@Test
	void cadeiaRealExigeSessaoPermiteSomenteAuditorEDistingueOJob() throws Exception {
		UUID job = job(INICIO);
		String rota = ROTA.formatted(job);
		assertThat(chamar(rota, "").statusCode()).isEqualTo(401);
		assertThat(chamar(rota, "token-invalido").statusCode()).isEqualTo(401);
		HttpResponse<String> rh = chamar(rota, rh());
		assertThat(rh.statusCode()).isEqualTo(403);
		assertThat(JSON.readTree(rh.body()).path("codigo").asString()).isEqualTo("sem_permissao");
		HttpResponse<String> inexistente = chamar(ROTA.formatted(UUID.randomUUID()), auditor());
		assertThat(inexistente.statusCode()).isEqualTo(404);
		assertThat(JSON.readTree(inexistente.body()).path("codigo").asString()).isEqualTo("job_nao_encontrado");
		HttpResponse<String> malformado = chamar(ROTA.formatted("nao-e-uuid"), auditor());
		assertThat(malformado.statusCode()).isEqualTo(400);
		assertThat(JSON.readTree(malformado.body()).path("codigo").asString()).isEqualTo("requisicao_invalida");
		JsonNode vazio = resumo(job);
		assertThat(vazio.path("simulacoes").toString()).isEqualTo("{\"registradas\":0,\"sucesso\":0,\"falha\":0}");
		assertThat(vazio.has("versao_vigente")).isFalse();
		assertThat(vazio.path("versoes").isEmpty()).isTrue();
		assertThat(vazio.path("comparacoes").isEmpty()).isTrue();
	}

	@Test
	void versaoCorrigidaTrazSoOPercentualEARaizNaoTrazAlteracoes() throws Exception {
		UUID job = job(INICIO);
		UUID v1 = versao(job, 1, "extracao", NUCLEO_V1, "[]", null, INICIO);
		UUID v2 = versao(job, 2, "correcao", NUCLEO_V2, "[]", v1, INICIO.plusSeconds(60));
		HttpResponse<String> resposta = chamar(ROTA.formatted(job), auditor());
		assertThat(resposta.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("ResumoDossieAuditoria", resposta.body());
		JsonNode versoes = JSON.readTree(resposta.body()).path("versoes");
		assertThat(versoes.size()).isEqualTo(2);
		assertThat(versoes.path(0).path("id").asString()).isEqualTo(v1.toString());
		assertThat(versoes.path(0).path("numero").asInt()).isEqualTo(1);
		assertThat(versoes.path(0).has("regra_origem_id")).isFalse();
		assertThat(versoes.path(0).path("alteracoes").isEmpty()).isTrue();
		assertThat(versoes.path(1).path("id").asString()).isEqualTo(v2.toString());
		assertThat(versoes.path(1).path("regra_origem_id").asString()).isEqualTo(v1.toString());
		assertThat(versoes.path(1).path("alteracoes").size()).isEqualTo(1);
		assertThat(resposta.body())
			.contains("\"alteracoes\":[{\"elemento_ref\":\"nucleo.percentual\",\"anterior\":0.025,\"novo\":0.030}]");
	}

	@Test
	void elementosSaoCasadosPeloRefEParteDeUmLadoSoNaoTemOOutroValor() throws Exception {
		UUID job = job(INICIO);
		UUID v1 = versao(job, 1, "extracao", """
				{"loja":["13"],"percentual":0.025,"vigencia":{"inicio":"2026-10","fim":"2026-10"}}""", """
				[{"ref":"elem.1","construto":"generico","descricao":"antes"},
				 {"ref":"elem.2","construto":"generico","descricao":"removido"}]""", null, INICIO);
		versao(job, 2, "correcao", """
				{"loja":["13"],"percentual":0.025,"marca":["10"]}""", """
				[{"ref":"elem.10","construto":"generico","descricao":"decimo"},
				 {"ref":"elem.1","construto":"generico","descricao":"depois"},
				 {"ref":"elem.3","construto":"generico","descricao":"incluido"}]""", v1, INICIO.plusSeconds(60));
		JsonNode alteracoes = resumo(job).path("versoes").path(1).path("alteracoes");
		assertThat(StreamSupport.stream(alteracoes.spliterator(), false)
			.map(alteracao -> alteracao.path("elemento_ref").asString())
			.toList()).containsExactly("nucleo.marca", "nucleo.vigencia", "elem.1", "elem.2", "elem.3", "elem.10");
		assertParte(alteracoes.path(0), false, true);
		assertThat(alteracoes.path(0).path("novo").toString()).isEqualTo("[\"10\"]");
		assertParte(alteracoes.path(1), true, false);
		assertThat(alteracoes.path(1).path("anterior").path("inicio").asString()).isEqualTo("2026-10");
		assertParte(alteracoes.path(2), true, true);
		assertThat(alteracoes.path(2).path("anterior").path("descricao").asString()).isEqualTo("antes");
		assertThat(alteracoes.path(2).path("novo").path("descricao").asString()).isEqualTo("depois");
		assertParte(alteracoes.path(3), true, false);
		assertParte(alteracoes.path(4), false, true);
		assertParte(alteracoes.path(5), false, true);
	}

	@Test
	void correcaoSoDoOrcamentoAparecePeloParametroComoParteDoNucleo() throws Exception {
		UUID job = job(INICIO);
		UUID v1 = versaoComParametros(job, 1, "extracao", NUCLEO_V1, """
				{"orcamento":600000,"meta_venda":28000000,"competencias":["2026-10"]}""", null, INICIO);
		versaoComParametros(job, 2, "correcao", NUCLEO_V1, """
				{"orcamento":650000,"competencias":["2026-10"]}""", v1, INICIO.plusSeconds(60));
		assertThat(corpoDoResumo(job)).contains("""
				"numero":2,"regra_origem_id":"%s","alteracoes":[\
				{"elemento_ref":"nucleo.meta_venda","anterior":28000000},\
				{"elemento_ref":"nucleo.orcamento","anterior":600000,"novo":650000}]}""".formatted(v1));
	}

	@Test
	void periodoQueOTextoNaoDisseNaoApareceComoIncluidoNaCorrecao() throws Exception {
		UUID job = job(INICIO);
		UUID v1 = versaoComParametros(job, 1, "extracao", NUCLEO_V1, "{}", null, INICIO);
		UUID v2 = versaoComParametros(job, 2, "correcao", NUCLEO_V1, """
				{"competencias":["2025-08","2025-09","2025-10","2025-11","2025-12"],"orcamento":600000}""", v1,
				INICIO.plusSeconds(60));
		versaoComParametros(job, 3, "correcao", NUCLEO_V1, """
				{"competencias":["2025-11"],"orcamento":600000}""", v2, INICIO.plusSeconds(120));
		String corpo = corpoDoResumo(job);
		assertThat(corpo).contains("""
				"numero":2,"regra_origem_id":"%s","alteracoes":[{"elemento_ref":"nucleo.orcamento","novo":600000}]}"""
			.formatted(v1));
		JsonNode periodo = JSON.readTree(corpo).path("versoes").path(2).path("alteracoes");
		assertThat(periodo.size()).isEqualTo(1);
		assertThat(periodo.path(0).path("elemento_ref").asString()).isEqualTo("nucleo.competencias");
		assertThat(periodo.path(0).path("anterior").size()).isEqualTo(5);
		assertThat(periodo.path(0).path("novo").toString()).isEqualTo("[\"2025-11\"]");
	}

	@Test
	void versaoQueNaoGravaParametrosNaoAparecePorRemoverParametros() throws Exception {
		UUID job = job(INICIO);
		UUID v1 = versaoComParametros(job, 1, "extracao", NUCLEO_V1, """
				{"orcamento":600000}""", null, INICIO);
		UUID v2 = versaoComParametros(job, 2, "sugestao_adaptacao", NUCLEO_V2, null, v1, INICIO.plusSeconds(60));
		versaoComParametros(job, 3, "correcao", NUCLEO_V2, "{}", v2, INICIO.plusSeconds(120));
		assertThat(corpoDoResumo(job)).contains("""
				"numero":2,"regra_origem_id":"%s","alteracoes":[\
				{"elemento_ref":"nucleo.percentual","anterior":0.025,"novo":0.030}]}""".formatted(v1), """
				"numero":3,"regra_origem_id":"%s","alteracoes":[]}""".formatted(v2));
	}

	@Test
	void versaoDeJobReprocessadoComparaComAOrigemDoOutroJob() throws Exception {
		UUID original = job(INICIO);
		UUID origem = versao(original, 1, "extracao", NUCLEO_V1, "[]", null, INICIO);
		UUID reprocessado = inserir("""
				INSERT INTO jobs (usuario_id, job_origem_id, status, competencias, orcamento, criado_em)
				VALUES (?, ?, 'aguardando_confirmacao_parametros', '{2026-10}', 600000, ?) RETURNING id
				""", A, original, ts(INICIO.plusSeconds(60)));
		versao(reprocessado, 1, "reprocessamento", NUCLEO_V1, "[]", origem, INICIO.plusSeconds(60));
		JsonNode versao = resumo(reprocessado).path("versoes").path(0);
		assertThat(versao.path("regra_origem_id").asString()).isEqualTo(origem.toString());
		assertThat(versao.path("alteracoes").isEmpty()).isTrue();
	}

	@Test
	void contadoresEComparacoesUsamSoSimulacoesComSucessoEValoresExatos() throws Exception {
		UUID job = job(INICIO);
		UUID v1 = versao(job, 1, "extracao", NUCLEO_V1, "[]", null, INICIO);
		UUID v2 = versao(job, 2, "correcao", NUCLEO_V2, "[]", v1, INICIO.plusSeconds(10));
		UUID r1 = simulacao(job, v1, "erro_codigo", null, null, INICIO.plusSeconds(20));
		UUID r2 = simulacao(job, v1, "sucesso", """
				{"baseline":540000,"simulado":%s,"diferenca_abs":58000.123456789,"diferenca_pct":0.1074,
				 "orcamento":600000}""".formatted(SIMULADO_ANTERIOR), new BigDecimal("28000000"),
				INICIO.plusSeconds(30));
		UUID r3 = simulacao(job, v2, "sucesso", """
				{"baseline":540000.0,"simulado":%s,"diferenca_abs":100000.987654321,"diferenca_pct":0.1852}"""
			.formatted(SIMULADO_ATUAL), new BigDecimal("28000000.50"), INICIO.plusSeconds(40));
		UUID codigoDaUltima = Objects.requireNonNull(
				dono.queryForObject("SELECT codigo_gerado_id FROM resultados_simulacao WHERE id = ?", UUID.class, r3));
		UUID candidata = resultado(job, codigoDaUltima, "sucesso", "busca_meta", """
				{"baseline":1,"simulado":2,"diferenca_abs":1,"diferenca_pct":1.0,"orcamento":600000}""",
				new BigDecimal("30000000"), INICIO.plusSeconds(50));
		String antes = snapshotNegocio();
		HttpResponse<String> resposta = chamar(ROTA.formatted(job), auditor());
		assertThat(resposta.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("ResumoDossieAuditoria", resposta.body());
		assertThat(snapshotNegocio()).isEqualTo(antes);
		assertThat(resposta.body()).doesNotContain(PROMPT_PRIVADO, RESPOSTA_PRIVADA, CODIGO_PRIVADO, "MATRIC-PRIVADA",
				candidata.toString(), r1.toString());
		JsonNode resumo = JSON.readTree(resposta.body());
		assertThat(resumo.path("simulacoes").path("registradas").asLong()).isEqualTo(3);
		assertThat(resumo.path("simulacoes").path("sucesso").asLong()).isEqualTo(2);
		assertThat(resumo.path("simulacoes").path("falha").asLong()).isEqualTo(1);
		assertThat(resumo.path("versao_vigente").asInt()).isEqualTo(2);
		assertThat(resumo.path("comparacoes").size()).isEqualTo(1);
		JsonNode comparacao = resumo.path("comparacoes").path(0);
		assertThat(comparacao.path("resultado_id").asString()).isEqualTo(r3.toString());
		assertThat(comparacao.path("resultado_anterior_id").asString()).isEqualTo(r2.toString());
		JsonNode simulado = comparacao.path("simulado");
		assertThat(simulado.path("anterior").decimalValue()).isEqualTo(new BigDecimal(SIMULADO_ANTERIOR));
		assertThat(simulado.path("atual").decimalValue()).isEqualTo(new BigDecimal(SIMULADO_ATUAL));
		assertThat(simulado.path("variacao").decimalValue())
			.isEqualTo(new BigDecimal(SIMULADO_ATUAL).subtract(new BigDecimal(SIMULADO_ANTERIOR)));
		assertThat(resposta.body()).contains("\"variacao\":42000.864197532");
		assertThat(comparacao.path("baseline").path("variacao").decimalValue()).isEqualTo(new BigDecimal("0.0"));
		assertThat(comparacao.path("diferenca_abs").path("variacao").decimalValue())
			.isEqualTo(new BigDecimal("42000.864197532"));
		assertThat(comparacao.path("diferenca_pct").path("variacao").decimalValue())
			.isEqualTo(new BigDecimal("0.0778"));
		assertThat(comparacao.path("meta_venda").path("variacao").decimalValue()).isEqualTo(new BigDecimal("0.50"));
		assertThat(comparacao.has("orcamento")).isFalse();
	}

	@Test
	void simulacaoEmCursoContaSoComoRegistradaENaoMudaAVersaoVigente() throws Exception {
		UUID job = job(INICIO);
		UUID v1 = versao(job, 1, "extracao", NUCLEO_V1, "[]", null, INICIO);
		UUID v2 = versao(job, 2, "correcao", NUCLEO_V2, "[]", v1, INICIO.plusSeconds(10));
		simulacao(job, v1, "sucesso", """
				{"baseline":1,"simulado":2,"diferenca_abs":1,"diferenca_pct":1.0}""", null, INICIO.plusSeconds(20));
		UUID codigo = codigo(job, v2, INICIO.plusSeconds(30));
		dono.update("INSERT INTO simulacoes (job_id, regra_id, codigo_gerado_id, criado_em) VALUES (?, ?, ?, ?)", job,
				v2, codigo, ts(INICIO.plusSeconds(30)));
		JsonNode resumo = resumo(job);
		assertThat(resumo.path("simulacoes").toString()).isEqualTo("{\"registradas\":2,\"sucesso\":1,\"falha\":0}");
		assertThat(resumo.path("versao_vigente").asInt()).isEqualTo(1);
		assertThat(resumo.path("comparacoes").isEmpty()).isTrue();
	}

	@Test
	void logsDaCadeiaRealTrazemJobEUsuarioSemValores() throws Exception {
		UUID job = job(INICIO);
		UUID v1 = versao(job, 1, "extracao", NUCLEO_V1, "[]", null, INICIO);
		versao(job, 2, "correcao", NUCLEO_V2, "[]", v1, INICIO.plusSeconds(10));
		simulacao(job, v1, "sucesso", """
				{"baseline":540000,"simulado":%s,"diferenca_abs":1,"diferenca_pct":0.1}""".formatted(SIMULADO_ANTERIOR),
				null, INICIO.plusSeconds(20));
		UUID inexistente = UUID.randomUUID();
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog("synapse.api.auditoria")) {
			assertThat(chamar(ROTA.formatted(job), auditor()).statusCode()).isEqualTo(200);
			assertThat(chamar(ROTA.formatted(job), rh()).statusCode()).isEqualTo(403);
			assertThat(chamar(ROTA.formatted(inexistente), auditor()).statusCode()).isEqualTo(404);
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(3);
		for (ILoggingEvent evento : eventos) {
			String serializado = CapturaDeLog.emJson(evento);
			ContratoDeEvento.validarLog(serializado);
			assertThat(serializado).doesNotContain(SIMULADO_ANTERIOR, "nucleo.percentual", "subject-auditor",
					"subject-a", "profissional-rh");
		}
		JsonNode sucesso = JSON.readTree(CapturaDeLog.emJson(eventos.get(0)));
		assertThat(sucesso.path("level").asString()).isEqualTo("INFO");
		assertThat(sucesso.path("message").asString()).isEqualTo("consulta de resumo de auditoria encerrada");
		assertThat(sucesso.path("job_id").asString()).isEqualTo(job.toString());
		assertThat(sucesso.path("user_id").asString()).isEqualTo(AUDITOR.toString());
		JsonNode recusa = JSON.readTree(CapturaDeLog.emJson(eventos.get(1)));
		assertThat(recusa.path("level").asString()).isEqualTo("WARN");
		assertThat(recusa.path("message").asString()).isEqualTo("acesso à auditoria recusado");
		assertThat(recusa.path("user_id").asString()).isEqualTo(A.toString());
		assertThat(recusa.has("job_id")).isFalse();
		JsonNode naoEncontrado = JSON.readTree(CapturaDeLog.emJson(eventos.get(2)));
		assertThat(naoEncontrado.path("level").asString()).isEqualTo("WARN");
		assertThat(naoEncontrado.path("job_id").asString()).isEqualTo(inexistente.toString());
		assertThat(naoEncontrado.path("extra").path("resultado").asString()).isEqualTo("job_nao_encontrado");
	}

	@Test
	void metricsExpoeARotaPeloTemplateComVolumeFalhasEDuracao() throws Exception {
		UUID job = job(INICIO);
		assertThat(chamar(ROTA.formatted(job), auditor()).statusCode()).isEqualTo(200);
		assertThat(chamar(ROTA.formatted(job), rh()).statusCode()).isEqualTo(403);
		assertThat(chamar(ROTA.formatted(UUID.randomUUID()), auditor()).statusCode()).isEqualTo(404);
		String metricas = chamar("/metrics", "").body();
		List<String> contagens = metricas.lines()
			.filter(linha -> linha.startsWith("http_server_requests_seconds_count{"))
			.filter(linha -> linha.contains("uri=\"/auditoria/jobs/{id}/resumo\""))
			.toList();
		for (String status : List.of("200", "403", "404")) {
			assertThat(contagens).anyMatch(linha -> linha.contains("status=\"" + status + "\"")
					&& linha.contains("method=\"GET\"") && valorMetrica(linha) >= 1);
		}
		assertThat(metricas.lines()
			.filter(linha -> linha.startsWith("http_server_requests_seconds_sum{"))
			.filter(linha -> linha.contains("uri=\"/auditoria/jobs/{id}/resumo\"")))
			.anyMatch(linha -> valorMetrica(linha) > 0);
		assertThat(metricas).doesNotContain(job.toString(), AUDITOR.toString(), "subject-auditor");
	}

	private static void assertParte(JsonNode alteracao, boolean comAnterior, boolean comNovo) {
		assertThat(alteracao.has("anterior")).as(alteracao.toString()).isEqualTo(comAnterior);
		assertThat(alteracao.has("novo")).as(alteracao.toString()).isEqualTo(comNovo);
	}

	private static JsonNode resumo(UUID job) throws Exception {
		return JSON.readTree(corpoDoResumo(job));
	}

	private static String corpoDoResumo(UUID job) throws Exception {
		HttpResponse<String> resposta = chamar(ROTA.formatted(job), auditor());
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("ResumoDossieAuditoria", resposta.body());
		return resposta.body();
	}

	private static UUID job(Instant instante) {
		UUID submissao = inserir("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em) VALUES (?, 'texto', 'Entrada', ?)
				RETURNING id
				""", A, ts(instante));
		return inserir("""
				INSERT INTO jobs (usuario_id, submissao_id, status, competencias, orcamento, criado_em)
				VALUES (?, ?, 'gerando_regra', '{2026-10}', 600000, ?) RETURNING id
				""", A, submissao, ts(instante));
	}

	private static UUID versao(UUID job, int numero, String origem, String nucleo, String especificacoes,
			@Nullable UUID anterior, Instant instante) {
		return inserir("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, regra_origem_id, criada_em)
				VALUES (?, ?, ?, ?::jsonb, ?::jsonb, ?, ?, ?) RETURNING id
				""", job, numero, origem, nucleo, especificacoes, Integer.toString(numero).repeat(64), anterior,
				ts(instante));
	}

	private static UUID versaoComParametros(UUID job, int numero, String origem, String nucleo,
			@Nullable String parametros, @Nullable UUID anterior, Instant instante) {
		return inserir("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, parametros, hash, regra_origem_id,
				    criada_em)
				VALUES (?, ?, ?, ?::jsonb, '[]'::jsonb, ?::jsonb, ?, ?, ?) RETURNING id
				""", job, numero, origem, nucleo, parametros, Integer.toString(numero).repeat(64), anterior,
				ts(instante));
	}

	private static UUID codigo(UUID job, UUID regra, Instant instante) {
		UUID prompt = inserir("""
				INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
				VALUES (?, 'geracao_codigo', ?, '{}'::jsonb, ?) RETURNING id
				""", job, PROMPT_PRIVADO, ts(instante));
		dono.update("INSERT INTO respostas_modelo (job_id, prompt_id, conteudo, criado_em) VALUES (?, ?, ?, ?)", job,
				prompt, RESPOSTA_PRIVADA, ts(instante));
		return inserir("""
				INSERT INTO codigos_gerados (job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES (?, ?, 'python', ?, ?, ?) RETURNING id
				""", job, regra, CODIGO_PRIVADO, prompt, ts(instante));
	}

	private static UUID resultado(UUID job, UUID codigo, String status, String proposito, @Nullable String totais,
			@Nullable BigDecimal metaVenda, Instant instante) {
		return inserir("""
				INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, proposito, veredito, meta_venda,
				    totais, assercoes, linhas, criado_em)
				VALUES (?, ?, ?, ?, CASE WHEN ? = 'sucesso' THEN 'viavel' ELSE NULL END, ?, ?::jsonb, '[]'::jsonb,
				    '{"2026-10":{"MATRIC-PRIVADA":{"baseline":10,"simulado":11}}}'::jsonb, ?) RETURNING id
				""", job, codigo, status, proposito, status, metaVenda, totais, ts(instante));
	}

	/** Grava o código, o resultado e a simulação que o aponta, e devolve o resultado. */
	private static UUID simulacao(UUID job, UUID regra, String status, @Nullable String totais,
			@Nullable BigDecimal metaVenda, Instant instante) {
		UUID codigo = codigo(job, regra, instante);
		UUID resultado = resultado(job, codigo, status, "simulacao", totais, metaVenda, instante);
		dono.update("""
				INSERT INTO simulacoes (job_id, regra_id, codigo_gerado_id, resultado_id, criado_em)
				VALUES (?, ?, ?, ?, ?)
				""", job, regra, codigo, resultado, ts(instante));
		return resultado;
	}

	private static double valorMetrica(String linha) {
		return Double.parseDouble(linha.substring(linha.lastIndexOf(' ') + 1));
	}

	private static UUID inserir(String sql, @Nullable Object... parametros) {
		return Objects.requireNonNull(dono.queryForObject(sql, UUID.class, parametros));
	}

	private static Timestamp ts(Instant instante) {
		return Timestamp.from(instante);
	}

	private static String snapshotNegocio() {
		return Objects.requireNonNull(dono.queryForObject("""
				SELECT jsonb_build_object(
				  'jobs', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM jobs t),
				  'submissoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM submissoes t),
				  'regras', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM regras t),
				  'resultados', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM resultados_simulacao t),
				  'codigos', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM codigos_gerados t),
				  'simulacoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM simulacoes t),
				  'outbox', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM outbox_events t)
				)::text
				""", String.class));
	}

	private static HttpResponse<String> chamar(String caminho, String token) throws Exception {
		HttpRequest.Builder pedido = HttpRequest.newBuilder(URI.create(base + caminho)).GET();
		if (!token.isEmpty()) {
			pedido.header("Authorization", "Bearer " + token);
		}
		return HTTP.send(pedido.build(), HttpResponse.BodyHandlers.ofString());
	}

	private static String auditor() throws Exception {
		return token("subject-auditor", "auditoria", "auditor");
	}

	private static String rh() throws Exception {
		return token("subject-a", "rh.a", "profissional-rh");
	}

	private static String token(String sub, String login, String papel) throws Exception {
		JWTClaimsSet claims = new JWTClaimsSet.Builder().subject(sub)
			.issuer(ISSUER)
			.issueTime(Date.from(Instant.now().minusSeconds(60)))
			.expirationTime(Date.from(Instant.now().plusSeconds(300)))
			.claim("preferred_username", login)
			.claim("realm_access", Map.of("roles", List.of(papel)))
			.build();
		SignedJWT jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID("teste-resumo").build(), claims);
		jwt.sign(new RSASSASigner(chave));
		return jwt.serialize();
	}

}
