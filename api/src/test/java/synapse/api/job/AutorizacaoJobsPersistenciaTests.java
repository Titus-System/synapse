package synapse.api.job;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
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
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import synapse.api.ApiApplication;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;

import static org.assertj.core.api.Assertions.assertThat;

@EnabledIf("dockerIsAvailable")
class AutorizacaoJobsPersistenciaTests {

	private static final UUID A = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final UUID B = UUID.fromString("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");

	private static final String ISSUER = "https://emissor-de-teste.invalid/realms/synapse";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

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
		contexto = new SpringApplicationBuilder(ApiApplication.class, RotasDeTeste.class)
			.web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.keycloak.enabled=true", "--app.keycloak.issuer-uri=" + ISSUER,
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
	void prepararUsuarios() {
		dono.execute("TRUNCATE usuarios CASCADE");
		dono.update("""
				INSERT INTO usuarios (id, login, nome, papel, keycloak_sub, criado_em)
				VALUES (?, 'a', 'A', 'profissional_rh', 'subject-a', now()),
				       (?, 'b', 'B', 'profissional_rh', 'subject-b', now())
				""", A, B);
	}

	static Stream<Arguments> mutacoesNegadas() {
		return Stream.of("criar", "parameters", "reprocessar", "confirmar_liberar", "salvar", "cancelar", "arquivar")
			.flatMap(rota -> Stream.of("auditor", "alheio", "nenhum", "ambos")
				.filter(perfil -> !rota.equals("criar") || !perfil.equals("alheio"))
				.map(perfil -> Arguments.of(rota, perfil)));
	}

