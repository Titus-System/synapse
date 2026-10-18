package synapse.api.submissoes;

import java.io.ByteArrayOutputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import io.micrometer.core.instrument.MeterRegistry;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.PlatformTransactionManager;

import synapse.api.ApiApplication;
import synapse.api.core.config.AppProperties;
import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.job.CapturaDeLog;
import synapse.api.job.ContratoDeEvento;
import synapse.api.job.JobsDeSubmissoes;
import synapse.api.job.StreamCliente;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * A correção por voz pelo caminho real: {@code POST /submissoes} em multipart com
 * autenticação, Postgres de verdade e o provedor de transcrição num servidor HTTP local
 * que responde como o Deepgram. O teste chama o processador e observa o banco, o outbox,
 * {@code GET /jobs/{id}/rodadas}, os logs e as métricas.
 */
class CorrecoesPorVozTests {

	private static final UUID USUARIO = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final UUID JOB = UUID.fromString("11111111-1111-4111-8111-111111111111");

	private static final UUID REGRA = UUID.fromString("22222222-2222-4222-8222-222222222222");

	private static final UUID RODADA = UUID.fromString("33333333-3333-4333-8333-333333333333");

	private static final String ISSUER = "https://emissor-de-teste.invalid/realms/synapse";

	private static final String CHAVE = "chave-ficticia-do-teste";

	private static final String TEXTO = "Correção privada falada: o percentual é de dois e meio.";

	private static final String CONFLITOS = "[{\"elementos\":[\"nucleo.percentual\"],\"motivo\":\"percentual ausente\",\"campo_futuro\":true}]";

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final AtomicBoolean VOZ = new AtomicBoolean(true);

	private static final AtomicInteger STATUS = new AtomicInteger(200);

	private static final AtomicReference<String> TRANSCRITO = new AtomicReference<>(TEXTO);

	private static final AtomicInteger CHAMADAS = new AtomicInteger();

	/** Roda dentro do handler do provedor, com a chamada em curso. */
	private static final AtomicReference<Runnable> DURANTE_A_CHAMADA = new AtomicReference<>();

	private static PostgreSQLContainer postgres;

	private static ConfigurableApplicationContext contexto;

	private static HttpServer jwks;

	private static HttpServer provedor;

	private static RSAKey chave;

	private static JdbcTemplate dono;

	private static String base;

	private static String rh;

	private static RelogioControlado relogio = new RelogioControlado();

