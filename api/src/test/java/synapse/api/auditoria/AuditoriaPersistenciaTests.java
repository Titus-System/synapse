package synapse.api.auditoria;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
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
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
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
 * As duas rotas de auditoria pela cadeia real: token assinado, Postgres com as migrations
 * e o usuário de banco da api. O job do registro é semeado direto nas tabelas, como o
 * codegen, o worker e a api o deixariam.
 */
@EnabledIf("dockerIsAvailable")
class AuditoriaPersistenciaTests {

	private static final UUID A = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final UUID B = UUID.fromString("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");

	private static final UUID AUDITOR = UUID.fromString("cccccccc-cccc-4ccc-8ccc-cccccccccccc");

	private static final String ISSUER = "https://emissor-de-teste.invalid/realms/synapse";

	private static final Instant T0 = Instant.parse("2026-01-01T10:00:00Z");

	private static final String NUCLEO = """
			{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"loja":["13"],"marca":["10"],"cargo":["100"]}""";

	private static final String NUCLEO_CORRIGIDO = """
			{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"loja":["13"],"marca":["10"],"cargo":["100"],
			 "percentual":0.025}""";

	private static final String NUCLEO_SUGERIDO = """
			{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"loja":["13"],"marca":["10"],"cargo":["100"],
			 "percentual":0.02}""";

	private static final String MODELO = """
			{"provedor":"openai","modelo":"gpt-4.1","versao":"2025-04-14","parametros":{"temperature":0}}""";

	private static final String TOTAIS = """
			{"baseline":529520.10,"simulado":541900.0,"diferenca_abs":12379.90,"diferenca_pct":0.023400,
			 "orcamento":600000.0,"vendas_historicas":23583194.87}""";

	private static final String ASSERCOES = """
			[{"nome":"sem_comissao_negativa","resultado":"ok","detalhe":null}]""";

	private static final String DECOMPOSICAO = """
			{"elemento":{"nucleo.percentual":12380},"loja":{"13":12380},"marca":{"10":12380},"cargo":{"100":12380},
			 "competencia":{"2025-11":12380}}""";

	private static final String LINHAS_SECRETAS = """
			{"2025-11":{"MATRIC-SECRETA":{"cod_loja":"13","cod_marca":"10","cod_cargo":"100","baseline":10,
			 "simulado":12,"diferenca":2}}}""";

	private static final String TEXTO_INICIAL = "  Comissão de 2%\n\tna loja 13   para o cargo 100 da marca 10 em novembro de 2025  ";

	private static final String PROMPT_SECRETO = "PROMPT-CONFIDENCIAL-DA-EXTRACAO";

	private static final String CODIGO_SECRETO = "def aplicar_regra(): return 'CODIGO-CONFIDENCIAL'";

	private static final String TRANSCRICAO_SECRETA = "O percentual é 2,5% TRANSCRICAO-CONFIDENCIAL";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = new JsonMapper();

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
	void prepararUsuarios() {
		dono.execute("TRUNCATE usuarios CASCADE");
		dono.update("""
				INSERT INTO usuarios (id, login, nome, papel, keycloak_sub, criado_em)
				VALUES (?, 'a', 'Profissional A', 'profissional_rh', 'subject-a', now()),
				       (?, 'b', 'Profissional B', 'profissional_rh', 'subject-b', now()),
				       (?, 'auditoria', 'Auditor', 'auditor', 'subject-auditor', now())
				""", A, B, AUDITOR);
	}