	@ParameterizedTest(name = "{0} negado para {1} sem escrita")
	@MethodSource("mutacoesNegadas")
	void negacaoNaoAlteraJobsRegrasTransicoesAcoesTrilhasSubmissoesOuOutbox(String rota, String perfil)
			throws Exception {
		UUID job = criarJob(A, estadoPara(rota));
		String antes = snapshotNegocio();
		String usuarios = snapshotUsuarios();
		List<String> papeis = switch (perfil) {
			case "auditor" -> List.of("auditor", "offline_access");
			case "nenhum" -> List.of("offline_access");
			case "ambos" -> List.of("profissional-rh", "auditor");
			default -> List.of("profissional-rh");
		};
		String token = token(perfil.equals("alheio") ? "subject-b" : "subject-a", papeis);
		HttpResponse<String> resposta = chamar("POST", caminho(rota, job), corpo(rota), token);
		assertThat(resposta.statusCode()).isEqualTo(403);
		assertThat(new JsonMapper().readTree(resposta.body()).path("codigo").asString()).isEqualTo("sem_permissao");
		assertThat(snapshotNegocio()).isEqualTo(antes);
		if (perfil.equals("nenhum") || perfil.equals("ambos")) {
			assertThat(snapshotUsuarios()).isEqualTo(usuarios);
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "parameters", "reprocessar", "confirmar_liberar", "salvar", "cancelar", "arquivar" })
	void donoRhExecutaMutacaoNoEstadoPermitido(String rota) throws Exception {
		UUID job = criarJob(A, estadoPara(rota));
		HttpResponse<String> resposta = chamar("POST", caminho(rota, job), corpo(rota),
				token("subject-a", List.of("profissional-rh")));
		assertThat(resposta.statusCode())
			.isEqualTo(rota.equals("parameters") ? 202 : rota.equals("reprocessar") ? 201 : 200);
		if (rota.equals("reprocessar")) {
			UUID novo = UUID.fromString(new JsonMapper().readTree(resposta.body()).path("id").asString());
			assertThat(dono.queryForObject("SELECT usuario_id FROM jobs WHERE id = ?", UUID.class, novo)).isEqualTo(A);
			assertThat(dono.queryForObject("SELECT job_origem_id FROM jobs WHERE id = ?", UUID.class, novo))
				.isEqualTo(job);
		}
		else if (rota.equals("parameters")) {
			assertThat(dono.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Long.class, job))
				.isEqualTo(2);
		}
		else {
			assertThat(dono.queryForObject("SELECT acao FROM job_acoes WHERE job_id = ?", String.class, job))
				.isEqualTo(rota);
		}
	}

	@Test
	void listaSomentePropriosEConsultaConferePossePersistida() throws Exception {
		UUID proprio = criarJob(A, "gerando_regra");
		UUID alheio = criarJob(B, "gerando_regra");
		String token = token("subject-a", List.of("profissional-rh", "offline_access"));
		HttpResponse<String> lista = chamar("GET", "/jobs?usuario_id=" + B, "", token);
		assertThat(lista.statusCode()).isEqualTo(200);
		var pagina = new JsonMapper().readTree(lista.body());
		assertThat(pagina.path("total").asLong()).isEqualTo(1);
		assertThat(pagina.path("itens").size()).isEqualTo(1);
		assertThat(pagina.path("itens").path(0).path("id").asString()).isEqualTo(proprio.toString());
		assertThat(chamar("GET", "/jobs/" + proprio, "", token).statusCode()).isEqualTo(200);
		assertThat(chamar("GET", "/jobs/" + alheio + "?usuario_id=" + B, "", token).statusCode()).isEqualTo(403);
		assertThat(chamar("GET", "/jobs/" + UUID.randomUUID(), "", token).statusCode()).isEqualTo(404);
	}

	@Test
	void criacaoUsaSubEIgnoraIdentidadeForjadaEPapelLocal() throws Exception {
		dono.update("UPDATE usuarios SET papel = 'auditor' WHERE id = ?", A);
		String corpo = CriarJobControllerTests.FORMULARIO.replace("\"origem\"",
				"\"usuario_id\":\"" + B + "\",\"origem\"");
		HttpResponse<String> resposta = chamar("POST", "/jobs?usuario_id=" + B, corpo,
				token("subject-a", List.of("profissional-rh")));
		assertThat(resposta.statusCode()).isEqualTo(201);
		UUID job = UUID.fromString(new JsonMapper().readTree(resposta.body()).path("id").asString());
		assertThat(dono.queryForObject("SELECT usuario_id FROM jobs WHERE id = ?", UUID.class, job)).isEqualTo(A);
		assertThat(dono.queryForObject("SELECT papel FROM usuarios WHERE id = ?", String.class, A))
			.isEqualTo("auditor");
	}

	@ParameterizedTest
	@ValueSource(strings = { "profissional-rh", "auditor" })
	void novaContaPersistePapelCorrespondenteAoRealm(String papel) throws Exception {
		HttpResponse<String> resposta = chamar("GET", "/jobs", "", token("novo-sub", List.of(papel)));
		assertThat(resposta.statusCode()).isEqualTo(papel.equals("auditor") ? 403 : 200);
		assertThat(dono.queryForObject("SELECT papel FROM usuarios WHERE keycloak_sub = 'novo-sub'", String.class))
			.isEqualTo(papel.equals("auditor") ? "auditor" : "profissional_rh");
	}

	@ParameterizedTest
	@ValueSource(strings = { "nenhum", "ambos" })
	void papelInvalidoNaoCriaContaNemAssociaContaLegada(String perfil) throws Exception {
		dono.update("UPDATE usuarios SET keycloak_sub = NULL WHERE id = ?", A);
		String antes = snapshotUsuarios();
		List<String> papeis = perfil.equals("ambos") ? List.of("profissional-rh", "auditor")
				: List.of("offline_access");
		assertThat(chamar("GET", "/jobs", "", token("subject-a", papeis)).statusCode()).isEqualTo(403);
		assertThat(chamar("GET", "/jobs", "", token("novo-sub", papeis)).statusCode()).isEqualTo(403);
		assertThat(snapshotUsuarios()).isEqualTo(antes);
	}

	@Test
	void subTemPrecedenciaSobreLoginLegado() throws Exception {
		dono.update("UPDATE usuarios SET login = 'outro-login' WHERE id = ?", A);
		dono.update("UPDATE usuarios SET login = 'a', keycloak_sub = NULL, criado_em = '2020-01-01' WHERE id = ?", B);
		UUID proprio = criarJob(A, "gerando_regra");
		assertThat(chamar("GET", "/jobs/" + proprio, "", token("subject-a", List.of("profissional-rh"))).statusCode())
			.isEqualTo(200);
		assertThat(dono.queryForObject("SELECT keycloak_sub IS NULL FROM usuarios WHERE id = ?", Boolean.class, B))
			.isTrue();
	}

	@ParameterizedTest
	@ValueSource(strings = { "ausente", "invalido", "expirado", "issuer", "assinatura" })
	void autenticacaoInvalidaPreserva401SemEscrita(String caso) throws Exception {
		String antes = snapshotUsuarios();
		String token = switch (caso) {
			case "ausente" -> "";
			case "invalido" -> "nao-e-jwt";
			case "expirado" ->
				assinar("subject-a", List.of("profissional-rh"), ISSUER, Instant.now().minusSeconds(300), chave);
			case "issuer" -> assinar("subject-a", List.of("profissional-rh"), "https://outro.invalid",
					Instant.now().plusSeconds(300), chave);
			default -> assinar("subject-a", List.of("profissional-rh"), ISSUER, Instant.now().plusSeconds(300),
					new RSAKeyGenerator(2048).keyID("teste").generate());
		};
		assertThat(chamar("GET", "/jobs", "", token).statusCode()).isEqualTo(401);
		assertThat(snapshotUsuarios()).isEqualTo(antes);
	}

	@Test
	void registroRealDoInterceptorNegaRotaSemPolitica() throws Exception {
		assertThat(chamar("GET", "/jobs/sem-politica", "", token("subject-a", List.of("profissional-rh"))).statusCode())
			.isEqualTo(403);
	}

	@Test
	void sseAutorizaTodaAberturaAntesDeRegistrarEmissor() throws Exception {
		UUID job = criarJob(A, "gerando_regra");
		EmissoresSse emissores = contexto.getBean(EmissoresSse.class);
		String caminho = "/jobs/" + job + "/events";
		HttpRequest pedido = HttpRequest.newBuilder(URI.create(base + caminho))
			.header("Accept", "text/event-stream")
			.header("Authorization", "Bearer " + token("subject-a", List.of("profissional-rh")))
			.build();
		HttpResponse<java.io.InputStream> stream = HTTP.send(pedido, HttpResponse.BodyHandlers.ofInputStream());
		try (var entrada = stream.body()) {
			assertThat(stream.statusCode()).isEqualTo(200);
			assertThat(entrada.read()).isNotEqualTo(-1);
			assertThat(emissores.conexoesAtivas()).isEqualTo(1);
			assertThat(chamar("GET", caminho, "", token("subject-b", List.of("profissional-rh"))).statusCode())
				.isEqualTo(403);
			assertThat(chamar("GET", caminho, "", token("subject-a", List.of("auditor"))).statusCode()).isEqualTo(403);
			assertThat(emissores.conexoesAtivas()).isEqualTo(1);
		}
		finally {
			emissores.emitir(job, EventoSse.ultimo("estado", Map.of("status", "cancelado")));
		}
		dono.update("UPDATE jobs SET usuario_id = ? WHERE id = ?", B, job);
		assertThat(chamar("GET", caminho, "", token("subject-a", List.of("profissional-rh"))).statusCode())
			.isEqualTo(403);
		assertThat(emissores.conexoesAtivas()).isZero();
	}

	private static UUID criarJob(UUID usuario, String status) {
		UUID id = contexto.getBean(CriarJobService.class)
			.criar(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO), usuario)
			.id();
		dono.update("UPDATE jobs SET status = ? WHERE id = ?", status, id);
		return id;
	}

	private static String estadoPara(String rota) {
		return switch (rota) {
			case "parameters" -> "aguardando_confirmacao_parametros";
			case "reprocessar" -> "arquivado";
			case "arquivar" -> "simulacao_inviavel";
			default -> "aguardando_decisao_usuario";
		};
	}

	private static String caminho(String rota, UUID job) {
		return switch (rota) {
			case "criar" -> "/jobs";
			case "parameters", "reprocessar" -> "/jobs/" + job + "/" + rota;
			default -> "/jobs/" + job + "/actions";
		};
	}

	private static String corpo(String rota) {
		return switch (rota) {
			case "criar" -> CriarJobControllerTests.FORMULARIO;
			case "parameters" -> ConfirmarParametrosControllerTests.CONFIRMAR;
			case "reprocessar" -> "{}";
			default -> "{\"acao\":\"" + rota + "\"}";
		};
	}

	private static HttpResponse<String> chamar(String metodo, String caminho, String corpo, String token)
			throws Exception {
		HttpRequest.Builder pedido = HttpRequest.newBuilder(URI.create(base + caminho))
			.header("Content-Type", "application/json")
			.method(metodo,
					corpo.isEmpty() ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(corpo));
		if (!token.isEmpty()) {
			pedido.header("Authorization", "Bearer " + token);
		}
		return HTTP.send(pedido.build(), HttpResponse.BodyHandlers.ofString());
	}

	private static String token(String sub, List<String> papeis) throws Exception {
		return assinar(sub, papeis, ISSUER, Instant.now().plusSeconds(300), chave);
	}

	private static String assinar(String sub, List<String> papeis, String issuer, Instant expira, RSAKey key)
			throws Exception {
		JWTClaimsSet claims = new JWTClaimsSet.Builder().subject(sub)
			.issuer(issuer)
			.issueTime(Date.from(Instant.now().minusSeconds(600)))
			.expirationTime(Date.from(expira))
			.claim("preferred_username", sub.equals("subject-a") ? "a" : sub.equals("subject-b") ? "b" : sub)
			.claim("realm_access", Map.of("roles", papeis))
			.build();
		SignedJWT jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID("teste").build(), claims);
		jwt.sign(new RSASSASigner(key));
		return jwt.serialize();
	}

	private static String snapshotUsuarios() {
		return Objects.requireNonNull(dono.queryForObject(
				"SELECT coalesce(jsonb_agg(to_jsonb(u) ORDER BY id), '[]')::text FROM usuarios u", String.class));
	}

	private static String snapshotNegocio() {
		return Objects.requireNonNull(dono.queryForObject("""
				SELECT jsonb_build_object(
				  'jobs', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM jobs t),
				  'regras', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM regras t),
				  'transicoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM job_transicoes t),
				  'acoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM job_acoes t),
				  'trilhas', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM trilhas_auditoria t),
				  'submissoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM submissoes t),
				  'outbox', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM outbox_events t)
				)::text
				""", String.class));
	}

	@TestConfiguration(proxyBeanMethods = false)
	static class RotasDeTeste {

		@Bean
		AutorizacaoJobsTests.RotaSemPolitica rotaSemPolitica() {
			return new AutorizacaoJobsTests.RotaSemPolitica();
		}

	}

}
