package synapse.api.submissoes;

import java.io.ByteArrayOutputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Arrays;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
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
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import synapse.api.ApiApplication;
import synapse.api.job.CapturaDeLog;
import synapse.api.job.ContratoDeEvento;
import synapse.api.job.JobsDeSubmissoes;
import synapse.api.job.JobStatus;
import synapse.api.job.MaquinaDeEstadosDoJob;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.awaitility.Awaitility.await;

class SubmissoesHttpTests {

	private static final UUID USUARIO = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final String TEXTO = "  Descrição privada da regra\ncom acentuação e comissão.  ";

	private static final String PARAMETROS = "{\"finalidade\":\"entrada_inicial\",\"tipo\":\"voz\",\"orcamento\":485000.1234567890123456789}";

	private static final String ISSUER = "https://emissor-de-teste.invalid/realms/synapse";

	private static final String FILENAME = "segredo-nao-logar.exe";

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final AtomicBoolean VOZ = new AtomicBoolean(true);

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
		contexto = new SpringApplicationBuilder(ApiApplication.class, CapacidadeDeTeste.class)
			.web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--server.tomcat.threads.max=1", "--server.tomcat.threads.min-spare=1",
					"--logging.level.root=DEBUG", "--app.keycloak.enabled=true", "--app.keycloak.issuer-uri=" + ISSUER,
					"--app.keycloak.jwk-set-uri=http://127.0.0.1:" + jwks.getAddress().getPort() + "/jwks",
					"--app.postgres.host=" + postgres.getHost(), "--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
					"--app.postgres.password=senha-de-teste", "--spring.rabbitmq.dynamic=false",
					"--spring.rabbitmq.listener.simple.auto-startup=false", "--management.health.rabbit.enabled=false",
					"--management.health.db.enabled=false", "--app.outbox.enabled=false");
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE synapse_api WITH PASSWORD 'senha-de-teste'");
		base = "http://localhost:" + contexto.getEnvironment().getProperty("local.server.port");
		rh = token("subject-a", List.of("profissional-rh"));
	}

	@TestConfiguration(proxyBeanMethods = false)
	static class CapacidadeDeTeste {

		@Bean
		@Primary
		DisponibilidadeTranscricao capacidade() {
			return new DisponibilidadeTranscricao() {
				@Override
				boolean disponivel() {
					return VOZ.get();
				}
			};
		}

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
		VOZ.set(true);
		dono.execute("TRUNCATE usuarios CASCADE");
		dono.update(
				"INSERT INTO usuarios (id, login, nome, papel, keycloak_sub, criado_em) VALUES (?, 'rh', 'RH', 'profissional_rh', 'subject-a', now())",
				USUARIO);
	}

	@Test
	void textoCriaJobSemRegraEEventoValidoComPrecisaoEIdentidade() throws Exception {
		dono.update(
				"INSERT INTO usuarios (id, login, nome, papel, keycloak_sub, criado_em) VALUES (?, 'outro', 'Outro', 'profissional_rh', 'subject-outro', now())",
				UUID.fromString("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"));
		var resposta = texto(corpoTexto(TEXTO).replace("\"tipo\"",
				"\"usuario_id\":\"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb\",\"tipo\""), rh);
		var criada = criada(resposta, "texto", "gerando_regra");
		UUID id = UUID.fromString(criada.path("id").asString());
		UUID job = UUID.fromString(criada.path("job").path("id").asString());
		assertThat(dono.queryForMap("SELECT * FROM submissoes WHERE id = ?", id)).containsEntry("usuario_id", USUARIO)
			.containsEntry("tipo", "texto")
			.containsEntry("transcricao", TEXTO)
			.containsEntry("conteudo", null)
			.containsEntry("binario", null)
			.containsEntry("formato", null)
			.containsEntry("transcrito_em", null);
		assertThat(dono.queryForMap("SELECT * FROM jobs WHERE id = ?", job)).containsEntry("usuario_id", USUARIO)
			.containsEntry("submissao_id", id)
			.containsEntry("status", "gerando_regra");
		transicaoInicial(job, "gerando_regra");
		String payload = Objects.requireNonNull(dono.queryForObject(
				"SELECT payload::text FROM outbox_events WHERE job_id = ? AND tipo = 'regra-submetida'", String.class,
				job));
		ContratoDeEvento.validar("regra-submetida", payload);
		var evento = JSON.readTree(payload);
		assertThat(evento.has("regra_id")).as("a publicação inicial precede a extração").isFalse();
		assertThat(evento.path("submissao_id").asString()).isEqualTo(id.toString());
		assertThat(evento.path("origem").asString()).isEqualTo("texto");
		assertThat(evento.path("competencias").toString()).isEqualTo("[\"2025-08\",\"2025-11\"]");
		assertThat(evento.path("orcamento").decimalValue()).isEqualByComparingTo("485000.1234567890123456789");
		assertThat(dono.queryForObject("SELECT orcamento FROM jobs WHERE id = ?", java.math.BigDecimal.class, job))
			.isEqualByComparingTo("485000.1234567890123456789");
		assertThat(contar("regras")).isZero();
		assertThat(contar("trabalhos_transcricao")).isZero();
		consultarSemRegra(job, "gerando_regra");
	}

	static Stream<Arguments> formatos() {
		return Stream.of(
				Arguments.of("webm", "audio/webm;codecs=opus", new byte[] { 0x1a, 0x45, (byte) 0xdf, (byte) 0xa3 }),
				Arguments.of("ogg", "audio/ogg", "OggS".getBytes(StandardCharsets.US_ASCII)),
				Arguments.of("wav", "audio/wav", "RIFF1234WAVE".getBytes(StandardCharsets.US_ASCII)),
				Arguments.of("mp4", "audio/mp4",
						new byte[] { 0, 0, 0, 16, 'f', 't', 'y', 'p', 'M', '4', 'A', ' ', 0, 0, 0, 0 }));
	}

	@ParameterizedTest
	@MethodSource("formatos")
	void vozCriaTrabalhoSemEventoPreservandoBytes(String formato, String media, byte[] bytes) throws Exception {
		var resposta = voz(media, bytes, PARAMETROS, rh);
		var criada = criada(resposta, "voz", "aguardando_transcricao");
		UUID id = UUID.fromString(criada.path("id").asString());
		UUID job = UUID.fromString(criada.path("job").path("id").asString());
		assertThat(dono.queryForMap("SELECT * FROM submissoes WHERE id = ?", id)).containsEntry("usuario_id", USUARIO)
			.containsEntry("tipo", "voz")
			.containsEntry("formato", formato)
			.containsEntry("transcricao", null)
			.containsEntry("transcrito_em", null)
			.containsEntry("conteudo", null);
		assertThat(dono.queryForObject("SELECT binario FROM submissoes WHERE id = ?", byte[].class, id))
			.containsExactly(bytes);
		assertThat(dono.queryForMap("SELECT * FROM jobs WHERE id = ?", job)).containsEntry("usuario_id", USUARIO)
			.containsEntry("submissao_id", id)
			.containsEntry("iniciado_em", null)
			.containsEntry("finalizado_em", null);
		assertThat(dono.queryForObject("SELECT competencias::text FROM jobs WHERE id = ?", String.class, job))
			.isEqualTo("{2025-08,2025-09,2025-10,2025-11,2025-12}");
		assertThat(contar("trabalhos_transcricao")).isEqualTo(1);
		var trabalho = dono.queryForMap("SELECT * FROM trabalhos_transcricao WHERE job_id = ?", job);
		assertThat(trabalho).containsEntry("submissao_id", id)
			.containsEntry("estado", "pendente")
			.containsEntry("finalidade", "entrada_inicial")
			.containsEntry("tentativas", 0)
			.containsEntry("reservado_ate", null)
			.containsEntry("proxima_tentativa_em", null);
		assertThat(trabalho.get("criado_em")).isEqualTo(trabalho.get("atualizado_em"));
		transicaoInicial(job, "aguardando_transcricao");
		assertThat(contar("outbox_events")).isZero();
		assertThat(contar("regras")).isZero();
		consultarSemRegra(job, "aguardando_transcricao");
	}

	static Stream<String> textosInvalidos() {
		String valido = corpoTexto("regra");
		return Stream.of("{", "[]", valido + " {}", valido.replace("entrada_inicial", "correcao"),
				valido.replace("\"tipo\":\"texto\"", "\"tipo\":\"voz\""), valido.replace("\"texto\":\"regra\",", ""),
				valido.replace("\"texto\":\"regra\"", "\"texto\":123"), corpoTexto(""), corpoTexto(" \t\n"),
				corpoTexto("\u00a0"), corpoTexto("x".repeat(8001)),
				valido.replace("485000.1234567890123456789", "null"),
				valido.replace("485000.1234567890123456789", "\"20\""),
				valido.replace("485000.1234567890123456789", "-1"),
				valido.replace("\"orcamento\":485000.1234567890123456789,", ""),
				valido.replace("[\"2025-11\",\"2025-08\"]", "[]"), valido.replace("2025-08", "2025-07"),
				valido.replace("2025-08", "2025-11"), valido.replace("[\"2025-11\",\"2025-08\"]", "null"),
				valido.replace("[\"2025-11\",\"2025-08\"]", "[1]"));
	}

	@ParameterizedTest
	@MethodSource("textosInvalidos")
	void recusaTextoInvalidoSemEfeitos(String corpo) throws Exception {
		recusa(texto(corpo, rh), 400, "requisicao_invalida");
	}

	@Test
	void aceitaLimiteDeTextoEmPontosUnicodeEOrcamentoZero() throws Exception {
		criada(texto(corpoTexto("😀".repeat(8000)).replace("485000.1234567890123456789", "0"), rh), "texto",
				"gerando_regra");
	}

	@ParameterizedTest
	@ValueSource(strings = { "{}", "{", "[]", "{\"finalidade\":\"entrada_inicial\",\"tipo\":\"texto\"}",
			"{\"finalidade\":\"entrada_inicial\",\"tipo\":\"voz\"}",
			"{\"finalidade\":\"entrada_inicial\",\"tipo\":\"voz\",\"orcamento\":-1}" })
	void recusaParametrosDaVoz(String parametros) throws Exception {
		recusa(voz("audio/ogg", ogg(4), parametros, rh), 400, "requisicao_invalida");
	}

	@ParameterizedTest
	@ValueSource(strings = { "audio", "parametros" })
	void exigeAsDuasPartes(String ausente) throws Exception {
		recusa(multipart("audio/ogg", ogg(4), PARAMETROS, rh, ausente), 400, "requisicao_invalida");
	}

	static Stream<Arguments> audiosInvalidos() {
		return Stream.of(Arguments.of("audio/ogg", new byte[0]),
				Arguments.of("audio/ogg", new byte[] { 0x1a, 0x45, (byte) 0xdf, (byte) 0xa3 }),
				Arguments.of("audio/ogg", new byte[] { 1, 2, 3, 4 }), Arguments.of("audio/mpeg", ogg(4)),
				Arguments.of("application/ogg", ogg(4)),
				Arguments.of("audio/wav", "RIFF1234FAIL".getBytes(StandardCharsets.US_ASCII)),
				Arguments.of("audio/mp4", "xxxxxxxxftypxxxx".getBytes(StandardCharsets.US_ASCII)));
	}

	@ParameterizedTest
	@MethodSource("audiosInvalidos")
	void recusaAudioInvalido(String media, byte[] bytes) throws Exception {
		recusa(voz(media, bytes, PARAMETROS, rh), 422, "audio_invalido");
	}

	@Test
	void limiteRealDoServidorRecusaArquivoMaiorQueCincoMb() throws Exception {
		recusa(voz("audio/ogg", ogg(5 * 1024 * 1024 + 1), PARAMETROS, rh), 413, "audio_muito_grande");
	}

	@Test
	void limiteRealDaRequisicaoTambemRetornaErroDoContrato() throws Exception {
		recusa(voz("audio/ogg", ogg(7 * 1024 * 1024), PARAMETROS, rh), 413, "audio_muito_grande");
	}

	@Test
	void aceitaCincoMbComMargemParaJsonEOverhead() throws Exception {
		criada(voz("audio/ogg", ogg(5 * 1024 * 1024), PARAMETROS, rh), "voz", "aguardando_transcricao");
	}

	@Test
	void vozDesabilitadaNaoPersiste() throws Exception {
		assertThat(new DisponibilidadeTranscricao().disponivel()).isFalse();
		VOZ.set(false);
		recusa(voz("audio/ogg", ogg(4), PARAMETROS, rh), 409, "estado_invalido");
	}

	@Test
	void mediaTypeMultipartNaoDependeDeMaiusculasNaMetrica() throws Exception {
		double antes = contador("voz", "aceita");
		criada(multipart("audio/ogg", ogg(4), PARAMETROS, rh, "", "MULTIPART/FORM-DATA"), "voz",
				"aguardando_transcricao");
		await().untilAsserted(() -> assertThat(contador("voz", "aceita")).isEqualTo(antes + 1));
	}

	@ParameterizedTest
	@ValueSource(strings = { "auditor", "nenhum", "ambos" })
	void segurancaRealRecusaPapeisSemEfeitos(String perfil) throws Exception {
		List<String> papeis = switch (perfil) {
			case "auditor" -> List.of("auditor");
			case "ambos" -> List.of("profissional-rh", "auditor");
			default -> List.of("offline_access");
		};
		String token = token("subject-a", papeis);
		recusa(texto(corpoTexto(TEXTO), token), 403, "sem_permissao");
		recusa(voz("audio/ogg", ogg(4), PARAMETROS, token), 403, "sem_permissao");
	}

	@Test
	void semAutenticacaoRecebe401() throws Exception {
		recusa(texto(corpoTexto(TEXTO), ""), 401, "nao_autenticado");
	}

	@Test
	void tokenInvalidoRecebe401() throws Exception {
		recusa(texto(corpoTexto(TEXTO), "invalido"), 401, "nao_autenticado");
	}

	@ParameterizedTest
	@ValueSource(strings = { "texto", "voz" })
	void falhaPosteriorDesfazTudoENaoContaAceita(String tipo) throws Exception {
		double antes = contador(tipo, "aceita");
		String tabela = tipo.equals("texto") ? "outbox_events" : "trabalhos_transcricao";
		dono.execute(
				"CREATE FUNCTION falhar_t231() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''falha induzida''; END'");
		dono.execute("CREATE TRIGGER falhar_t231 BEFORE INSERT ON " + tabela
				+ " FOR EACH ROW EXECUTE FUNCTION falhar_t231()");
		try (var logs = new CapturaDeLog(ObservabilidadeSubmissoes.class);
				var todosOsLogs = new CapturaDeLog(org.slf4j.Logger.ROOT_LOGGER_NAME)) {
			var resposta = tipo.equals("texto") ? texto(corpoTexto(TEXTO), rh)
					: voz("audio/ogg", ogg(4), PARAMETROS, rh);
			assertThat(resposta.statusCode()).isEqualTo(500);
			semEfeitos();
			assertThat(resposta.body()).doesNotContain("SQLException", "submissoes", "falha induzida", TEXTO);
			assertThat(contador(tipo, "aceita")).isEqualTo(antes);
			await().untilAsserted(() -> assertThat(logs.eventos()).hasSize(1));
			String serializado = CapturaDeLog.emJson(logs.eventos().getFirst());
			ContratoDeEvento.validarLog(serializado);
			assertThat(serializado).contains("falha_interna").doesNotContain("submissão e job criados");
			for (var evento : todosOsLogs.eventos()) {
				assertThat(CapturaDeLog.emJson(evento)).doesNotContain("privada", FILENAME, "OggS", rh,
						"485000.1234567890123456789", "falha induzida");
			}
		}
		finally {
			dono.execute("DROP TRIGGER falhar_t231 ON " + tabela);
			dono.execute("DROP FUNCTION falhar_t231()");
		}
	}

	@Test
	void logsEMetricasPeloHttpRealSemConteudoNemVazamentoEntreRequisicoes() throws Exception {
		try (var logs = new CapturaDeLog(ObservabilidadeSubmissoes.class);
				var todosOsLogs = new CapturaDeLog(org.slf4j.Logger.ROOT_LOGGER_NAME)) {
			var medidas = List.of(List.of("texto", "aceita"), List.of("voz", "aceita"),
					List.of("voz", "estado_invalido"), List.of("texto", "requisicao_invalida"),
					List.of("voz", "audio_invalido"), List.of("voz", "audio_muito_grande"),
					List.of("texto", "sem_permissao"), List.of("texto", "nao_autenticado"));
			var valores = medidas.stream().map(m -> contador(m.get(0), m.get(1))).toList();
			double antes = contador("texto", "aceita");
			var criada = criada(texto(corpoTexto(TEXTO), rh), "texto", "gerando_regra");
			await().untilAsserted(() -> assertThat(contador("texto", "aceita")).isEqualTo(antes + 1));
			criada(voz("audio/ogg", ogg(4), PARAMETROS, rh), "voz", "aguardando_transcricao");
			VOZ.set(false);
			assertThat(voz("audio/ogg", ogg(4), PARAMETROS, rh).statusCode()).isEqualTo(409);
			assertThat(texto(corpoTexto(" "), rh).statusCode()).isEqualTo(400);
			assertThat(voz("audio/ogg", new byte[] { 1, 2, 3 }, PARAMETROS, rh).statusCode()).isEqualTo(422);
			assertThat(voz("audio/ogg", ogg(5 * 1024 * 1024 + 1), PARAMETROS, rh).statusCode()).isEqualTo(413);
			assertThat(texto(corpoTexto(TEXTO), token("subject-b", List.of("auditor"))).statusCode()).isEqualTo(403);
			assertThat(texto(corpoTexto(TEXTO), "").statusCode()).isEqualTo(401);
			await().untilAsserted(() -> assertThat(logs.eventos()).hasSize(8));
			for (var evento : todosOsLogs.eventos()) {
				assertThat(CapturaDeLog.emJson(evento)).doesNotContain("privada", FILENAME, "OggS", rh,
						"485000.1234567890123456789");
			}
			for (int i = 0; i < medidas.size(); i++) {
				assertThat(contador(medidas.get(i).get(0), medidas.get(i).get(1))).isEqualTo(valores.get(i) + 1);
			}
			for (var evento : logs.eventos()) {
				String serializado = CapturaDeLog.emJson(evento);
				ContratoDeEvento.validarLog(serializado);
				assertThat(serializado).doesNotContain("Descrição privada", FILENAME, "OggS", "orcamento", "parametros",
						rh);
				assertThat(JSON.readTree(serializado).path("service.name").asString()).isEqualTo("synapse-api");
			}
			assertThat(logs.eventos().getFirst().getMDCPropertyMap()).containsEntry("user_id", USUARIO.toString())
				.containsEntry("job_id", criada.path("job").path("id").asString());
			assertThat(logs.eventos().get(2).getMDCPropertyMap()).containsEntry("user_id", USUARIO.toString())
				.doesNotContainKey("job_id");
			assertThat(logs.eventos().getLast().getMDCPropertyMap()).doesNotContainKeys("job_id", "user_id");
			String scrape = get("/metrics", "").body();
			for (String resultado : List.of("aceita", "estado_invalido", "requisicao_invalida", "audio_invalido",
					"audio_muito_grande", "sem_permissao")) {
				assertThat(scrape).contains("resultado=\"" + resultado + "\"");
			}
			assertThat(scrape).contains("submissoes_criacao_total")
				.doesNotContain(FILENAME, "Descrição privada", "subject-a", USUARIO.toString());
			for (var meter : contexto.getBean(MeterRegistry.class).find("submissoes.criacao").meters()) {
				assertThat(meter.getId().getTags()).extracting(io.micrometer.core.instrument.Tag::getKey)
					.containsExactlyInAnyOrder("tipo", "resultado");
				assertThat(meter.getId().getTag("tipo")).isIn("texto", "voz");
				assertThat(meter.getId().getTag("resultado")).isIn("aceita", "estado_invalido", "requisicao_invalida",
						"audio_invalido", "audio_muito_grande", "sem_permissao", "nao_autenticado", "falha_interna");
			}
		}
	}

	@Test
	void portaExigeTransacaoEConclusaoIdempotente() throws Exception {
		var porta = contexto.getBean(JobsDeSubmissoes.class);
		assertThatThrownBy(() -> porta.concluirTranscricao(UUID.randomUUID(), UUID.randomUUID()))
			.isInstanceOf(org.springframework.transaction.IllegalTransactionStateException.class);
		var criada = criada(voz("audio/ogg", ogg(4), PARAMETROS, rh), "voz", "aguardando_transcricao");
		UUID job = UUID.fromString(criada.path("job").path("id").asString());
		UUID id = UUID.fromString(criada.path("id").asString());
		var tx = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
		var metrics = contexto.getBean(synapse.api.core.metrics.AppMetrics.class);
		var aplicadas = metrics.transcricaoTransicao("concluir", "aplicada");
		var descartadas = metrics.transcricaoTransicao("concluir", "descartada");
		long aplicadasAntes = aplicadas.count();
		long descartadasAntes = descartadas.count();
		assertThat(tx.<Boolean>execute(s -> porta.concluirTranscricao(job, UUID.randomUUID()))).isFalse();
		dono.update("UPDATE submissoes SET transcricao = 'transcrição concluída', transcrito_em = now() WHERE id = ?",
				id);
		assertThat(tx.<Boolean>execute(s -> {
			boolean aplicada = porta.concluirTranscricao(job, id);
			assertThat(aplicadas.count()).isEqualTo(aplicadasAntes);
			return aplicada;
		})).isTrue();
		assertThat(tx.<Boolean>execute(s -> porta.concluirTranscricao(job, id))).isFalse();
		assertThat(aplicadas.count()).isEqualTo(aplicadasAntes + 1);
		assertThat(descartadas.count()).isEqualTo(descartadasAntes + 2);
		String payload = Objects.requireNonNull(
				dono.queryForObject("SELECT payload::text FROM outbox_events WHERE job_id = ?", String.class, job));
		ContratoDeEvento.validar("regra-submetida", payload);
		assertThat(JSON.readTree(payload).path("origem").asString()).isEqualTo("voz");
		assertThat(JSON.readTree(payload).has("regra_id")).isFalse();
		assertThat(MDC.get("job_id")).isNull();
		assertThat(MDC.get("user_id")).isNull();
	}

	@ParameterizedTest
	@ValueSource(strings = { "falha", "cancelado", "rollback" })
	void portaRespeitaFalhaCancelamentoERollbackComObservabilidade(String cenario) throws Exception {
		var criada = criada(voz("audio/ogg", ogg(4), PARAMETROS, rh), "voz", "aguardando_transcricao");
		UUID job = UUID.fromString(criada.path("job").path("id").asString());
		UUID id = UUID.fromString(criada.path("id").asString());
		var porta = contexto.getBean(JobsDeSubmissoes.class);
		var tx = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
		String operacao = cenario.equals("falha") ? "falhar" : "concluir";
		String resultado = switch (cenario) {
			case "falha" -> "aplicada";
			case "cancelado" -> "descartada";
			default -> "rollback";
		};
		var registry = contexto.getBean(MeterRegistry.class);
		var timer = contexto.getBean(synapse.api.core.metrics.AppMetrics.class)
			.transcricaoTransicao(operacao, resultado);
		long antes = timer.count();
		try (var logs = new CapturaDeLog("synapse.api.job.JobsDeSubmissoesService");
				var terminais = new CapturaDeLog(MaquinaDeEstadosDoJob.class)) {
			if (cenario.equals("cancelado")) {
				tx.executeWithoutResult(s -> contexto.getBean(MaquinaDeEstadosDoJob.class)
					.transicionar(job, JobStatus.CANCELADO, "usuario", null));
				assertThat(tx.<Boolean>execute(s -> porta.concluirTranscricao(job, id))).isFalse();
			}
			else if (cenario.equals("falha")) {
				assertThat(tx.<Boolean>execute(s -> porta.falharTranscricao(job, id))).isTrue();
			}
			else {
				tx.executeWithoutResult(s -> {
					assertThat(porta.concluirTranscricao(job, id)).isTrue();
					s.setRollbackOnly();
				});
			}
			assertThat(timer.count()).isEqualTo(antes + 1);
			assertThat(timer.totalTime(java.util.concurrent.TimeUnit.NANOSECONDS)).isPositive();
			assertThat(logs.eventos()).hasSize(1);
			for (var evento : Stream.concat(logs.eventos().stream(), terminais.eventos().stream()).toList()) {
				ContratoDeEvento.validarLog(CapturaDeLog.emJson(evento));
				assertThat(evento.getMDCPropertyMap()).containsEntry("job_id", job.toString());
				assertThat(CapturaDeLog.emJson(evento)).doesNotContain(TEXTO, FILENAME, "OggS", PARAMETROS);
			}
			assertThat(MDC.get("job_id")).isNull();
			assertThat(MDC.get("user_id")).isNull();
		}
		String status = cenario.equals("falha") ? "erro"
				: cenario.equals("cancelado") ? "cancelado" : "aguardando_transcricao";
		assertThat(dono.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, job)).isEqualTo(status);
		assertThat(dono.queryForMap("SELECT iniciado_em, finalizado_em FROM jobs WHERE id = ?", job))
			.containsEntry("iniciado_em", null);
		assertThat(contar("outbox_events")).isEqualTo(cenario.equals("rollback") ? 0 : 1);
		assertThat(contar("job_transicoes")).isEqualTo(cenario.equals("rollback") ? 1 : 2);
		if (!cenario.equals("rollback")) {
			assertThat(dono.queryForObject("SELECT tipo FROM outbox_events WHERE job_id = ?", String.class, job))
				.isEqualTo("job-encerrado");
			assertThat(tx.<Boolean>execute(s -> porta.falharTranscricao(job, id))).isFalse();
			assertThat(contar("outbox_events")).isEqualTo(1);
		}
		assertThat(registry.find("transcricao.transicao").tags("operacao", operacao, "resultado", resultado).timer())
			.isNotNull();
		assertThat(get("/metrics", "").body()).contains("transcricao_transicao_seconds_count",
				"resultado=\"" + resultado + "\"");
	}

	private static JsonNode criada(HttpResponse<String> resposta, String tipo, String status) throws Exception {
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(201);
		ContratoDeEvento.validarRespostaHttp("SubmissaoCriada", resposta.body());
		var json = JSON.readTree(resposta.body());
		assertThat(json.path("tipo").asString()).isEqualTo(tipo);
		assertThat(json.path("finalidade").asString()).isEqualTo("entrada_inicial");
		assertThat(json.path("job").path("status").asString()).isEqualTo(status);
		assertThat(json.has("rodada")).isFalse();
		return json;
	}

	private static void transicaoInicial(UUID job, String status) {
		assertThat(dono.queryForMap("SELECT * FROM job_transicoes WHERE job_id = ?", job))
			.containsEntry("status_anterior", null)
			.containsEntry("status_novo", status)
			.containsEntry("ator", "usuario");
	}

	private static void consultarSemRegra(UUID job, String status) throws Exception {
		var detalhe = get("/jobs/" + job, rh);
		assertThat(detalhe.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("JobDetalhado", detalhe.body());
		assertThat(JSON.readTree(detalhe.body()).path("regras").isEmpty()).isTrue();
		assertThat(JSON.readTree(detalhe.body()).path("status").asString()).isEqualTo(status);
		var pagina = get("/jobs", rh);
		assertThat(pagina.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("PaginaJobs", pagina.body());
		assertThat(JSON.readTree(pagina.body()).path("itens").get(0).path("id").asString()).isEqualTo(job.toString());
	}

	private static void recusa(HttpResponse<String> resposta, int status, String codigo) throws Exception {
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(status);
		ContratoDeEvento.validarRespostaHttp("Erro", resposta.body());
		assertThat(JSON.readTree(resposta.body()).path("codigo").asString()).isEqualTo(codigo);
		assertThat(resposta.body()).doesNotContain(FILENAME, "Descrição privada", "SQLException", "stackTrace", "OggS");
		semEfeitos();
	}

	private static void semEfeitos() {
		for (String tabela : List.of("submissoes", "jobs", "job_transicoes", "trabalhos_transcricao", "outbox_events",
				"regras")) {
			assertThat(contar(tabela)).as(tabela).isZero();
		}
	}

	private static long contar(String tabela) {
		return Objects.requireNonNull(dono.queryForObject("SELECT count(*) FROM " + tabela, Long.class));
	}

	private static double contador(String tipo, String resultado) {
		var counter = contexto.getBean(MeterRegistry.class)
			.find("submissoes.criacao")
			.tags("tipo", tipo, "resultado", resultado)
			.counter();
		return counter == null ? 0 : counter.count();
	}

	private static String corpoTexto(String texto) {
		return "{\"finalidade\":\"entrada_inicial\",\"tipo\":\"texto\",\"texto\":" + JSON.writeValueAsString(texto)
				+ ",\"orcamento\":485000.1234567890123456789,\"competencias\":[\"2025-11\",\"2025-08\"]}";
	}

	private static byte[] ogg(int tamanho) {
		return Arrays.copyOf("OggS".getBytes(StandardCharsets.US_ASCII), tamanho);
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

	private static HttpResponse<String> voz(String media, byte[] bytes, String parametros, String token)
			throws Exception {
		return multipart(media, bytes, parametros, token, "");
	}

	private static HttpResponse<String> multipart(String media, byte[] bytes, String parametros, String token,
			String ausente) throws Exception {
		return multipart(media, bytes, parametros, token, ausente, "multipart/form-data");
	}

	private static HttpResponse<String> multipart(String media, byte[] bytes, String parametros, String token,
			String ausente, String tipoRequisicao) throws Exception {
		var corpo = new ByteArrayOutputStream();
		if (!ausente.equals("audio")) {
			corpo.write(("--t231\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"" + FILENAME
					+ "\"\r\nContent-Type: " + media + "\r\n\r\n")
				.getBytes(StandardCharsets.UTF_8));
			corpo.write(bytes);
			corpo.write("\r\n".getBytes(StandardCharsets.UTF_8));
		}
		if (!ausente.equals("parametros")) {
			corpo.write(
					("--t231\r\nContent-Disposition: form-data; name=\"parametros\"\r\nContent-Type: application/json\r\n\r\n"
							+ parametros + "\r\n")
						.getBytes(StandardCharsets.UTF_8));
		}
		corpo.write("--t231--\r\n".getBytes(StandardCharsets.UTF_8));
		return HTTP.send(requisicao("/submissoes", token).header("Content-Type", tipoRequisicao + "; boundary=t231")
			.POST(HttpRequest.BodyPublishers.ofByteArray(corpo.toByteArray()))
			.build(), HttpResponse.BodyHandlers.ofString());
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