	@Test
	void auditorListaJobsDeTodosOsDonosComONomeDaListagemDoRh() throws Exception {
		UUID deA = jobDeTexto(A, TEXTO_INICIAL, T0);
		UUID deB = jobDeFormulario(B, "  Regra nomeada por B  ", T0.plusSeconds(60));
		UUID reprocessado = jobReprocessado(A, deA, T0.plusSeconds(120));

		HttpResponse<String> resposta = chamar("/auditoria/jobs", auditor());
		assertThat(resposta.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("PaginaJobsAuditoria", resposta.body());
		JsonNode pagina = JSON.readTree(resposta.body());
		assertThat(pagina.path("total").asLong()).isEqualTo(3);
		assertThat(pagina.path("pagina").asInt()).isZero();
		assertThat(pagina.path("tamanho").asInt()).isEqualTo(20);
		assertThat(ids(pagina.path("itens"))).containsExactly(reprocessado, deB, deA);
		JsonNode itemDeB = item(pagina, deB);
		assertThat(itemDeB.path("usuario").path("login").asString()).isEqualTo("b");
		assertThat(itemDeB.path("usuario").path("nome").asString()).isEqualTo("Profissional B");
		assertThat(itemDeB.path("origem").asString()).isEqualTo("formulario");
		assertThat(item(pagina, reprocessado).path("origem").asString()).isEqualTo("reprocessamento");
		assertThat(item(pagina, reprocessado).path("job_origem_id").asString()).isEqualTo(deA.toString());
		assertThat(item(pagina, deA).path("usuario").path("login").asString()).isEqualTo("a");

		JsonNode historicoDeA = JSON.readTree(chamar("/jobs", rh("subject-a")).body());
		JsonNode historicoDeB = JSON.readTree(chamar("/jobs", rh("subject-b")).body());
		assertThat(item(pagina, deA).path("nome").asString()).isEqualTo(item(historicoDeA, deA).path("nome").asString())
			.isEqualTo("Comissão de 2% na loja 13 para o cargo 100 da marc");
		assertThat(item(pagina, reprocessado).path("nome").asString())
			.isEqualTo(item(historicoDeA, reprocessado).path("nome").asString());
		assertThat(itemDeB.path("nome").asString()).isEqualTo(item(historicoDeB, deB).path("nome").asString());

		JsonNode segunda = JSON.readTree(chamar("/auditoria/jobs?pagina=1&tamanho=2", auditor()).body());
		assertThat(ids(segunda.path("itens"))).containsExactly(deA);
		assertThat(segunda.path("total").asLong()).isEqualTo(3);
	}

	@ParameterizedTest
	@ValueSource(strings = { "pagina=-1", "pagina=um", "tamanho=0", "tamanho=101", "tamanho=vinte" })
	void paginacaoInvalidaRespondeComoAListagemDeJobs(String parametro) throws Exception {
		HttpResponse<String> doHistorico = chamar("/jobs?" + parametro, rh("subject-a"));
		HttpResponse<String> daAuditoria = chamar("/auditoria/jobs?" + parametro, auditor());
		assertThat(daAuditoria.statusCode()).isEqualTo(doHistorico.statusCode()).isEqualTo(400);
		assertThat(JSON.readTree(daAuditoria.body())).isEqualTo(JSON.readTree(doHistorico.body()));
	}

	@Test
	void somenteOAuditorConsultaESemSessaoRecebe401() throws Exception {
		UUID job = jobDeTexto(A, TEXTO_INICIAL, T0);
		for (String rota : List.of("/auditoria/jobs", "/auditoria/jobs/" + job)) {
			HttpResponse<String> doDono = chamar(rota, rh("subject-a"));
			assertThat(doDono.statusCode()).isEqualTo(403);
			assertThat(JSON.readTree(doDono.body()).path("codigo").asString()).isEqualTo("sem_permissao");
			assertThat(chamar(rota, rh("subject-b")).statusCode()).isEqualTo(403);
			assertThat(chamar(rota, "").statusCode()).isEqualTo(401);
			assertThat(chamar(rota, auditor()).statusCode()).isEqualTo(200);
		}
		HttpResponse<String> inexistente = chamar("/auditoria/jobs/" + UUID.randomUUID(), auditor());
		assertThat(inexistente.statusCode()).isEqualTo(404);
		assertThat(JSON.readTree(inexistente.body()).path("codigo").asString()).isEqualTo("job_nao_encontrado");
		HttpResponse<String> malformado = chamar("/auditoria/jobs/nao-e-uuid", auditor());
		assertThat(malformado.statusCode()).isEqualTo(400);
		assertThat(JSON.readTree(malformado.body()).path("codigo").asString()).isEqualTo("requisicao_invalida");
	}

	@Test
	void registroLigaEtapasAResultadosSimulacoesESubmissoes() throws Exception {
		JobCompleto j = jobCompleto();
		String antes = snapshotNegocio();

		HttpResponse<String> resposta = chamar("/auditoria/jobs/" + j.id(), auditor());

		assertThat(resposta.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("RegistroAuditoria", resposta.body());
		assertThat(snapshotNegocio()).isEqualTo(antes);
		JsonNode registro = JSON.readTree(resposta.body());

		JsonNode job = registro.path("job");
		assertThat(job.path("id").asString()).isEqualTo(j.id().toString());
		assertThat(job.path("nome").asString()).isEqualTo("Comissão de 2% na loja 13 para o cargo 100 da marc");
		assertThat(job.path("usuario").path("login").asString()).isEqualTo("a");
		assertThat(job.path("origem").asString()).isEqualTo("texto");
		assertThat(job.path("iniciado_em").asString()).isEqualTo("2026-01-01T10:01:00Z");

		JsonNode etapas = registro.path("etapas");
		assertThat(ids(etapas)).containsExactlyElementsOf(j.etapas());
		assertEtapa(etapas, j.extracaoInicial(), null, null, j.entradaInicial());
		assertEtapa(etapas, j.reextracao(), null, null, j.correcaoAceita());
		assertEtapa(etapas, j.geracao(), null, j.simulacaoDoPrimeiroCodigo(), null);
		assertEtapa(etapas, j.correcaoDoCodigo(), j.resultadoComErro(), j.simulacaoDoCodigoCorrigido(), null);
		assertEtapa(etapas, j.decisaoInviavel(), j.resultadoInviavel(), j.simulacaoDoCodigoCorrigido(), null);
		assertEtapa(etapas, j.sugestao(), j.resultadoInviavel(), j.simulacaoDoCodigoCorrigido(), null);
		assertEtapa(etapas, j.geracaoDerivada(), j.resultadoInviavel(), j.simulacaoDaSugestao(), null);
		assertEtapa(etapas, j.decisaoViavel(), j.resultadoViavel(), j.simulacaoDaSugestao(), null);
		assertEtapa(etapas, j.fimDaBusca(), j.candidataVencedora(), j.simulacaoDaSugestao(), null);
		assertThat(etapa(etapas, j.explicacao()).path("explicacao_id").asString())
			.isEqualTo(j.explicacaoId().toString());

		assertThat(ids(registro.path("resultados"))).containsExactly(j.resultadoComErro(), j.resultadoInviavel(),
				j.resultadoViavel(), j.candidataVencedora(), j.candidataInviavel());
		assertThat(StreamSupport.stream(registro.path("resultados").spliterator(), false)
			.filter(r -> r.path("proposito").asString().equals("busca_meta"))
			.map(r -> UUID.fromString(r.path("id").asString())))
			.containsExactly(j.candidataVencedora(), j.candidataInviavel());
		assertThat(ids(registro.path("simulacoes"))).containsExactly(j.simulacaoDoPrimeiroCodigo(),
				j.simulacaoDoCodigoCorrigido(), j.simulacaoDaSugestao());

		JsonNode entradas = registro.path("entradas");
		assertThat(ids(entradas)).containsExactly(j.entradaInicial(), j.correcaoRecusada(), j.correcaoAceita());
		assertThat(entradas.path(0).path("finalidade").asString()).isEqualTo("entrada_inicial");
		assertThat(entradas.path(0).path("texto").asString()).isEqualTo(TEXTO_INICIAL);
		assertThat(entradas.path(2).path("finalidade").asString()).isEqualTo("correcao");
		assertThat(entradas.path(2).path("tipo").asString()).isEqualTo("voz");
		assertThat(entradas.path(2).path("formato").asString()).isEqualTo("ogg");
		assertThat(entradas.path(2).has("transcrito_em")).isTrue();

		JsonNode rodadas = registro.path("rodadas");
		assertThat(rodadas.path(0).has("regra_resultante_id")).isTrue();
		assertThat(rodadas.path(0).path("regra_resultante_id").isNull()).isTrue();
		assertThat(rodadas.path(0).path("rodada_anterior_id").isNull()).isTrue();
		assertThat(rodadas.path(1).path("correcao").path("tipo").asString()).isEqualTo("voz");
		assertThat(rodadas.path(1).path("regra_resultante_id").asString()).isEqualTo(j.versaoCorrigida().toString());

		assertThat(ids(registro.path("versoes"))).containsExactly(j.versaoExtraida(), j.versaoCorrigida(),
				j.versaoSugerida());
		assertThat(registro.path("versoes").path(1).path("representacao").path("extensao_da_raiz").asString())
			.isEqualTo("preservada");
		assertThat(registro.path("versoes").path(2).path("tentativa").asInt()).isEqualTo(1);
		assertThat(registro.path("chamadas_modelo").size()).isEqualTo(5);
		assertThat(registro.path("chamadas_modelo").path(0).path("resposta").path("consumo_tokens").has("tokens_in"))
			.isTrue();
		assertThat(registro.path("codigos").size()).isEqualTo(3);
		assertThat(registro.path("transicoes").size()).isEqualTo(3);
		assertThat(registro.path("acoes").path(0).path("acao").asString()).isEqualTo("aceitar_meta");
		JsonNode sugestao = registro.path("sugestoes_meta").path(0);
		assertThat(sugestao.path("resultado_id").asString()).isEqualTo(j.candidataVencedora().toString());
		assertThat(sugestao.path("resultado_anterior_id").asString()).isEqualTo(j.resultadoViavel().toString());
		assertThat(registro.path("explicacoes").path(0).path("aderencia_conferida").asBoolean()).isFalse();

		assertThat(resposta.body()).doesNotContain("\"binario\"", "\"linhas\"", "MATRIC-SECRETA")
			.contains("0.023400", "529520.10", "28000000.00");
	}

	@Test
	void registroDeJobDeFormularioSemArtefatosTemListasVazias() throws Exception {
		UUID job = jobDeFormulario(B, null, T0);

		HttpResponse<String> resposta = chamar("/auditoria/jobs/" + job, auditor());

		assertThat(resposta.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("RegistroAuditoria", resposta.body());
		JsonNode registro = JSON.readTree(resposta.body());
		assertThat(registro.path("job").has("nome")).isFalse();
		assertThat(registro.path("job").has("iniciado_em")).isFalse();
		assertThat(registro.path("entradas").path(0).path("tipo").asString()).isEqualTo("formulario");
		assertThat(registro.path("entradas").path(0).path("conteudo").path("nucleo").path("loja").path(0).asString())
			.isEqualTo("13");
		assertThat(registro.path("entradas").path(0).has("texto")).isFalse();
		for (String secao : List.of("etapas", "chamadas_modelo", "codigos", "resultados", "simulacoes", "acoes",
				"rodadas", "sugestoes_meta", "explicacoes")) {
			assertThat(registro.path(secao).isArray()).as(secao).isTrue();
			assertThat(registro.path(secao).isEmpty()).as(secao).isTrue();
		}
	}

	@Test
	void logsLevamUsuarioEJobSemConteudo() throws Exception {
		JobCompleto j = jobCompleto();
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(AuditoriaController.class)) {
			assertThat(chamar("/auditoria/jobs/" + j.id(), auditor()).statusCode()).isEqualTo(200);
			assertThat(chamar("/auditoria/jobs?pagina=0&tamanho=5", auditor()).statusCode()).isEqualTo(200);
			assertThat(chamar("/auditoria/jobs/" + UUID.randomUUID(), auditor()).statusCode()).isEqualTo(404);
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(3);
		List<JsonNode> linhas = new ArrayList<>();
		for (ILoggingEvent evento : eventos) {
			String linha = CapturaDeLog.emJson(evento);
			ContratoDeEvento.validarLog(linha);
			assertThat(linha).doesNotContain(PROMPT_SECRETO, CODIGO_SECRETO, TRANSCRICAO_SECRETA, "Comissão de 2%",
					"Correção recebida", "subject-auditor", "MATRIC-SECRETA");
			linhas.add(JSON.readTree(linha));
		}
		JsonNode consulta = linhas.get(0);
		assertThat(consulta.path("level").asString()).isEqualTo("INFO");
		assertThat(consulta.path("message").asString()).isEqualTo("consulta de auditoria encerrada");
		assertThat(consulta.path("job_id").asString()).isEqualTo(j.id().toString());
		assertThat(consulta.path("user_id").asString()).isEqualTo(AUDITOR.toString());
		assertThat(consulta.path("extra").path("resultado").asString()).isEqualTo("sucesso");
		JsonNode listagem = linhas.get(1);
		assertThat(listagem.path("level").asString()).isEqualTo("INFO");
		assertThat(listagem.path("message").asString()).isEqualTo("listagem de auditoria encerrada");
		assertThat(listagem.has("job_id")).isFalse();
		assertThat(listagem.path("user_id").asString()).isEqualTo(AUDITOR.toString());
		assertThat(listagem.path("extra").path("pagina").asInt()).isZero();
		assertThat(listagem.path("extra").path("tamanho").asInt()).isEqualTo(5);
		JsonNode inexistente = linhas.get(2);
		assertThat(inexistente.path("level").asString()).isEqualTo("WARN");
		assertThat(inexistente.path("extra").path("resultado").asString()).isEqualTo("job_nao_encontrado");
	}

	@Test
	void metricsExpoeAsRotasDeAuditoriaPeloTemplate() throws Exception {
		UUID job = jobDeTexto(A, TEXTO_INICIAL, T0);
		assertThat(chamar("/auditoria/jobs", auditor()).statusCode()).isEqualTo(200);
		assertThat(chamar("/auditoria/jobs/" + job, auditor()).statusCode()).isEqualTo(200);
		assertThat(chamar("/auditoria/jobs/" + job, rh("subject-a")).statusCode()).isEqualTo(403);

		String metricas = chamar("/metrics", "").body();

		List<String> contagens = metricas.lines()
			.filter(linha -> linha.startsWith("http_server_requests_seconds_count{"))
			.toList();
		assertThat(contagens).anyMatch(linha -> linha.contains("uri=\"/auditoria/jobs\"")
				&& linha.contains("status=\"200\"") && linha.contains("method=\"GET\""));
		assertThat(contagens)
			.anyMatch(linha -> linha.contains("uri=\"/auditoria/jobs/{id}\"") && linha.contains("status=\"200\""));
		assertThat(contagens)
			.anyMatch(linha -> linha.contains("uri=\"/auditoria/jobs/{id}\"") && linha.contains("status=\"403\""));
		assertThat(metricas).doesNotContain(job.toString());
	}

	private static void assertEtapa(JsonNode etapas, UUID etapaId, @Nullable UUID resultado, @Nullable UUID simulacao,
			@Nullable UUID submissao) {
		JsonNode etapa = etapa(etapas, etapaId);
		assertCampo(etapa, "resultado_id", resultado);
		assertCampo(etapa, "simulacao_id", simulacao);
		assertCampo(etapa, "submissao_id", submissao);
	}

	private static void assertCampo(JsonNode etapa, String campo, @Nullable UUID esperado) {
		if (esperado == null) {
			assertThat(etapa.has(campo)).as("%s ausente em %s", campo, etapa).isFalse();
		}
		else {
			assertThat(etapa.path(campo).asString()).as("%s em %s", campo, etapa).isEqualTo(esperado.toString());
		}
	}

	private static JsonNode etapa(JsonNode etapas, UUID id) {
		return StreamSupport.stream(etapas.spliterator(), false)
			.filter(e -> e.path("id").asString().equals(id.toString()))
			.findFirst()
			.orElseThrow();
	}

	private static JsonNode item(JsonNode pagina, UUID id) {
		return etapa(pagina.path("itens"), id);
	}

	private static List<UUID> ids(JsonNode lista) {
		return StreamSupport.stream(lista.spliterator(), false)
			.map(item -> UUID.fromString(item.path("id").asString()))
			.toList();
	}

	private static UUID jobDeTexto(UUID usuario, String texto, Instant criadoEm) {
		UUID submissao = inserir("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em) VALUES (?, 'texto', ?, ?) RETURNING id
				""", usuario, texto, ts(criadoEm));
		return inserir("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, meta_venda, criado_em,
				    iniciado_em)
				VALUES ('aguardando_decisao_usuario', ?, ?, '{2025-11}', 600000, 28000000.00, ?, ?) RETURNING id
				""", usuario, submissao, ts(criadoEm), ts(criadoEm.plusSeconds(60)));
	}

	private static UUID jobDeFormulario(UUID usuario, @Nullable String nome, Instant criadoEm) {
		UUID submissao = inserir("""
				INSERT INTO submissoes (usuario_id, tipo, conteudo, criado_em)
				VALUES (?, 'formulario', ?::jsonb, ?) RETURNING id
				""", usuario,
				"{\"nucleo\":" + NUCLEO.replace("]}", "],\"percentual\":0.02}") + ",\"texto_livre\":null}",
				ts(criadoEm));
		return inserir("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, nome, criado_em)
				VALUES ('gerando_regra', ?, ?, '{2025-11}', 485000, ?, ?) RETURNING id
				""", usuario, submissao, nome == null ? null : nome.strip(), ts(criadoEm));
	}

	private static UUID jobReprocessado(UUID usuario, UUID origem, Instant criadoEm) {
		return inserir("""
				INSERT INTO jobs (status, usuario_id, job_origem_id, competencias, orcamento, criado_em)
				VALUES ('aguardando_confirmacao_parametros', ?, ?, '{2025-11}', 600000, ?) RETURNING id
				""", usuario, origem, ts(criadoEm));
	}

	/**
	 * Um job de texto que passou por todos os ramos do registro: extração, rodada cuja
	 * reextração falhou, rodada corrigida por voz, correção do código, sugestão de
	 * adaptação, busca da meta com duas candidatas, meta aceita e explicação reprovada.
	 */
	private static JobCompleto jobCompleto() {
		List<UUID> etapas = new ArrayList<>();
		UUID job = jobDeTexto(A, TEXTO_INICIAL, T0);
		UUID entradaInicial = Objects
			.requireNonNull(dono.queryForObject("SELECT submissao_id FROM jobs WHERE id = ?", UUID.class, job));
		UUID promptExtracao = prompt(job, "extracao_parametros", PROMPT_SECRETO, 1);
		UUID respostaExtracao = resposta(job, promptExtracao, 2);
		dono.update("""
				INSERT INTO extracoes_regras (id, job_id, submissao_id, resposta_id, representacao, rebaixamentos,
				    parametros, criado_em)
				VALUES (?, ?, ?, ?, ?::jsonb, '[]'::jsonb, '{}'::jsonb, ?)
				""", UUID.randomUUID(), job, entradaInicial, respostaExtracao,
				"{\"nucleo\":" + NUCLEO + ",\"especificacoes\":[]}", ts(minuto(2)));
		UUID extracaoInicial = trilha(etapas, job, "extracao_parametros", 2, null, promptExtracao, null, null, null,
				null, "{\"resumo\":\"Regra extraída.\"}");
		UUID versaoExtraida = inserir("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, parametros, hash, criada_em)
				VALUES (?, 1, 'extracao', ?::jsonb, '[]'::jsonb, '{"orcamento":600000}'::jsonb, ?, ?) RETURNING id
				""", job, NUCLEO, "1".repeat(64), ts(minuto(3)));
		trilha(etapas, job, "validacao_dominio", 3, versaoExtraida, null, null, null, null, null,
				"{\"resumo\":\"Percentual ausente.\"}");
		UUID correcaoRecusada = inserir("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em) VALUES (?, 'texto', 'Corrija', ?)
				RETURNING id
				""", A, ts(minuto(4)));
		UUID rodadaRecusada = inserir("""
				INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado, submissao_correcao_id,
				    criada_em, atualizada_em)
				VALUES (?, ?, '[{"elementos":["nucleo.percentual"],"motivo":"percentual ausente"}]'::jsonb,
				    'reextracao_falhou', ?, ?, ?) RETURNING id
				""", job, versaoExtraida, correcaoRecusada, ts(minuto(3)), ts(minuto(5)));
		UUID correcaoAceita = inserir("""
				INSERT INTO submissoes (usuario_id, tipo, binario, formato, transcricao, transcrito_em, criado_em)
				VALUES (?, 'voz', ?, 'ogg', ?, ?, ?) RETURNING id
				""", A, "AUDIO-BINARIO".getBytes(StandardCharsets.UTF_8), TRANSCRICAO_SECRETA, ts(minuto(6)),
				ts(minuto(5)));
		UUID promptReextracao = prompt(job, "extracao_parametros", "Reextraia a regra corrigida.", 6);
		resposta(job, promptReextracao, 7);
		UUID reextracao = trilha(etapas, job, "extracao_parametros", 7, versaoExtraida, promptReextracao, null, null,
				null, null, "{\"resumo\":\"Correção recebida e reextraída.\"}");
		UUID versaoCorrigida = inserir("""
				INSERT INTO regras (job_id, versao, origem, regra_origem_id, representacao, nucleo, especificacoes,
				    parametros, hash, criada_em)
				VALUES (?, 2, 'correcao', ?, ?::jsonb, ?::jsonb, '[]'::jsonb, '{}'::jsonb, ?, ?) RETURNING id
				""", job, versaoExtraida,
				"{\"nucleo\":" + NUCLEO_CORRIGIDO + ",\"especificacoes\":[],\"extensao_da_raiz\":\"preservada\"}",
				NUCLEO_CORRIGIDO, "2".repeat(64), ts(minuto(7)));
		dono.update("""
				INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado, submissao_correcao_id,
				    regra_resultante_id, rodada_anterior_id, criada_em, atualizada_em)
				VALUES (?, ?, '[{"elementos":["nucleo.percentual"],"motivo":"percentual ausente"}]'::jsonb,
				    'corrigida', ?, ?, ?, ?, ?)
				""", job, versaoExtraida, correcaoAceita, versaoCorrigida, rodadaRecusada, ts(minuto(5)),
				ts(minuto(7)));

		UUID promptCodigo = prompt(job, "geracao_codigo", "Gere o código.", 8);
		resposta(job, promptCodigo, 8);
		UUID primeiroCodigo = codigo(job, versaoCorrigida, promptCodigo, CODIGO_SECRETO, 8);
		UUID simulacaoDoPrimeiroCodigo = simulacao(job, versaoCorrigida, primeiroCodigo, 8);
		UUID geracao = trilha(etapas, job, "geracao_codigo", 8, versaoCorrigida, promptCodigo, primeiroCodigo,
				simulacaoDoPrimeiroCodigo, null, null, "{\"resumo\":\"Código gerado.\",\"modo_geracao\":\"gerado\"}");
		UUID resultadoComErro = inserir(
				"""
						INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, assercoes, diagnostico, criado_em)
						VALUES (?, ?, 'erro_codigo', '[]'::jsonb, '{"causa":"excecao","falha":{"tipo":"KeyError","mensagem":"vlr","traceback":"linha 3"}}'::jsonb, ?) RETURNING id
						""",
				job, primeiroCodigo, ts(minuto(9)));
		vincular(simulacaoDoPrimeiroCodigo, resultadoComErro);

		UUID promptCorrecao = prompt(job, "geracao_codigo", "Corrija o código.", 10);
		resposta(job, promptCorrecao, 10);
		UUID codigoCorrigido = codigo(job, versaoCorrigida, promptCorrecao, "def aplicar_regra(): pass", 10);
		UUID simulacaoDoCodigoCorrigido = simulacao(job, versaoCorrigida, codigoCorrigido, 10);
		UUID correcaoDoCodigo = trilha(etapas, job, "geracao_codigo", 10, versaoCorrigida, promptCorrecao,
				codigoCorrigido, simulacaoDoCodigoCorrigido, resultadoComErro, null,
				"{\"resumo\":\"Código corrigido.\",\"modo_geracao\":\"correcao\"}");
		UUID resultadoInviavel = resultado(job, codigoCorrigido, "simulacao", "inviavel", "28000000.00", 11);
		vincular(simulacaoDoCodigoCorrigido, resultadoInviavel);
		UUID decisaoInviavel = trilha(etapas, job, "decisao", 12, versaoCorrigida, null, null, null, resultadoInviavel,
				null, "{\"resumo\":\"Fora do orçamento.\"}");
		UUID sugestao = trilha(etapas, job, "sugestao_adaptacao", 13, versaoCorrigida, null, null, null,
				resultadoInviavel, null, "{\"resumo\":\"Taxa menor proposta.\",\"motivo_sugestao\":\"proposta\"}");

		UUID versaoSugerida = inserir("""
				INSERT INTO regras (job_id, versao, origem, regra_origem_id, nucleo, especificacoes, hash, tentativa,
				    criada_em)
				VALUES (?, 3, 'sugestao_adaptacao', ?, ?::jsonb, '[]'::jsonb, ?, 1, ?) RETURNING id
				""", job, versaoCorrigida, NUCLEO_SUGERIDO, "3".repeat(64), ts(minuto(13)));
		UUID promptDerivado = prompt(job, "geracao_codigo", "Derive o código.", 14);
		resposta(job, promptDerivado, 14);
		UUID codigoDerivado = codigo(job, versaoSugerida, promptDerivado, "def aplicar_regra(): return 1", 14);
		UUID simulacaoDaSugestao = simulacao(job, versaoSugerida, codigoDerivado, 14);
		UUID geracaoDerivada = trilha(etapas, job, "geracao_codigo", 14, versaoSugerida, promptDerivado, codigoDerivado,
				simulacaoDaSugestao, resultadoInviavel, null,
				"{\"resumo\":\"Código derivado.\",\"modo_geracao\":\"derivado\"}");
		UUID resultadoViavel = resultado(job, codigoDerivado, "simulacao", "viavel", "28000000.00", 15);
		vincular(simulacaoDaSugestao, resultadoViavel);
		UUID decisaoViavel = trilha(etapas, job, "decisao", 16, versaoSugerida, null, null, null, resultadoViavel, null,
				"{\"resumo\":\"Dentro do orçamento.\",\"encaminhamento\":\"busca_meta\"}");
		UUID candidataVencedora = resultado(job, codigoDerivado, "busca_meta", "viavel", "28500000", 17);
		UUID candidataInviavel = resultado(job, codigoDerivado, "busca_meta", "inviavel", "29000000", 18);
		UUID fimDaBusca = trilha(etapas, job, "decisao", 19, versaoSugerida, null, null, null, candidataVencedora, null,
				"{\"resumo\":\"Meta maior encontrada.\",\"desfecho_busca\":\"encontrada\",\"candidatas_simuladas\":2}");
		dono.update("""
				INSERT INTO sugestoes_meta_venda (job_id, regra_id, resultado_id, resultado_anterior_id, criada_em,
				    aceita_em)
				VALUES (?, ?, ?, ?, ?, ?)
				""", job, versaoSugerida, candidataVencedora, resultadoViavel, ts(minuto(19)), ts(minuto(21)));
		vincular(simulacaoDaSugestao, candidataVencedora);
		dono.update("INSERT INTO job_acoes (job_id, acao, executado_em) VALUES (?, 'aceitar_meta', ?)", job,
				ts(minuto(21)));

		UUID explicacaoId = inserir("""
				INSERT INTO explicacoes (resultado_id, texto, aderencia_conferida, criado_em)
				VALUES (?, 'A comissão de R$ 1 cabe no orçamento.', false, ?) RETURNING id
				""", resultadoViavel, ts(minuto(20)));
		UUID explicacao = trilha(etapas, job, "explicacao", 20, versaoSugerida, null, null, null, resultadoViavel,
				explicacaoId, "{\"resumo\":\"Narrativa reprovada.\",\"desfecho_explicacao\":\"reprovada\"}");

		dono.update("""
				INSERT INTO job_transicoes (job_id, status_anterior, status_novo, ocorrido_em, ator, motivo)
				VALUES (?, NULL, 'gerando_regra', ?, 'usuario', NULL),
				       (?, 'gerando_regra', 'simulando', ?, 'evento', NULL),
				       (?, 'simulando', 'aguardando_decisao_usuario', ?, 'evento', NULL)
				""", job, ts(T0), job, ts(minuto(8)), job, ts(minuto(12)));
		return new JobCompleto(job, entradaInicial, correcaoRecusada, correcaoAceita, versaoExtraida, versaoCorrigida,
				versaoSugerida, List.copyOf(etapas), extracaoInicial, reextracao, geracao, correcaoDoCodigo,
				decisaoInviavel, sugestao, geracaoDerivada, decisaoViavel, fimDaBusca, explicacao, explicacaoId,
				simulacaoDoPrimeiroCodigo, simulacaoDoCodigoCorrigido, simulacaoDaSugestao, resultadoComErro,
				resultadoInviavel, resultadoViavel, candidataVencedora, candidataInviavel);
	}

	private static void vincular(UUID simulacao, UUID resultado) {
		dono.update("UPDATE simulacoes SET resultado_id = ? WHERE id = ?", resultado, simulacao);
	}

	private static UUID prompt(UUID job, String no, String conteudo, int minuto) {
		return inserir("""
				INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em) VALUES (?, ?, ?, ?::jsonb, ?) RETURNING id
				""", job, no, conteudo, MODELO, ts(minuto(minuto)));
	}

	private static UUID resposta(UUID job, UUID prompt, int minuto) {
		return inserir("""
				INSERT INTO respostas_modelo (job_id, prompt_id, conteudo, consumo_tokens, criado_em)
				VALUES (?, ?, 'resposta do modelo', '{"tokens_in":3120,"tokens_out":480}'::jsonb, ?) RETURNING id
				""", job, prompt, ts(minuto(minuto)));
	}

	private static UUID codigo(UUID job, UUID regra, UUID prompt, String fonte, int minuto) {
		return inserir("""
				INSERT INTO codigos_gerados (job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES (?, ?, 'python', ?, ?, ?) RETURNING id
				""", job, regra, fonte, prompt, ts(minuto(minuto)));
	}

	private static UUID simulacao(UUID job, UUID regra, UUID codigo, int minuto) {
		return inserir("""
				INSERT INTO simulacoes (job_id, regra_id, codigo_gerado_id, criado_em) VALUES (?, ?, ?, ?) RETURNING id
				""", job, regra, codigo, ts(minuto(minuto)));
	}

	private static UUID resultado(UUID job, UUID codigo, String proposito, String veredito, String meta, int minuto) {
		return inserir("""
				INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, proposito, veredito, meta_venda,
				    totais, assercoes, decomposicao, linhas, criado_em)
				VALUES (?, ?, 'sucesso', ?, ?, ?::numeric, ?::jsonb, ?::jsonb, ?::jsonb, ?::jsonb, ?) RETURNING id
				""", job, codigo, proposito, veredito, meta, TOTAIS, ASSERCOES, DECOMPOSICAO, LINHAS_SECRETAS,
				ts(minuto(minuto)));
	}

	private static UUID trilha(List<UUID> etapas, UUID job, String no, int minuto, @Nullable UUID regra,
			@Nullable UUID prompt, @Nullable UUID codigo, @Nullable UUID simulacao, @Nullable UUID resultado,
			@Nullable UUID explicacao, String conclusao) {
		UUID id = inserir("""
				INSERT INTO trilhas_auditoria (evento_id, job_id, simulacao_id, no, concluido_em, regra_id, conclusao,
				    prompt_id, codigo_gerado_id, explicacao_id, resultado_id)
				VALUES (?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?, ?, ?) RETURNING id
				""", UUID.randomUUID(), job, simulacao, no, ts(minuto(minuto)), regra, conclusao, prompt, codigo,
				explicacao, resultado);
		etapas.add(id);
		return id;
	}

	private static UUID inserir(String sql, @Nullable Object... parametros) {
		return Objects.requireNonNull(dono.queryForObject(sql, UUID.class, parametros));
	}

	private static Instant minuto(int minutos) {
		return T0.plusSeconds(60L * minutos);
	}

	private static Timestamp ts(Instant instante) {
		return Timestamp.from(instante);
	}

	private static String snapshotNegocio() {
		return Objects.requireNonNull(dono.queryForObject("""
				SELECT jsonb_build_object(
				  'jobs', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM jobs t),
				  'submissoes', (SELECT jsonb_agg(to_jsonb(t) - 'binario' ORDER BY id) FROM submissoes t),
				  'regras', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM regras t),
				  'trilhas', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM trilhas_auditoria t),
				  'transicoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM job_transicoes t),
				  'acoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM job_acoes t),
				  'rodadas', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM rodadas_correcao t),
				  'simulacoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM simulacoes t),
				  'sugestoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY regra_id) FROM sugestoes_meta_venda t),
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
		return token("subject-auditor", "auditoria", List.of("default-roles-synapse", "auditor"));
	}

	private static String rh(String sub) throws Exception {
		return token(sub, sub.equals("subject-a") ? "a" : "b", List.of("profissional-rh"));
	}

	private static String token(String sub, String login, List<String> papeis) throws Exception {
		JWTClaimsSet claims = new JWTClaimsSet.Builder().subject(sub)
			.issuer(ISSUER)
			.issueTime(Date.from(Instant.now().minusSeconds(60)))
			.expirationTime(Date.from(Instant.now().plusSeconds(300)))
			.claim("preferred_username", login)
			.claim("realm_access", Map.of("roles", papeis))
			.build();
		SignedJWT jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID("teste").build(), claims);
		jwt.sign(new RSASSASigner(chave));
		return jwt.serialize();
	}

	/** Os ids do job semeado, para as asserções localizarem cada linha. */
	private record JobCompleto(UUID id, UUID entradaInicial, UUID correcaoRecusada, UUID correcaoAceita,
			UUID versaoExtraida, UUID versaoCorrigida, UUID versaoSugerida, List<UUID> etapas, UUID extracaoInicial,
			UUID reextracao, UUID geracao, UUID correcaoDoCodigo, UUID decisaoInviavel, UUID sugestao,
			UUID geracaoDerivada, UUID decisaoViavel, UUID fimDaBusca, UUID explicacao, UUID explicacaoId,
			UUID simulacaoDoPrimeiroCodigo, UUID simulacaoDoCodigoCorrigido, UUID simulacaoDaSugestao,
			UUID resultadoComErro, UUID resultadoInviavel, UUID resultadoViavel, UUID candidataVencedora,
			UUID candidataInviavel) {
	}

}