	private ProcessadorTranscricao processador;

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
		provedor = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
		provedor.setExecutor(Executors.newCachedThreadPool());
		provedor.createContext("/v1/listen", CorrecoesPorVozTests::responder);
		provedor.start();
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		contexto = new SpringApplicationBuilder(ApiApplication.class, CapacidadeDeTeste.class)
			.web(WebApplicationType.SERVLET)
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
					"--app.transcription.api-key=" + CHAVE,
					"--app.transcription.base-url=http://127.0.0.1:" + provedor.getAddress().getPort(),
					"--app.transcription.connect-timeout-ms=1000", "--app.transcription.read-timeout-ms=5000",
					"--app.transcription.processor.enabled=false",
					"--app.transcription.processor.reservation-timeout=30s");
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
		DisponibilidadeTranscricao capacidade(ClienteDeepgram cliente) {
			return new DisponibilidadeTranscricao(cliente) {
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
		if (provedor != null) {
			provedor.stop(0);
		}
	}

	@BeforeEach
	void limpar() {
		VOZ.set(true);
		STATUS.set(200);
		TRANSCRITO.set(TEXTO);
		CHAMADAS.set(0);
		DURANTE_A_CHAMADA.set(null);
		relogio = new RelogioControlado();
		processador = new ProcessadorTranscricao(contexto.getBean(SubmissoesRepository.class),
				contexto.getBean(ClienteDeepgram.class), contexto.getBean(JobsDeSubmissoes.class),
				contexto.getBean(PlatformTransactionManager.class), contexto.getBean(CorrelationContext.class),
				contexto.getBean(AppMetrics.class), contexto.getBean(AppProperties.class), relogio);
		dono.execute("TRUNCATE usuarios CASCADE");
		dono.update(
				"INSERT INTO usuarios (id, login, nome, papel, keycloak_sub, criado_em) VALUES (?, 'rh', 'RH', 'profissional_rh', 'subject-a', now())",
				USUARIO);
	}

	@AfterEach
	void conferirCorrelacaoLimpa() {
		processador.encerrar();
		assertThat(MDC.get("job_id")).as("o ciclo não pode deixar o job_id na thread").isNull();
	}

	@Test
	void aceitaCorrecaoPorVozSemEventoEDevolveARodadaEmTranscricao() throws Exception {
		UUID inicial = prepararJob(JOB, REGRA, RODADA);
		String inicialAntes = linha("submissoes", inicial);
		byte[] audio = wav();

		JsonNode criada = aceita(JOB, audio);

		UUID submissao = UUID.fromString(criada.path("id").asString());
		assertThat(criada.path("tipo").asString()).isEqualTo("voz");
		assertThat(criada.path("rodada").path("id").asString()).isEqualTo(RODADA.toString());
		assertThat(criada.path("rodada").path("correcao").path("tipo").asString()).isEqualTo("voz");
		assertThat(criada.path("rodada").path("correcao").path("texto").isNull()).isTrue();
		assertThat(criada.path("rodada").path("conflitos").path(0).path("campo_futuro").asBoolean()).isTrue();
		var gravada = dono.queryForMap("SELECT * FROM submissoes WHERE id = ?", submissao);
		assertThat(gravada).containsEntry("usuario_id", USUARIO)
			.containsEntry("tipo", "voz")
			.containsEntry("formato", "wav")
			.containsEntry("transcricao", null)
			.containsEntry("transcrito_em", null);
		assertThat((byte[]) gravada.get("binario")).containsExactly(audio);
		assertThat(dono.queryForMap("SELECT estado, submissao_correcao_id FROM rodadas_correcao WHERE id = ?", RODADA))
			.containsEntry("estado", "em_transcricao")
			.containsEntry("submissao_correcao_id", submissao);
		assertThat(trabalho(submissao)).containsEntry("job_id", JOB)
			.containsEntry("finalidade", "correcao")
			.containsEntry("estado", "pendente")
			.containsEntry("tentativas", 0);
		assertThat(contar("outbox_events")).isZero();
		assertThat(dono.queryForMap("SELECT status, submissao_id FROM jobs WHERE id = ?", JOB))
			.containsEntry("status", "aguardando_confirmacao_parametros")
			.containsEntry("submissao_id", inicial);
		assertThat(linha("submissoes", inicial)).isEqualTo(inicialAntes);

		JsonNode rodada = unicaRodada(JOB);
		assertThat(rodada.path("estado").asString()).isEqualTo("em_transcricao");
		assertThat(rodada.path("correcao").path("tipo").asString()).isEqualTo("voz");
		assertThat(rodada.path("correcao").path("texto").isNull()).isTrue();
	}

	@Test
	void transcricaoLevaARodadaAReextracaoEPublicaOMesmoEventoDaCorrecaoPorTexto() throws Exception {
		UUID inicial = prepararJob(JOB, REGRA, RODADA);
		String inicialAntes = linha("submissoes", inicial);
		UUID outroJob = UUID.randomUUID();
		UUID outraRegra = UUID.randomUUID();
		prepararJob(outroJob, outraRegra, UUID.randomUUID());
		UUID submissao = UUID.fromString(aceita(JOB, wav()).path("id").asString());
		long transicoes = contar("job_transicoes");
		var stream = abrirStream(JOB);

		processador.processarPendentes();

		assertThat(CHAMADAS.get()).isEqualTo(1);
		assertThat(dono.queryForMap("SELECT transcricao, transcrito_em FROM submissoes WHERE id = ?", submissao))
			.containsEntry("transcricao", TEXTO)
			.hasEntrySatisfying("transcrito_em", instante -> assertThat(instante).isNotNull());
		assertThat(dono.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, RODADA))
			.isEqualTo("em_reextracao");
		assertThat(trabalho(submissao)).containsEntry("estado", "concluido").containsEntry("reservado_ate", null);
		assertThat(status(JOB)).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(contar("job_transicoes")).isEqualTo(transicoes);
		assertThat(linha("submissoes", inicial)).isEqualTo(inicialAntes);
		JsonNode porVoz = correcaoSubmetida(JOB);
		assertThat(porVoz.path("job_id").asString()).isEqualTo(JOB.toString());
		assertThat(porVoz.path("regra_origem_id").asString()).isEqualTo(REGRA.toString());
		assertThat(porVoz.path("submissao_id").asString()).isEqualTo(submissao.toString());
		assertThat(porVoz.path("competencias").toString()).isEqualTo("[\"2025-08\",\"2025-11\"]");

		JsonNode rodada = unicaRodada(JOB);
		assertThat(rodada.path("estado").asString()).isEqualTo("em_reextracao");
		assertThat(rodada.path("correcao").path("tipo").asString()).isEqualTo("voz");
		assertThat(rodada.path("correcao").path("texto").asString()).isEqualTo(TEXTO);

		var porTexto = texto(corpoTexto(outroJob, "Correção digitada."), rh);
		assertThat(porTexto.statusCode()).as(porTexto.body()).isEqualTo(201);
		JsonNode digitada = correcaoSubmetida(outroJob);
		assertThat(digitada.path("regra_origem_id").asString()).isEqualTo(outraRegra.toString());
		ObjectNode semIdentidadeVoz = (ObjectNode) porVoz.deepCopy();
		ObjectNode semIdentidadeTexto = (ObjectNode) digitada.deepCopy();
		semIdentidadeVoz.remove(List.of("job_id", "regra_origem_id", "submissao_id"));
		semIdentidadeTexto.remove(List.of("job_id", "regra_origem_id", "submissao_id"));
		assertThat(semIdentidadeVoz).isEqualTo(semIdentidadeTexto);
		assertThat(porVoz.propertyNames()).containsExactlyInAnyOrderElementsOf(digitada.propertyNames());

		processador.processarPendentes();
		assertThat(CHAMADAS.get()).as("o trabalho concluído não volta ao ciclo").isEqualTo(1);
		assertThat(contar("outbox_events WHERE tipo = 'correcao-submetida' AND job_id = '" + JOB + "'")).isEqualTo(1);
		try {
			assertThat(stream.conteudo()).as("a transcrição concluída não anuncia falha").doesNotContain("event:etapa");
		}
		finally {
			stream.fechar();
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "permanente", "texto_vazio", "esgotado" })
	void falhaDaTranscricaoFechaARodadaEReabreAPendenteSemMudarOJob(String falha) throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		UUID submissao = UUID.fromString(aceita(JOB, wav()).path("id").asString());
		long transicoes = contar("job_transicoes");
		var stream = abrirStream(JOB);
		stream.aguardarBloco("\"status\":\"aguardando_confirmacao_parametros\"", Duration.ofSeconds(10));
		switch (falha) {
			case "permanente" -> STATUS.set(400);
			case "texto_vazio" -> TRANSCRITO.set("  \\u3000 ");
			default -> STATUS.set(503);
		}

		if ("esgotado".equals(falha)) {
			relogio.fixar(Instant.now().plusSeconds(1).truncatedTo(ChronoUnit.MICROS));
			for (int tentativa = 1; tentativa < 3; tentativa++) {
				processador.processarPendentes();
				assertThat(trabalho(submissao)).containsEntry("estado", "pendente");
				assertThat(
						dono.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, RODADA))
					.isEqualTo("em_transcricao");
				relogio.fixar(
						((java.sql.Timestamp) Objects.requireNonNull(trabalho(submissao).get("proxima_tentativa_em")))
							.toInstant());
			}
		}
		processador.processarPendentes();

		assertThat(trabalho(submissao)).containsEntry("estado", "falhou").containsEntry("reservado_ate", null);
		assertThat(dono.queryForMap("SELECT transcricao, transcrito_em FROM submissoes WHERE id = ?", submissao))
			.containsEntry("transcricao", null)
			.containsEntry("transcrito_em", null);
		assertThat(status(JOB)).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(contar("job_transicoes")).isEqualTo(transicoes);
		assertThat(contar("outbox_events")).isZero();
		JsonNode historico = rodadas(JOB);
		assertThat(historico.size()).isEqualTo(2);
		JsonNode falhou = historico.path(0);
		assertThat(falhou.path("id").asString()).isEqualTo(RODADA.toString());
		assertThat(falhou.path("estado").asString()).isEqualTo("reextracao_falhou");
		assertThat(falhou.path("correcao").path("tipo").asString()).isEqualTo("voz");
		assertThat(falhou.path("correcao").path("texto").isNull()).isTrue();
		JsonNode nova = historico.path(1);
		assertThat(nova.path("estado").asString()).isEqualTo("pendente");
		assertThat(nova.path("rodada_anterior_id").asString()).isEqualTo(RODADA.toString());
		assertThat(nova.path("regra_analisada_id").asString()).isEqualTo(REGRA.toString());
		assertThat(nova.path("conflitos")).isEqualTo(JSON.readTree(CONFLITOS));
		assertThat(nova.path("correcao").isNull()).isTrue();

		try {
			JsonNode etapa = etapaDoStream(stream.aguardarBloco("event:etapa", Duration.ofSeconds(10)));
			assertThat(etapa.path("etapa").asString()).isEqualTo("extracao_parametros");
			assertThat(etapa.path("status").asString()).isEqualTo("erro");
			assertThat(etapa.has("conflitos")).isFalse();
			assertThat(ocorrencias(stream.conteudo(), "event:estado")).as("o job não muda de estado").isEqualTo(1);
		}
		finally {
			stream.fechar();
		}

		var deNovo = texto(corpoTexto(JOB, "Agora por texto."), rh);
		assertThat(deNovo.statusCode()).as("o usuário corrige de novo na pendente nova").isEqualTo(201);
		assertThat(JSON.readTree(deNovo.body()).path("rodada").path("id").asString())
			.isEqualTo(nova.path("id").asString());
	}

	@Test
	void falhaNaTransacaoQueFechaARodadaNaoAnunciaNada() throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		UUID submissao = UUID.fromString(aceita(JOB, wav()).path("id").asString());
		STATUS.set(400);
		var stream = abrirStream(JOB);
		dono.execute(
				"CREATE FUNCTION falhar_t238() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'falha induzida'; END $$");
		dono.execute(
				"CREATE TRIGGER falhar_t238 BEFORE INSERT ON rodadas_correcao FOR EACH ROW EXECUTE FUNCTION falhar_t238()");
		try {
			processador.processarPendentes();
		}
		finally {
			dono.execute("DROP TRIGGER falhar_t238 ON rodadas_correcao");
			dono.execute("DROP FUNCTION falhar_t238()");
		}
		try {
			assertThat(dono.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, RODADA))
				.isEqualTo("em_transcricao");
			assertThat(contar("rodadas_correcao")).isEqualTo(1);
			assertThat(trabalho(submissao)).containsEntry("estado", "em_andamento");

			dono.update("UPDATE trabalhos_transcricao SET reservado_ate = now() - interval '1 second'");
			processador.processarPendentes();

			assertThat(dono.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, RODADA))
				.isEqualTo("reextracao_falhou");
			stream.aguardarBloco("event:etapa", Duration.ofSeconds(10));
			assertThat(ocorrencias(stream.conteudo(), "event:etapa")).as("a tentativa desfeita não anunciou nada")
				.isEqualTo(1);
		}
		finally {
			stream.fechar();
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "antes_da_chamada", "durante_a_chamada", "durante_falha_transitoria" })
	void cancelarDuranteATranscricaoAbandonaARodadaEDescartaOTrabalhoSemEvento(String momento) throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		UUID submissao = UUID.fromString(aceita(JOB, wav()).path("id").asString());
		if ("antes_da_chamada".equals(momento)) {
			cancelar(JOB);
		}
		else {
			if ("durante_falha_transitoria".equals(momento)) {
				STATUS.set(503);
			}
			DURANTE_A_CHAMADA.set(() -> cancelar(JOB));
		}

		processador.processarPendentes();

		assertThat(status(JOB)).isEqualTo("cancelado");
		assertThat(dono.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, RODADA))
			.isEqualTo("abandonada");
		assertThat(contar("rodadas_correcao")).as("o cancelamento não reabre rodada").isEqualTo(1);
		assertThat(trabalho(submissao)).containsEntry("estado", "descartado")
			.containsEntry("proxima_tentativa_em", null);
		assertThat(dono.queryForObject("SELECT transcricao FROM submissoes WHERE id = ?", String.class, submissao))
			.isNull();
		assertThat(contar("outbox_events WHERE tipo = 'correcao-submetida'")).isZero();
	}

	@ParameterizedTest
	@ValueSource(strings = { "job_em_outro_estado", "rodada_em_transcricao", "rodada_em_reextracao", "audio_invalido",
			"audio_muito_grande", "parametros_sem_job", "outro_dono", "auditor", "job_inexistente",
			"voz_indisponivel" })
	void recusaCorrecaoPorVozForaDasCondicoesSemGravarNada(String caso) throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		String parametros = parametros(JOB);
		byte[] audio = wav();
		String tipoAudio = "audio/wav";
		String credencial = rh;
		int status = 409;
		String codigo = "estado_invalido";
		switch (caso) {
			case "job_em_outro_estado" -> dono.update("UPDATE jobs SET status = 'gerando_regra' WHERE id = ?", JOB);
			case "rodada_em_transcricao", "rodada_em_reextracao" ->
				dono.update("UPDATE rodadas_correcao SET estado = ? WHERE id = ?", caso.replace("rodada_", ""), RODADA);
			case "audio_invalido" -> {
				audio = "não é áudio".getBytes(StandardCharsets.UTF_8);
				status = 422;
				codigo = "audio_invalido";
			}
			case "audio_muito_grande" -> {
				audio = new byte[AudioSubmissao.LIMITE + 1];
				status = 413;
				codigo = "audio_muito_grande";
			}
			case "parametros_sem_job" -> {
				parametros = "{\"finalidade\":\"correcao\",\"tipo\":\"voz\"}";
				status = 400;
				codigo = "requisicao_invalida";
			}
			case "outro_dono", "auditor" -> {
				credencial = "outro_dono".equals(caso) ? token("subject-b", List.of("profissional-rh"))
						: token("subject-a", List.of("auditor"));
				status = 403;
				codigo = "sem_permissao";
			}
			case "job_inexistente" -> {
				parametros = parametros(UUID.randomUUID());
				status = 404;
				codigo = "job_nao_encontrado";
			}
			default -> VOZ.set(false);
		}
		String rodadaAntes = linha("rodadas_correcao", RODADA);
		String resultado = codigo;
		double recusadas = correcoes(resultado);
		double criacoes = criacoes(resultado);

		var resposta = voz(parametros, audio, tipoAudio, credencial);

		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(status);
		ContratoDeEvento.validarRespostaHttp("Erro", resposta.body());
		assertThat(JSON.readTree(resposta.body()).path("codigo").asString()).isEqualTo(codigo);
		assertThat(resposta.body()).doesNotContain("SQLException", "stackTrace", CHAVE);
		assertThat(contar("submissoes WHERE tipo = 'voz'")).isZero();
		assertThat(contar("trabalhos_transcricao")).isZero();
		assertThat(contar("outbox_events")).isZero();
		assertThat(linha("rodadas_correcao", RODADA)).isEqualTo(rodadaAntes);
		await().untilAsserted(() -> assertThat(correcoes(resultado)).isEqualTo(recusadas + 1));
		assertThat(criacoes(resultado)).as("a recusa da correção não conta como entrada inicial").isEqualTo(criacoes);
	}

	@Test
	void corpoAcimaDoTetoDaRequisicaoNaoTemFinalidadeEContaComoSubmissao() throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		double recusadas = correcoes("audio_muito_grande");
		double criacoes = criacoes("audio_muito_grande");

		var resposta = voz(parametros(JOB), new byte[7 * 1024 * 1024], "audio/wav", rh);

		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(413);
		ContratoDeEvento.validarRespostaHttp("Erro", resposta.body());
		assertThat(JSON.readTree(resposta.body()).path("codigo").asString()).isEqualTo("audio_muito_grande");
		assertThat(contar("submissoes WHERE tipo = 'voz'")).isZero();
		await().untilAsserted(() -> assertThat(criacoes("audio_muito_grande")).isEqualTo(criacoes + 1));
		assertThat(correcoes("audio_muito_grande")).isEqualTo(recusadas);
	}

	@Test
	void falhaAoGravarOTrabalhoDesfazSubmissaoERodada() throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		double antes = correcoes("aceita");
		dono.execute(
				"CREATE FUNCTION falhar_t238() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'falha induzida confidencial'; END $$");
		dono.execute("CREATE TRIGGER falhar_t238 BEFORE INSERT ON trabalhos_transcricao FOR EACH ROW "
				+ "EXECUTE FUNCTION falhar_t238()");
		try {
			var resposta = voz(parametros(JOB), wav(), "audio/wav", rh);
			assertThat(resposta.statusCode()).isEqualTo(500);
			assertThat(resposta.body()).doesNotContain("falha induzida", "trabalhos_transcricao");
		}
		finally {
			dono.execute("DROP TRIGGER falhar_t238 ON trabalhos_transcricao");
			dono.execute("DROP FUNCTION falhar_t238()");
		}
		assertThat(contar("submissoes WHERE tipo = 'voz'")).isZero();
		assertThat(contar("trabalhos_transcricao")).isZero();
		assertThat(dono.queryForMap("SELECT estado, submissao_correcao_id FROM rodadas_correcao WHERE id = ?", RODADA))
			.containsEntry("estado", "pendente")
			.containsEntry("submissao_correcao_id", null);
		assertThat(correcoes("aceita")).isEqualTo(antes);
	}

	@Test
	void falhaNaTransacaoFinalDesfazTextoRodadaEEventoJuntos() throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		UUID submissao = UUID.fromString(aceita(JOB, wav()).path("id").asString());
		dono.execute(
				"CREATE FUNCTION falhar_t238() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'falha induzida'; END $$");
		dono.execute(
				"CREATE TRIGGER falhar_t238 BEFORE INSERT ON outbox_events FOR EACH ROW EXECUTE FUNCTION falhar_t238()");
		try {
			processador.processarPendentes();
		}
		finally {
			dono.execute("DROP TRIGGER falhar_t238 ON outbox_events");
			dono.execute("DROP FUNCTION falhar_t238()");
		}

		assertThat(dono.queryForObject("SELECT transcricao FROM submissoes WHERE id = ?", String.class, submissao))
			.isNull();
		assertThat(dono.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, RODADA))
			.isEqualTo("em_transcricao");
		assertThat(trabalho(submissao)).containsEntry("estado", "em_andamento");
		assertThat(contar("outbox_events")).isZero();

		dono.update("UPDATE trabalhos_transcricao SET reservado_ate = now() - interval '1 second'");
		processador.processarPendentes();
		assertThat(dono.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, RODADA))
			.isEqualTo("em_reextracao");
		assertThat(contar("outbox_events WHERE tipo = 'correcao-submetida'")).isEqualTo(1);
	}

	@Test
	void reservaRecuperadaConcluiUmaVezSoSemContarOutraConclusao() throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		UUID submissao = UUID.fromString(aceita(JOB, wav()).path("id").asString());
		dono.update(
				"UPDATE trabalhos_transcricao SET estado = 'em_andamento', tentativas = 1, reservado_ate = now() - interval '1 second'");
		double concluidas = trabalhos("correcao", "concluida");

		processador.processarPendentes();
		processador.processarPendentes();

		assertThat(CHAMADAS.get()).isEqualTo(1);
		assertThat(trabalho(submissao)).containsEntry("estado", "concluido").containsEntry("tentativas", 2);
		assertThat(contar("outbox_events WHERE tipo = 'correcao-submetida'")).isEqualTo(1);
		assertThat(trabalhos("correcao", "concluida")).isEqualTo(concluidas + 1);
	}

	@Test
	void correcoesPorVozEPorTextoConcorrentesSoAceitamUma() throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		try (var executor = Executors.newFixedThreadPool(2)) {
			var inicio = new CountDownLatch(1);
			var porVoz = executor.submit(() -> {
				inicio.await();
				return voz(parametros(JOB), wav(), "audio/wav", rh);
			});
			var porTexto = executor.submit(() -> {
				inicio.await();
				return texto(corpoTexto(JOB, "por texto"), rh);
			});
			inicio.countDown();
			var respostaVoz = porVoz.get(20, TimeUnit.SECONDS);
			var respostaTexto = porTexto.get(20, TimeUnit.SECONDS);
			assertThat(List.of(respostaVoz.statusCode(), respostaTexto.statusCode())).containsExactlyInAnyOrder(201,
					409);
			boolean vozVenceu = respostaVoz.statusCode() == 201;
			assertThat(dono.queryForObject("SELECT estado FROM rodadas_correcao WHERE id = ?", String.class, RODADA))
				.isEqualTo(vozVenceu ? "em_transcricao" : "em_reextracao");
			assertThat(contar("trabalhos_transcricao")).isEqualTo(vozVenceu ? 1 : 0);
			assertThat(contar("outbox_events")).isEqualTo(vozVenceu ? 0 : 1);
		}
		assertThat(contar("submissoes")).as("a inicial e a correção aceita").isEqualTo(2);
	}

	@Test
	void observaAceitacaoTranscricaoEFechamentoSemConteudo() throws Exception {
		prepararJob(JOB, REGRA, RODADA);
		UUID outroJob = UUID.randomUUID();
		UUID outraRodada = UUID.randomUUID();
		prepararJob(outroJob, UUID.randomUUID(), outraRodada);
		double aceitasAntes = correcoes("aceita");
		double recusadasAntes = correcoes("estado_invalido");
		double concluidasAntes = trabalhos("correcao", "concluida");
		double falhasAntes = trabalhos("correcao", "falhou_permanente");
		double iniciaisAntes = trabalhos("entrada_inicial", "concluida");
		try (var aceitacao = new CapturaDeLog(ObservabilidadeSubmissoes.class);
				var processamento = new CapturaDeLog(ProcessadorTranscricao.class);
				var fechamento = new CapturaDeLog("synapse.api.job.JobsDeSubmissoesService");
				var todos = new CapturaDeLog(org.slf4j.Logger.ROOT_LOGGER_NAME)) {
			aceita(JOB, wav());
			var recusada = voz(parametros(JOB), wav(), "audio/wav", rh);
			assertThat(recusada.statusCode()).isEqualTo(409);
			processador.processarPendentes();
			aceita(outroJob, wav());
			STATUS.set(400);
			processador.processarPendentes();

			await().untilAsserted(() -> assertThat(aceitacao.eventos()).hasSize(3));
			List<String> aceitas = aceitacao.eventos().stream().map(CapturaDeLog::emJson).toList();
			for (String linha : aceitas) {
				ContratoDeEvento.validarLog(linha);
				assertThat(JSON.readTree(linha).path("extra").path("tipo").asString()).isEqualTo("voz");
			}
			JsonNode primeira = JSON.readTree(aceitas.getFirst());
			assertThat(primeira.path("message").asString()).isEqualTo("correção aceita");
			assertThat(primeira.path("job_id").asString()).isEqualTo(JOB.toString());
			assertThat(primeira.path("extra").path("rodada_id").asString()).isEqualTo(RODADA.toString());
			assertThat(JSON.readTree(aceitas.get(1)).path("extra").path("motivo").asString())
				.isEqualTo("estado_invalido");

			List<JsonNode> processadas = processamento.eventos()
				.stream()
				.filter(evento -> evento.getFormattedMessage().equals("transcrição processada"))
				.map(CapturaDeLog::emJson)
				.map(JSON::readTree)
				.toList();
			assertThat(processadas).hasSize(2);
			assertThat(processadas.get(0).path("job_id").asString()).isEqualTo(JOB.toString());
			assertThat(processadas.get(0).path("extra").path("finalidade").asString()).isEqualTo("correcao");
			assertThat(processadas.get(0).path("extra").path("resultado").asString()).isEqualTo("concluida");
			assertThat(processadas.get(1).path("job_id").asString()).isEqualTo(outroJob.toString());
			assertThat(processadas.get(1).path("extra").path("resultado").asString()).isEqualTo("falhou_permanente");
			assertThat(processadas.get(1).path("extra").path("classe_motivo").asString()).isEqualTo("permanente");

			List<String> fechadas = fechamento.eventos().stream().map(CapturaDeLog::emJson).toList();
			assertThat(fechadas).hasSize(2);
			for (String linha : fechadas) {
				ContratoDeEvento.validarLog(linha);
			}
			JsonNode transcrita = JSON.readTree(fechadas.get(0));
			assertThat(transcrita.path("job_id").asString()).isEqualTo(JOB.toString());
			assertThat(transcrita.path("extra").path("rodada_id").asString()).isEqualTo(RODADA.toString());
			JsonNode falhou = JSON.readTree(fechadas.get(1));
			assertThat(falhou.path("job_id").asString()).isEqualTo(outroJob.toString());
			assertThat(falhou.path("extra").path("rodada_id").asString()).isEqualTo(outraRodada.toString());
			assertThat(falhou.path("extra").path("rodada_nova_id").asString()).isNotBlank();

			for (var evento : todos.eventos()) {
				assertThat(CapturaDeLog.emJson(evento)).doesNotContain(TEXTO, "RIFF", CHAVE, rh);
			}
		}

		assertThat(correcoes("aceita")).isEqualTo(aceitasAntes + 2);
		assertThat(correcoes("estado_invalido")).isEqualTo(recusadasAntes + 1);
		assertThat(trabalhos("correcao", "concluida")).isEqualTo(concluidasAntes + 1);
		assertThat(trabalhos("correcao", "falhou_permanente")).isEqualTo(falhasAntes + 1);
		assertThat(trabalhos("entrada_inicial", "concluida")).isEqualTo(iniciaisAntes);
		String scrape = HTTP
			.send(HttpRequest.newBuilder(URI.create(base + "/metrics")).GET().build(),
					HttpResponse.BodyHandlers.ofString())
			.body();
		assertThat(amostra(scrape, "submissoes_correcoes_total{resultado=\"aceita\",tipo=\"voz\"}"))
			.isEqualTo(correcoes("aceita"));
		assertThat(amostra(scrape, "submissoes_correcoes_total{resultado=\"estado_invalido\",tipo=\"voz\"}"))
			.isEqualTo(correcoes("estado_invalido"));
		assertThat(amostra(scrape, "transcricao_trabalhos_total{finalidade=\"correcao\",resultado=\"concluida\"}"))
			.isEqualTo(trabalhos("correcao", "concluida"));
		assertThat(
				amostra(scrape, "transcricao_trabalhos_total{finalidade=\"correcao\",resultado=\"falhou_permanente\"}"))
			.isEqualTo(trabalhos("correcao", "falhou_permanente"));
		assertThat(scrape).doesNotContain(JOB.toString(), RODADA.toString(), TEXTO);
	}

	private static UUID prepararJob(UUID job, UUID regra, UUID rodada) {
		UUID inicial = Objects.requireNonNull(dono.queryForObject(
				"INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em) VALUES (?, 'texto', 'Descrição inicial privada.', now()) RETURNING id",
				UUID.class, USUARIO));
		dono.update(
				"INSERT INTO jobs (id, usuario_id, status, submissao_id, competencias, orcamento, meta_venda, criado_em) VALUES (?, ?, 'aguardando_confirmacao_parametros', ?, ARRAY['2025-08','2025-11'], 485000.12, 9000000, now())",
				job, USUARIO, inicial);
		dono.update(
				"INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em) VALUES (?, ?, 1, 'extracao', '{}', '[]', ?, now())",
				regra, job, "a".repeat(64));
		dono.update(
				"INSERT INTO rodadas_correcao (id, job_id, regra_analisada_id, conflitos, estado, criada_em, atualizada_em) VALUES (?, ?, ?, ?::jsonb, 'pendente', '2026-10-13T10:00:00Z', '2026-10-13T10:00:00Z')",
				rodada, job, regra, CONFLITOS);
		return inicial;
	}

	private static JsonNode aceita(UUID job, byte[] audio) throws Exception {
		var resposta = voz(parametros(job), audio, "audio/wav", rh);
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(201);
		ContratoDeEvento.validarRespostaHttp("SubmissaoCriada", resposta.body());
		JsonNode json = JSON.readTree(resposta.body());
		assertThat(json.path("finalidade").asString()).isEqualTo("correcao");
		assertThat(json.path("job").path("id").asString()).isEqualTo(job.toString());
		assertThat(json.path("job").path("status").asString()).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(json.path("rodada").path("estado").asString()).isEqualTo("em_transcricao");
		return json;
	}

	private static JsonNode rodadas(UUID job) throws Exception {
		var resposta = HTTP.send(requisicao("/jobs/" + job + "/rodadas", rh).GET().build(),
				HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		JsonNode lista = JSON.readTree(resposta.body());
		for (JsonNode rodada : lista) {
			ContratoDeEvento.validarRespostaHttp("Rodada", rodada.toString());
		}
		return lista;
	}

	private static JsonNode unicaRodada(UUID job) throws Exception {
		JsonNode lista = rodadas(job);
		assertThat(lista.size()).isEqualTo(1);
		return lista.path(0);
	}

	private static JsonNode correcaoSubmetida(UUID job) throws Exception {
		String payload = Objects.requireNonNull(dono.queryForObject(
				"SELECT payload::text FROM outbox_events WHERE job_id = ? AND tipo = 'correcao-submetida'",
				String.class, job));
		ContratoDeEvento.validar("correcao-submetida", payload);
		assertThat(payload).doesNotContain("texto", "transcricao", "Correção");
		return JSON.readTree(payload);
	}

	private static void cancelar(UUID job) {
		try {
			var resposta = HTTP
				.send(requisicao("/jobs/" + job + "/actions", rh).header("Content-Type", "application/json")
					.POST(HttpRequest.BodyPublishers.ofString("{\"acao\":\"cancelar\"}"))
					.build(), HttpResponse.BodyHandlers.ofString());
			assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		}
		catch (Exception ex) {
			throw new AssertionError(ex);
		}
	}

	private static String parametros(UUID job) {
		return "{\"finalidade\":\"correcao\",\"tipo\":\"voz\",\"job_id\":\"" + job + "\"}";
	}

	private static String corpoTexto(UUID job, String texto) {
		return "{\"finalidade\":\"correcao\",\"tipo\":\"texto\",\"job_id\":\"" + job + "\",\"texto\":"
				+ JSON.writeValueAsString(texto) + "}";
	}

	private static HttpResponse<String> voz(String parametros, byte[] audio, String tipo, String token)
			throws Exception {
		String limite = "----t238";
		var corpo = new ByteArrayOutputStream();
		corpo.write(("--" + limite + "\r\nContent-Disposition: form-data; name=\"parametros\"\r\n"
				+ "Content-Type: application/json\r\n\r\n" + parametros + "\r\n")
			.getBytes(StandardCharsets.UTF_8));
		corpo.write(("--" + limite + "\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"correcao.wav\"\r\n"
				+ "Content-Type: " + tipo + "\r\n\r\n")
			.getBytes(StandardCharsets.UTF_8));
		corpo.write(audio);
		corpo.write(("\r\n--" + limite + "--\r\n").getBytes(StandardCharsets.UTF_8));
		return HTTP
			.send(requisicao("/submissoes", token).header("Content-Type", "multipart/form-data; boundary=" + limite)
				.POST(HttpRequest.BodyPublishers.ofByteArray(corpo.toByteArray()))
				.build(), HttpResponse.BodyHandlers.ofString());
	}

	private static HttpResponse<String> texto(String corpo, String token) throws Exception {
		return HTTP.send(requisicao("/submissoes", token).header("Content-Type", "application/json")
			.POST(HttpRequest.BodyPublishers.ofString(corpo))
			.build(), HttpResponse.BodyHandlers.ofString());
	}

	private static HttpRequest.Builder requisicao(String path, String token) {
		var builder = HttpRequest.newBuilder(URI.create(base + path));
		if (!token.isEmpty()) {
			builder.header("Authorization", "Bearer " + token);
		}
		return builder;
	}

	private static void responder(HttpExchange exchange) throws java.io.IOException {
		CHAMADAS.incrementAndGet();
		exchange.getRequestBody().readAllBytes();
		Runnable durante = DURANTE_A_CHAMADA.get();
		if (durante != null) {
			durante.run();
		}
		byte[] corpo = ("{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":\"" + TRANSCRITO.get()
				+ "\"}]}]}}")
			.getBytes(StandardCharsets.UTF_8);
		exchange.getResponseHeaders().add("Content-Type", "application/json");
		exchange.sendResponseHeaders(STATUS.get(), corpo.length);
		try (var saida = exchange.getResponseBody()) {
			saida.write(corpo);
		}
		finally {
			exchange.close();
		}
	}

	/**
	 * Um segundo de WAV PCM mono 8 kHz 16 bits, em silêncio: a api só confere o
	 * contêiner.
	 */
	private static byte[] wav() {
		int dados = 8000 * 2;
		var buffer = ByteBuffer.allocate(44 + dados).order(ByteOrder.LITTLE_ENDIAN);
		buffer.put("RIFF".getBytes(StandardCharsets.US_ASCII)).putInt(36 + dados);
		buffer.put("WAVEfmt ".getBytes(StandardCharsets.US_ASCII)).putInt(16);
		buffer.putShort((short) 1).putShort((short) 1).putInt(8000).putInt(8000 * 2);
		buffer.putShort((short) 2).putShort((short) 16);
		buffer.put("data".getBytes(StandardCharsets.US_ASCII)).putInt(dados);
		return buffer.array();
	}

	private static String linha(String tabela, UUID id) {
		return Objects.requireNonNull(dono
			.queryForObject("SELECT row_to_json(t)::text FROM " + tabela + " t WHERE id = ?", String.class, id));
	}

	private static Map<String, Object> trabalho(UUID submissao) {
		return dono.queryForMap("SELECT * FROM trabalhos_transcricao WHERE submissao_id = ?", submissao);
	}

	private static String status(UUID job) {
		return Objects.requireNonNull(dono.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, job));
	}

	private static long contar(String tabela) {
		return Objects.requireNonNull(dono.queryForObject("SELECT count(*) FROM " + tabela, Long.class));
	}

	private static double correcoes(String resultado) {
		var contador = contexto.getBean(MeterRegistry.class)
			.find("submissoes.correcoes")
			.tag("tipo", "voz")
			.tag("resultado", resultado)
			.counter();
		return contador == null ? 0 : contador.count();
	}

	private static double criacoes(String resultado) {
		var contador = contexto.getBean(MeterRegistry.class)
			.find("submissoes.criacao")
			.tag("tipo", "voz")
			.tag("resultado", resultado)
			.counter();
		return contador == null ? 0 : contador.count();
	}

	private static StreamCliente abrirStream(UUID job) throws Exception {
		return new StreamCliente(HTTP.send(
				requisicao("/jobs/" + job + "/events", rh).header("Accept", "text/event-stream").GET().build(),
				HttpResponse.BodyHandlers.ofInputStream()));
	}

	private static JsonNode etapaDoStream(String bloco) throws Exception {
		Matcher dados = Pattern.compile("(?m)^data:(.*)$").matcher(bloco);
		assertThat(dados.find()).as("bloco sem linha data: %s", bloco).isTrue();
		ContratoDeEvento.validarEventoDoStream("etapa", dados.group(1));
		return JSON.readTree(dados.group(1));
	}

	private static int ocorrencias(String texto, String trecho) {
		return texto.split(Pattern.quote(trecho), -1).length - 1;
	}

	private static double trabalhos(String finalidade, String resultado) {
		var contador = contexto.getBean(MeterRegistry.class)
			.find("transcricao.trabalhos")
			.tag("finalidade", finalidade)
			.tag("resultado", resultado)
			.counter();
		return contador == null ? 0 : contador.count();
	}

	private static double amostra(String scrape, String serie) {
		Matcher valor = Pattern.compile("(?m)^" + Pattern.quote(serie) + " (\\S+)$").matcher(scrape);
		return valor.find() ? Double.parseDouble(valor.group(1)) : 0;
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

	private static final class RelogioControlado extends Clock {

		private volatile @Nullable Instant fixo;

		void fixar(Instant instante) {
			this.fixo = instante;
		}

		@Override
		public ZoneId getZone() {
			return ZoneOffset.UTC;
		}

		@Override
		public Clock withZone(ZoneId zona) {
			return this;
		}

		@Override
		public Instant instant() {
			Instant instante = this.fixo;
			return instante == null ? Instant.now() : instante;
		}

	}

}
