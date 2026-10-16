package synapse.api.submissoes;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Stream;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
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
import synapse.api.job.JobsDeSubmissoes;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.awaitility.Awaitility.await;

class CorrecoesHttpTests {

	private static final UUID USUARIO = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final String ISSUER = "https://emissor-de-teste.invalid/realms/synapse";

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static PostgreSQLContainer postgres;

	private static ConfigurableApplicationContext contexto;

	private static HttpServer jwks;

	private static RSAKey chave;

	private static JdbcTemplate dono;

	private static String base;

	private static String rh;

	@BeforeAll
	static void iniciar() throws Exception {
		chave = new RSAKeyGenerator(2048).keyID("teste").generate();
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
			.run("--server.port=0", "--server.tomcat.threads.max=4", "--server.tomcat.threads.min-spare=2",
					"--logging.level.root=DEBUG", "--app.keycloak.enabled=true", "--app.keycloak.issuer-uri=" + ISSUER,
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
		rh = token("subject-a", List.of("profissional-rh"));
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
	void limpar() {

		dono.execute("TRUNCATE usuarios CASCADE");
		dono.update(
				"INSERT INTO usuarios (id, login, nome, papel, keycloak_sub, criado_em) VALUES (?, 'rh', 'RH', 'profissional_rh', 'subject-a', now())",
				USUARIO);
	}

	private static final UUID JOB = UUID.fromString("11111111-1111-4111-8111-111111111111");

	private static final UUID REGRA = UUID.fromString("22222222-2222-4222-8222-222222222222");

	private static final UUID RODADA = UUID.fromString("33333333-3333-4333-8333-333333333333");

	private static final String CORRECAO = "  Correção privada: percentual 2,5%.\nPreserve a loja.  ";

	private static final String CONFLITOS = "[{\"elementos\":[\"nucleo.percentual\"],\"motivo\":\"percentual ausente\",\"campo_futuro\":true}]";

	private static void prepararJob() {
		dono.update(
				"INSERT INTO jobs (id, usuario_id, status, competencias, criado_em) VALUES (?, ?, 'aguardando_confirmacao_parametros', ARRAY['2025-08','2025-11'], now())",
				JOB, USUARIO);
		dono.update(
				"INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em) VALUES (?, ?, 1, 'extracao', '{}', '[]', ?, now())",
				REGRA, JOB, "a".repeat(64));
		abrirRodada(RODADA, null, "2026-10-13T10:00:00Z");
	}

	private static void abrirRodada(UUID id, @org.jspecify.annotations.Nullable UUID anterior, String criada) {
		dono.update(
				"INSERT INTO rodadas_correcao (id, job_id, regra_analisada_id, conflitos, estado, rodada_anterior_id, criada_em, atualizada_em) VALUES (?, ?, ?, ?::jsonb, 'pendente', ?, ?::timestamptz, ?::timestamptz)",
				id, JOB, REGRA, CONFLITOS, anterior, criada, criada);
	}

	private static String corpo(String texto) {
		return "{\"finalidade\":\"correcao\",\"tipo\":\"texto\",\"job_id\":\"" + JOB + "\",\"texto\":"
				+ JSON.writeValueAsString(texto) + "}";
	}

	private static JsonNode aceita(String texto) throws Exception {
		var resposta = texto(corpo(texto), rh);
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(201);
		ContratoDeEvento.validarRespostaHttp("SubmissaoCriada", resposta.body());
		JsonNode json = JSON.readTree(resposta.body());
		assertThat(json.path("finalidade").asString()).isEqualTo("correcao");
		assertThat(json.path("job").path("id").asString()).isEqualTo(JOB.toString());
		assertThat(json.path("job").path("status").asString()).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(json.path("rodada").path("estado").asString()).isEqualTo("em_reextracao");
		assertThat(json.path("rodada").path("correcao").path("texto").asString()).isEqualTo(texto);
		return json;
	}

	@ParameterizedTest
	@ValueSource(strings = { "nenhum", "orcamento", "meta", "ambos" })
	void aceitaComParametrosAtuaisEPublicaSomenteReferencias(String parametros) throws Exception {
		prepararJob();
		if (parametros.equals("orcamento") || parametros.equals("ambos")) {
			dono.update("UPDATE jobs SET orcamento = 485000.1234567890123456789 WHERE id = ?", JOB);
		}
		if (parametros.equals("meta") || parametros.equals("ambos")) {
			dono.update("UPDATE jobs SET meta_venda = -123.4567890123456789 WHERE id = ?", JOB);
		}
		JsonNode criada = aceita(CORRECAO);
		UUID submissao = UUID.fromString(criada.path("id").asString());
		assertThat(dono.queryForMap("SELECT * FROM submissoes WHERE id = ?", submissao))
			.containsEntry("usuario_id", USUARIO)
			.containsEntry("tipo", "texto")
			.containsEntry("transcricao", CORRECAO)
			.containsEntry("conteudo", null)
			.containsEntry("binario", null)
			.containsEntry("formato", null)
			.containsEntry("transcrito_em", null);
		assertThat(dono.queryForMap("SELECT * FROM rodadas_correcao WHERE id = ?", RODADA))
			.containsEntry("estado", "em_reextracao")
			.containsEntry("submissao_correcao_id", submissao);
		assertThat(dono.queryForMap("SELECT * FROM jobs WHERE id = ?", JOB))
			.containsEntry("status", "aguardando_confirmacao_parametros")
			.containsEntry("submissao_id", null);
		assertThat(contar("jobs")).isEqualTo(1);
		assertThat(contar("submissoes")).isEqualTo(1);
		assertThat(contar("outbox_events")).isEqualTo(1);
		var outbox = dono.queryForMap("SELECT tipo, payload::text, publicado_em FROM outbox_events WHERE job_id = ?",
				JOB);
		assertThat(outbox).containsEntry("tipo", "correcao-submetida").containsEntry("publicado_em", null);
		String payload = Objects.requireNonNull(outbox.get("payload")).toString();
		ContratoDeEvento.validar("correcao-submetida", payload);
		JsonNode evento = JSON.readTree(payload);
		assertThat(evento.path("job_id").asString()).isEqualTo(JOB.toString());
		assertThat(evento.path("regra_origem_id").asString()).isEqualTo(REGRA.toString());
		assertThat(evento.path("submissao_id").asString()).isEqualTo(submissao.toString());
		assertThat(evento.path("competencias").toString()).isEqualTo("[\"2025-08\",\"2025-11\"]");
		assertThat(evento.has("orcamento")).isEqualTo(parametros.equals("orcamento") || parametros.equals("ambos"));
		assertThat(evento.has("meta_venda")).isEqualTo(parametros.equals("meta") || parametros.equals("ambos"));
		if (evento.has("orcamento")) {
			assertThat(evento.path("orcamento").decimalValue()).isEqualByComparingTo("485000.1234567890123456789");
		}
		if (evento.has("meta_venda")) {
			assertThat(evento.path("meta_venda").decimalValue()).isEqualByComparingTo("-123.4567890123456789");
		}
		assertThat(payload).doesNotContain("texto", "transcricao", "Correção privada");
		JsonNode rodada = criada.path("rodada");
		assertThat(rodada.path("conflitos").path(0).path("campo_futuro").asBoolean()).isTrue();
	}

	@ParameterizedTest
	@MethodSource("entradasInvalidas")
	void recusaValidacaoSemEfeitos(String corpo) throws Exception {
		prepararJob();
		recusa(texto(corpo, rh), 400, "requisicao_invalida");
		semCorrecao();
	}

	static Stream<String> entradasInvalidas() {
		return EntradaCorrecaoTests.invalidos();
	}

	@ParameterizedTest
	@ValueSource(strings = { "gerando_regra", "aguardando_transcricao", "simulando", "aguardando_decisao_usuario",
			"simulacao_inviavel", "liberado", "cancelado", "arquivado", "erro" })
	void recusaOutrosEstadosDoJob(String estado) throws Exception {
		prepararJob();
		dono.update("UPDATE jobs SET status = ? WHERE id = ?", estado, JOB);
		recusa(texto(corpo(CORRECAO), rh), 409, "estado_invalido");
		semCorrecao();
	}

	@ParameterizedTest
	@ValueSource(strings = { "ausente", "em_reextracao", "corrigida", "abandonada", "reextracao_falhou" })
	void recusaSemRodadaPendente(String estado) throws Exception {
		prepararJob();
		if (estado.equals("ausente")) {
			dono.update("DELETE FROM rodadas_correcao WHERE id = ?", RODADA);
		}
		else {
			dono.update("UPDATE rodadas_correcao SET estado = ? WHERE id = ?", estado, RODADA);
		}
		recusa(texto(corpo(CORRECAO), rh), 409, "estado_invalido");
		assertThat(contar("submissoes")).isZero();
		assertThat(contar("outbox_events")).isZero();
	}

	@Test
	void conferePapelPosseAutenticacaoEJobInexistenteNosDoisEndpoints() throws Exception {
		prepararJob();
		String outro = token("subject-b", List.of("profissional-rh"));
		String auditor = token("subject-a", List.of("auditor"));
		for (String credencial : List.of(outro, auditor)) {
			recusa(texto(corpo(CORRECAO), credencial), 403, "sem_permissao");
			recusa(get("/jobs/" + JOB + "/rodadas", credencial), 403, "sem_permissao");
			semCorrecao();
		}
		assertThat(texto(corpo(CORRECAO), "").statusCode()).isEqualTo(401);
		assertThat(get("/jobs/" + JOB + "/rodadas", "").statusCode()).isEqualTo(401);
		UUID inexistente = UUID.randomUUID();
		recusa(texto(corpo(CORRECAO).replace(JOB.toString(), inexistente.toString()), rh), 404, "job_nao_encontrado");
		recusa(get("/jobs/" + inexistente + "/rodadas", rh), 404, "job_nao_encontrado");
		semCorrecao();
	}

	@Test
	void historicoPersistidoOrdenadoComTodasAsFormasEDuasSubmissoesImutaveis() throws Exception {
		prepararJob();
		JsonNode primeira = aceita(CORRECAO);
		recusa(texto(corpo("segunda prematura"), rh), 409, "estado_invalido");
		assertThat(contar("submissoes")).isEqualTo(1);
		dono.update("UPDATE rodadas_correcao SET estado = 'corrigida', regra_resultante_id = ? WHERE id = ?", REGRA,
				RODADA);
		UUID segundaRodada = UUID.randomUUID();
		abrirRodada(segundaRodada, RODADA, "2026-10-13T10:01:00Z");
		JsonNode segunda = aceita("Correção seguinte independente.");
		assertThat(segunda.path("id").asString()).isNotEqualTo(primeira.path("id").asString());
		dono.update("UPDATE rodadas_correcao SET estado = 'reextracao_falhou' WHERE id = ?", segundaRodada);
		UUID terceira = UUID.randomUUID();
		abrirRodada(terceira, segundaRodada, "2026-10-13T10:02:00Z");
		var consulta = get("/jobs/" + JOB + "/rodadas", rh);
		assertThat(consulta.statusCode()).isEqualTo(200);
		JsonNode lista = JSON.readTree(consulta.body());
		assertThat(lista.isArray()).isTrue();
		assertThat(lista.size()).isEqualTo(3);
		for (JsonNode rodada : lista) {
			ContratoDeEvento.validarRespostaHttp("Rodada", rodada.toString());
		}
		assertThat(lista.path(0).path("id").asString()).isEqualTo(RODADA.toString());
		assertThat(lista.path(0).path("correcao").path("texto").asString()).isEqualTo(CORRECAO);
		assertThat(lista.path(0).path("regra_resultante_id").asString()).isEqualTo(REGRA.toString());
		assertThat(lista.path(1).path("id").asString()).isEqualTo(segundaRodada.toString());
		assertThat(lista.path(1).path("estado").asString()).isEqualTo("reextracao_falhou");
		assertThat(lista.path(2).path("rodada_anterior_id").asString()).isEqualTo(segundaRodada.toString());
		assertThat(lista.path(2).path("correcao").isNull()).isTrue();
		assertThat(lista.path(2).path("regra_resultante_id").isNull()).isTrue();
		assertThat(get("/jobs/" + JOB + "/rodadas", token("subject-a", List.of("profissional-rh"))).body())
			.isEqualTo(consulta.body());
		assertThat(contar("submissoes")).isEqualTo(2);
		assertThat(contar("outbox_events")).isEqualTo(2);
		dono.update("UPDATE rodadas_correcao SET estado = 'abandonada' WHERE id = ?", terceira);
		assertThat(JSON.readTree(get("/jobs/" + JOB + "/rodadas", rh).body()).path(2).path("estado").asString())
			.isEqualTo("abandonada");
	}

	@Test
	void jobSemRodadasRetornaListaVazia() throws Exception {
		prepararJob();
		dono.update("DELETE FROM rodadas_correcao WHERE job_id = ?", JOB);
		var resposta = get("/jobs/" + JOB + "/rodadas", rh);
		assertThat(resposta.statusCode()).isEqualTo(200);
		assertThat(resposta.body()).isEqualTo("[]");
	}

	@ParameterizedTest
	@ValueSource(strings = { "submissoes", "rodadas_correcao", "outbox_events" })
	void falhaDePersistenciaDesfazTodaATransacaoENaoContaAceitacao(String tabela) throws Exception {
		prepararJob();
		double antes = contador("aceita");
		dono.execute(
				"CREATE FUNCTION falhar_t216() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'falha induzida confidencial'; END $$");
		dono.execute("CREATE TRIGGER falhar_t216 BEFORE " + (tabela.equals("rodadas_correcao") ? "UPDATE" : "INSERT")
				+ " ON " + tabela + " FOR EACH ROW EXECUTE FUNCTION falhar_t216()");
		try (var logs = new CapturaDeLog(ObservabilidadeSubmissoes.class)) {
			assertThat(texto(corpo(CORRECAO), rh).statusCode()).isEqualTo(500);
			semCorrecao();
			await().untilAsserted(() -> assertThat(logs.eventos()).hasSize(1));
			String log = CapturaDeLog.emJson(logs.eventos().getFirst());
			ContratoDeEvento.validarLog(log);
			assertThat(log).contains("falha_interna", RODADA.toString())
				.doesNotContain("correção aceita", "Correção privada", "falha induzida");
			assertThat(contador("aceita")).isEqualTo(antes);
		}
		finally {
			dono.execute("DROP TRIGGER falhar_t216 ON " + tabela);
			dono.execute("DROP FUNCTION falhar_t216()");
		}
	}

	@Test
	void duasCorrecoesConcorrentesSoAceitamUma() throws Exception {
		prepararJob();
		try (var executor = java.util.concurrent.Executors.newFixedThreadPool(2)) {
			var inicio = new java.util.concurrent.CountDownLatch(1);
			var a = executor.submit(() -> {
				inicio.await();
				return texto(corpo("primeira"), rh);
			});
			var b = executor.submit(() -> {
				inicio.await();
				return texto(corpo("segunda"), rh);
			});
			inicio.countDown();
			var resultados = List.of(a.get(20, java.util.concurrent.TimeUnit.SECONDS),
					b.get(20, java.util.concurrent.TimeUnit.SECONDS));
			assertThat(resultados).extracting(HttpResponse::statusCode).containsExactlyInAnyOrder(201, 409);
		}
		assertThat(contar("submissoes")).isEqualTo(1);
		assertThat(contar("outbox_events")).isEqualTo(1);
	}

	@Test
	void portaNaoPodeSerChamadaSemTransacao() {
		var porta = contexto.getBean(JobsDeSubmissoes.class);
		assertThatThrownBy(() -> porta.corrigir(JOB,
				new synapse.api.core.security.AcessoDoUsuario(USUARIO,
						synapse.api.core.security.PapelDoUsuario.PROFISSIONAL_RH),
				rodada -> UUID.randomUUID(), Instant.now()))
			.isInstanceOf(org.springframework.transaction.IllegalTransactionStateException.class);
	}

	@Test
	void observaAceitacaoRecusasEMetricasNoHttpRealSemConteudo() throws Exception {
		prepararJob();
		List<String> resultados = List.of("aceita", "estado_invalido", "requisicao_invalida", "sem_permissao",
				"job_nao_encontrado");
		List<Double> antes = resultados.stream().map(CorrecoesHttpTests::contador).toList();
		try (var logs = new CapturaDeLog(ObservabilidadeSubmissoes.class);
				var todos = new CapturaDeLog(org.slf4j.Logger.ROOT_LOGGER_NAME)) {
			aceita(CORRECAO);
			recusa(texto(corpo(CORRECAO), rh), 409, "estado_invalido");
			recusa(texto(corpo("  "), rh), 400, "requisicao_invalida");
			recusa(texto(corpo(CORRECAO), token("subject-a", List.of("auditor"))), 403, "sem_permissao");
			recusa(texto(corpo(CORRECAO).replace(JOB.toString(), UUID.randomUUID().toString()), rh), 404,
					"job_nao_encontrado");
			await().untilAsserted(() -> assertThat(logs.eventos()).hasSize(5));
			for (var evento : logs.eventos()) {
				String serializado = CapturaDeLog.emJson(evento);
				ContratoDeEvento.validarLog(serializado);
				assertThat(evento.getMDCPropertyMap()).containsKey("job_id");
				assertThat(serializado).contains("resultado", "motivo");
			}
			assertThat(CapturaDeLog.emJson(logs.eventos().getFirst())).contains(RODADA.toString(), "correção aceita");
			assertThat(CapturaDeLog.emJson(logs.eventos().get(1))).contains(RODADA.toString(), "estado_invalido");
			for (var evento : todos.eventos()) {
				assertThat(CapturaDeLog.emJson(evento)).doesNotContain("Correção privada", "Preserve a loja", rh);
			}
			for (int i = 0; i < resultados.size(); i++) {
				assertThat(contador(resultados.get(i))).isEqualTo(antes.get(i) + 1);
			}
			var scrape = get("/metrics", "");
			assertThat(scrape.statusCode()).isEqualTo(200);
			for (String resultado : resultados) {
				assertThat(scrape.body())
					.contains("submissoes_correcoes_total{resultado=\"" + resultado + "\"} " + contador(resultado));
			}
			assertThat(scrape.body()).doesNotContain("Correção privada", JOB.toString(), RODADA.toString());
			for (var meter : contexto.getBean(MeterRegistry.class).find("submissoes.correcoes").meters()) {
				assertThat(meter.getId().getTags()).extracting(io.micrometer.core.instrument.Tag::getKey)
					.containsExactly("resultado");
			}
			assertThat(get("/actuator/prometheus", rh).statusCode()).isEqualTo(404);
		}
	}

	private static void recusa(HttpResponse<String> resposta, int status, String codigo) throws Exception {
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(status);
		ContratoDeEvento.validarRespostaHttp("Erro", resposta.body());
		assertThat(JSON.readTree(resposta.body()).path("codigo").asString()).isEqualTo(codigo);
		assertThat(resposta.body()).doesNotContain("Correção privada", "SQLException", "stackTrace");
	}

	private static void semCorrecao() {
		assertThat(contar("submissoes")).isZero();
		assertThat(contar("outbox_events")).isZero();
		assertThat(dono.queryForMap("SELECT estado, submissao_correcao_id FROM rodadas_correcao WHERE id = ?", RODADA))
			.containsEntry("estado", "pendente")
			.containsEntry("submissao_correcao_id", null);
	}

	private static long contar(String tabela) {
		return Objects.requireNonNull(dono.queryForObject("SELECT count(*) FROM " + tabela, Long.class));
	}

	private static double contador(String resultado) {
		var counter = contexto.getBean(MeterRegistry.class)
			.find("submissoes.correcoes")
			.tag("resultado", resultado)
			.counter();
		return counter == null ? 0 : counter.count();
	}

	private static HttpResponse<String> texto(String corpo, String token) throws Exception {
		return HTTP.send(requisicao("/submissoes", token).header("Content-Type", "application/json")
			.POST(HttpRequest.BodyPublishers.ofString(corpo))
			.build(), HttpResponse.BodyHandlers.ofString());
	}

	private static HttpResponse<String> get(String path, String token) throws Exception {
		return HTTP.send(requisicao(path, token).GET().build(), HttpResponse.BodyHandlers.ofString());
	}

	private static HttpRequest.Builder requisicao(String path, String token) {
		var builder = HttpRequest.newBuilder(URI.create(base + path));
		if (!token.isEmpty()) {
			builder.header("Authorization", "Bearer " + token);
		}
		return builder;
	}

	private static String token(String subject, List<String> papeis) throws Exception {
		Instant agora = Instant.now();
		var claims = new JWTClaimsSet.Builder().issuer(ISSUER)
			.subject(subject)
			.issueTime(Date.from(agora))
			.expirationTime(Date.from(agora.plusSeconds(3600)))
			.claim("realm_access", Map.of("roles", papeis))
			.build();
		var jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID(chave.getKeyID()).build(), claims);
		jwt.sign(new RSASSASigner(chave));
		return jwt.serialize();
	}

}
