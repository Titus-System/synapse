package synapse.api.auditoria;

import java.net.InetSocketAddress;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.StreamSupport;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
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
import org.slf4j.LoggerFactory;
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

@EnabledIf("dockerIsAvailable")
class EventosAuditoriaPersistenciaTests {

	private static final UUID A = UUID.fromString("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");

	private static final UUID B = UUID.fromString("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");

	private static final UUID AUDITOR = UUID.fromString("cccccccc-cccc-4ccc-8ccc-cccccccccccc");

	private static final String ISSUER = "https://emissor-de-teste.invalid/realms/synapse";

	private static final Instant OUTUBRO = Instant.parse("2026-11-01T02:30:00Z");

	private static final Instant NOVEMBRO = Instant.parse("2026-11-01T03:00:00Z");

	private static final String NUCLEO_ANTIGO = """
			{"loja":["13"],"marca":["10"],"cargo":["100"]}""";

	private static final String NUCLEO_ATUAL = """
			{"loja":["21","22"],"marca":["20"],"cargo":["200","300"]}""";

	private static final String NOME = "Plano 10%_! Especial";

	private static final String PROMPT_PRIVADO = "PROMPT-PRIVADO-DO-TESTE";

	private static final String RESPOSTA_PRIVADA = "RESPOSTA-PRIVADA-DO-TESTE";

	private static final String CODIGO_PRIVADO = "def aplicar(): return 'CODIGO-PRIVADO-DO-TESTE'";

	private static final String TEXTO_CORRECAO = "CORRECAO-PRIVADA-DO-TESTE";

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
		chave = new RSAKeyGenerator(2048).keyID("teste-eventos").generate();
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
				       (?, 'rh.b', 'RH B', 'profissional_rh', 'subject-b', now()),
				       (?, 'auditoria', 'Auditor', 'auditor', 'subject-auditor', now())
				""", A, B, AUDITOR);
	}

	@ParameterizedTest
	@ValueSource(strings = { "/auditoria/eventos", "/auditoria/eventos/filtros" })
	void cadeiaRealExigeSessaoEPermiteSomenteAuditor(String rota) throws Exception {
		assertThat(chamar(rota, "").statusCode()).isEqualTo(401);
		assertThat(chamar(rota, "token-invalido").statusCode()).isEqualTo(401);
		HttpResponse<String> rh = chamar(rota, token("subject-a", "rh.a", "profissional-rh"));
		assertThat(rh.statusCode()).isEqualTo(403);
		assertThat(JSON.readTree(rh.body()).path("codigo").asString()).isEqualTo("sem_permissao");
		HttpResponse<String> auditor = chamar(rota, auditor());
		assertThat(auditor.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp(
				rota.endsWith("filtros") ? "FiltrosEventosAuditoria" : "PaginaEventosAuditoria", auditor.body());
	}

	@Test
	void unificaTodasAsFontesSemCandidatasNemArtefatosPrivados() throws Exception {
		Historico historico = historicoCompleto();
		String antes = snapshotNegocio();
		HttpResponse<String> resposta = chamar("/auditoria/eventos?tamanho=100", auditor());
		assertThat(resposta.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("PaginaEventosAuditoria", resposta.body());
		assertThat(snapshotNegocio()).isEqualTo(antes);
		assertThat(resposta.body()).doesNotContain(PROMPT_PRIVADO, RESPOSTA_PRIVADA, CODIGO_PRIVADO, TEXTO_CORRECAO,
				"MATRIC-PRIVADA", "AUDIO-PRIVADO", "\"binario\"", "\"linhas\"", "\"fonte\"", "\"prompt\"");
		JsonNode pagina = JSON.readTree(resposta.body());
		assertContadores(pagina, 14, 2, 2, 1);
		assertThat(valores(pagina.path("itens"), "tipo")).contains("entrada", "rodada_correcao", "versao_regra",
				"codigo_gerado", "resultado_simulacao", "sugestao_meta_criada", "sugestao_meta_aceita", "acao_usuario",
				"job_erro");
		assertThat(valores(pagina.path("itens"), "origem_id")).doesNotContain(historico.candidataErro().toString(),
				historico.candidataSucesso().toString());
		JsonNode erro = evento(pagina, "resultado_simulacao", historico.resultadoErro());
		assertThat(erro.path("status").asString()).isEqualTo("erro_codigo");
		assertThat(erro.path("autor").asString()).isEqualTo("sistema");
		assertThat(evento(pagina, "entrada", historico.correcao()).path("finalidade").asString()).isEqualTo("correcao");
		assertThat(evento(pagina, "entrada", historico.correcao()).path("tipo_entrada").asString()).isEqualTo("voz");
		assertThat(evento(pagina, "versao_regra", historico.ultimaRegra()).path("versao").asInt()).isEqualTo(2);
		assertThat(evento(pagina, "versao_regra", historico.ultimaRegra()).path("origem_versao").asString())
			.isEqualTo("correcao");
		assertThat(evento(pagina, "sugestao_meta_aceita", historico.ultimaRegra()).path("autor").asString())
			.isEqualTo("usuario");
		assertThat(evento(pagina, "acao_usuario", historico.acao()).path("acao").asString()).isEqualTo("aceitar_meta");
		assertThat(evento(pagina, "job_erro", historico.erroJob()).path("job").path("status").asString())
			.isEqualTo("erro");
	}

	@Test
	void loginFiltraEventosEContadoresDeTodasAsPaginas() throws Exception {
		historicoCompleto();
		JsonNode deA = consultar("usuario=rh.a&tamanho=2");
		assertContadores(deA, 13, 1, 1, 1);
		assertThat(deA.path("itens").size()).isEqualTo(2);
		assertThat(valores(deA.path("itens"), "usuario_login")).containsOnly("rh.a");
		JsonNode deB = consultar("usuario=rh.b");
		assertContadores(deB, 1, 1, 1, 0);
		assertThat(valores(deB.path("itens"), "usuario_login")).containsExactly("rh.b");
		JsonNode alemDaUltima = consultar("usuario=rh.a&pagina=999&tamanho=2");
		assertThat(alemDaUltima.path("itens").isEmpty()).isTrue();
		assertContadores(alemDaUltima, 13, 1, 1, 1);
		assertContadores(consultar("usuario=inexistente"), 0, 0, 0, 0);
	}

	@Test
	void mesUsaBrasiliaNosDoisLadosDaViradaDoMes() throws Exception {
		UUID outubro = job(A, null, "Evento de outubro", OUTUBRO);
		UUID novembro = job(B, null, "Evento de novembro", NOVEMBRO);
		assertThat(jobs(consultar("mes=2026-10"))).containsExactly(outubro);
		assertThat(jobs(consultar("mes=2026-11"))).containsExactly(novembro);
		assertThat(consultar("mes=2026-09").path("itens").isEmpty()).isTrue();
		JsonNode filtros = filtros();
		assertThat(textos(filtros.path("meses"))).containsExactly("2026-10", "2026-11");
	}

	@Test
	void dimensoesUsamMaiorVersaoECombinamTodosOsFiltrosComE() throws Exception {
		Historico historico = historicoCompleto();
		dono.update("UPDATE regras SET criada_em = ? WHERE id = ?", ts(OUTUBRO.minusSeconds(60)),
				historico.ultimaRegra());
		assertContadores(consultar("loja=13"), 0, 0, 0, 0);
		assertContadores(consultar("marca=10"), 0, 0, 0, 0);
		assertContadores(consultar("cargo=100"), 0, 0, 0, 0);
		JsonNode combinado = consultar("usuario=rh.a&mes=2026-10&loja=22&marca=20&cargo=300&regra=" + historico.jobA());
		assertContadores(combinado, 13, 1, 1, 1);
		assertThat(jobs(combinado)).containsOnly(historico.jobA());
		assertThat(valores(combinado.path("itens"), "loja")).containsOnly("22");
		assertThat(valores(combinado.path("itens"), "marca")).containsOnly("20");
		assertThat(valores(combinado.path("itens"), "cargo")).containsOnly("300");
		assertContadores(consultar("usuario=rh.b&loja=22"), 0, 0, 0, 0);
		assertContadores(consultar("loja=22&marca=99"), 0, 0, 0, 0);
		assertContadores(consultar("loja=22&mes=2026-11"), 0, 0, 0, 0);
		JsonNode opcoes = filtros();
		assertThat(textos(opcoes.path("usuarios"))).containsExactly("rh.a", "rh.b");
		assertThat(textos(opcoes.path("lojas"))).containsExactly("21", "22");
		assertThat(textos(opcoes.path("marcas"))).containsExactly("20");
		assertThat(textos(opcoes.path("cargos"))).containsExactly("200", "300");
	}

	@Test
	void regraUsaUuidExatoOuNomeSemCaixaEEscapaCuringas() throws Exception {
		UUID nomeado = job(A, NOME, "Nome que não deve prevalecer", OUTUBRO);
		job(B, "Plano 10abc Especial " + nomeado, "Outro nome", OUTUBRO);
		for (String texto : List.of("pLaNo 10%_! eSpEcIaL", "%", "_", "!", "%_!")) {
			assertThat(jobs(consultar("regra=" + codificar(texto)))).as(texto).containsExactly(nomeado);
		}
		assertThat(jobs(consultar("regra=" + nomeado.toString().toUpperCase(java.util.Locale.ROOT))))
			.containsExactly(nomeado);
		assertContadores(consultar("regra=" + UUID.randomUUID()), 0, 0, 0, 0);
		assertContadores(consultar("regra=" + codificar("' OR '1'='1")), 0, 0, 0, 0);
		UUID barra = job(A, "Nome \\%_ literal", "Texto", OUTUBRO);
		assertThat(jobs(consultar("regra=" + codificar("\\%_")))).containsExactly(barra);
		UUID uuidAbreviado = job(A, "1-1-1-1-1", "Texto", OUTUBRO);
		assertThat(jobs(consultar("regra=1-1-1-1-1"))).containsExactly(uuidAbreviado);
	}

	@Test
	void nomeResolvidoSegueTextoInicialInclusiveCadeiaDeReprocessamento() throws Exception {
		UUID origem = job(A, null, " \tComissão  de\n\tvendas na loja 13   ", OUTUBRO);
		UUID intermediario = reprocessar(origem, "Nome manual do intermediário");
		UUID finalDaCadeia = reprocessar(intermediario, null);
		dono.update("INSERT INTO job_acoes (job_id, acao, executado_em) VALUES (?, 'salvar', ?)", finalDaCadeia,
				ts(OUTUBRO));
		JsonNode pagina = consultar("regra=" + codificar("COMISSÃO DE VENDAS"));
		assertThat(jobs(pagina)).containsExactlyInAnyOrder(origem, finalDaCadeia);
		for (JsonNode item : pagina.path("itens")) {
			assertThat(item.path("job").path("nome").asString()).isEqualTo("Comissão de vendas na loja 13");
		}
		assertContadores(consultar("regra=" + codificar("Nome manual do intermediário")), 0, 0, 0, 0);
	}

	@Test
	void paginacaoPercorreCadaEventoUmaVezMesmoComDesempateDeSugestao() throws Exception {
		historicoCompleto();
		JsonNode todos = consultar("tamanho=100");
		List<String> esperado = identidades(todos.path("itens"));
		List<String> percorridos = new ArrayList<>();
		for (int pagina = 0; pagina < 14; pagina++) {
			JsonNode resposta = consultar("tamanho=1&pagina=" + pagina);
			assertContadores(resposta, 14, 2, 2, 1);
			percorridos.addAll(identidades(resposta.path("itens")));
		}
		assertThat(percorridos).containsExactlyElementsOf(esperado);
		assertThat(new HashSet<>(percorridos)).hasSize(14);
		Instant instanteAnterior = Instant.MAX;
		String origemAnterior = "";
		for (JsonNode item : todos.path("itens")) {
			Instant instante = Instant.parse(item.path("instante").asString());
			String origem = item.path("origem_id").asString();
			assertThat(instante).isBeforeOrEqualTo(instanteAnterior);
			if (instante.equals(instanteAnterior)) {
				assertThat(origem.compareTo(origemAnterior)).isLessThanOrEqualTo(0);
			}
			instanteAnterior = instante;
			origemAnterior = origem;
		}
	}

	@Test
	void opcoesIncluemDonosDeJobsSemEventosENaoIncluemUsuariosSemJobs() throws Exception {
		UUID origem = job(A, null, "Entrada", OUTUBRO);
		dono.update("""
				INSERT INTO jobs (usuario_id, job_origem_id, status, competencias, criado_em)
				VALUES (?, ?, 'aguardando_confirmacao_parametros', '{2026-10}', ?)
				""", B, origem, ts(OUTUBRO));
		JsonNode resposta = filtros();
		assertThat(textos(resposta.path("usuarios"))).containsExactly("rh.a", "rh.b");
		assertThat(textos(resposta.path("lojas"))).isEmpty();
		assertThat(textos(resposta.path("marcas"))).isEmpty();
		assertThat(textos(resposta.path("cargos"))).isEmpty();
	}

	@Test
	void logsDaCadeiaRealTrazemAuditorSemFiltroLivreOuConteudo() throws Exception {
		historicoCompleto();
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(EventosAuditoriaController.class)) {
			assertThat(chamar("/auditoria/eventos?regra=" + codificar(NOME) + "&tamanho=2", auditor()).statusCode())
				.isEqualTo(200);
			assertThat(chamar("/auditoria/eventos/filtros", auditor()).statusCode()).isEqualTo(200);
			assertThat(chamar("/auditoria/eventos?regra=" + codificar(NOME) + "&mes=invalido", auditor()).statusCode())
				.isEqualTo(400);
			eventos = captura.eventos();
		}
		assertThat(eventos).hasSize(3);
		for (ILoggingEvent evento : eventos) {
			String serializado = CapturaDeLog.emJson(evento);
			ContratoDeEvento.validarLog(serializado);
			assertThat(serializado).doesNotContain(NOME, PROMPT_PRIVADO, RESPOSTA_PRIVADA, CODIGO_PRIVADO,
					TEXTO_CORRECAO, "MATRIC-PRIVADA", "subject-auditor");
			assertThat(JSON.readTree(serializado).path("user_id").asString()).isEqualTo(AUDITOR.toString());
		}
		assertThat(JSON.readTree(CapturaDeLog.emJson(eventos.getFirst())).path("level").asString()).isEqualTo("INFO");
		assertThat(JSON.readTree(CapturaDeLog.emJson(eventos.getLast())).path("level").asString()).isEqualTo("WARN");
	}

	@Test
	void metricsExpoeVolumeFalhasEDuracaoDasDuasRotas() throws Exception {
		job(A, NOME, "Entrada", OUTUBRO);
		for (String rota : List.of("/auditoria/eventos", "/auditoria/eventos/filtros")) {
			assertThat(chamar(rota, auditor()).statusCode()).isEqualTo(200);
			assertThat(chamar(rota, token("subject-a", "rh.a", "profissional-rh")).statusCode()).isEqualTo(403);
		}
		assertThat(chamar("/auditoria/eventos?pagina=-1", auditor()).statusCode()).isEqualTo(400);
		String metricas = chamar("/metrics", "").body();
		List<String> contagens = metricas.lines()
			.filter(linha -> linha.startsWith("http_server_requests_seconds_count{"))
			.toList();
		List<String> duracoes = metricas.lines()
			.filter(linha -> linha.startsWith("http_server_requests_seconds_sum{"))
			.toList();
		for (String rota : List.of("/auditoria/eventos", "/auditoria/eventos/filtros")) {
			for (String status : List.of("200", "403")) {
				assertThat(contagens).anyMatch(
						linha -> linha.contains("uri=\"" + rota + "\"") && linha.contains("status=\"" + status + "\"")
								&& linha.contains("method=\"GET\"") && valorMetrica(linha) >= 1);
			}
			assertThat(duracoes).anyMatch(linha -> linha.contains("uri=\"" + rota + "\"") && valorMetrica(linha) > 0);
		}
		assertThat(contagens)
			.anyMatch(linha -> linha.contains("uri=\"/auditoria/eventos\"") && linha.contains("status=\"400\""));
		assertThat(metricas).doesNotContain(A.toString(), AUDITOR.toString(), NOME, "subject-auditor");
	}

	@Test
	void formularioLegadoMantemEventoENomeNuloSemInventarTipoForaDoContrato() throws Exception {
		UUID entrada = inserir("""
				INSERT INTO submissoes (usuario_id, tipo, conteudo, criado_em)
				VALUES (?, 'formulario', '{"nucleo":{"loja":["13"]}}'::jsonb, ?) RETURNING id
				""", A, ts(OUTUBRO));
		inserir("""
				INSERT INTO jobs (usuario_id, submissao_id, status, competencias, criado_em)
				VALUES (?, ?, 'gerando_regra', '{2026-10}', ?) RETURNING id
				""", A, entrada, ts(OUTUBRO));
		JsonNode pagina = consultar("tamanho=20");
		assertContadores(pagina, 1, 1, 1, 0);
		JsonNode item = evento(pagina, "entrada", entrada);
		assertThat(item.has("tipo_entrada")).isFalse();
		assertThat(item.path("job").has("nome")).isTrue();
		assertThat(item.path("job").path("nome").isNull()).isTrue();
	}

	@Test
	void buscaDaMetaSemSolucaoNaoViraSugestaoCriada() throws Exception {
		UUID job = job(A, null, "Texto", OUTUBRO);
		UUID regra = versao(job, 1, "extracao", NUCLEO_ATUAL, null, OUTUBRO);
		dono.update("""
				INSERT INTO sugestoes_meta_venda (job_id, regra_id, motivo_sem_solucao, criada_em)
				VALUES (?, ?, 'intervalo_esgotado', ?)
				""", job, regra, ts(Instant.parse("2026-12-10T12:00:00Z")));
		JsonNode pagina = consultar("tamanho=100");
		assertContadores(pagina, 2, 1, 1, 0);
		assertThat(valores(pagina.path("itens"), "tipo")).containsExactlyInAnyOrder("entrada", "versao_regra");
		assertThat(textos(filtros().path("meses"))).containsExactly("2026-10");
	}

	@Test
	void mesExclusivoDeCandidataNaoViraOpcao() throws Exception {
		UUID job = job(A, null, "Texto", OUTUBRO);
		UUID regra = versao(job, 1, "extracao", NUCLEO_ATUAL, null, OUTUBRO);
		UUID codigo = codigo(job, regra, OUTUBRO);
		resultado(job, codigo, "erro_codigo", "busca_meta", Instant.parse("2026-12-10T12:00:00Z"));
		assertThat(textos(filtros().path("meses"))).containsExactly("2026-10");
		assertContadores(consultar("mes=2026-12"), 0, 0, 0, 0);
	}

	@ParameterizedTest
	@ValueSource(strings = { "DEBUG", "TRACE" })
	void diagnosticoDoFrameworkNaoRegistraFiltroLivreNemTokensNaCadeiaHttp(String nivel) throws Exception {
		String regraPrivada = "TEXTO-LIVRE-PRIVADO-NA-URL";
		String tokenAuditor = auditor();
		String tokenRh = token("subject-a", "rh.a", "profissional-rh");
		Logger raiz = (Logger) LoggerFactory.getLogger(org.slf4j.Logger.ROOT_LOGGER_NAME);
		Level nivelAnterior = raiz.getLevel();
		List<ILoggingEvent> eventos;
		try (CapturaDeLog captura = new CapturaDeLog(org.slf4j.Logger.ROOT_LOGGER_NAME)) {
			raiz.setLevel(Level.toLevel(nivel));
			assertThat(chamar("/auditoria/eventos?regra=" + regraPrivada, tokenAuditor).statusCode()).isEqualTo(200);
			assertThat(chamar("/auditoria/eventos?regra=" + regraPrivada, tokenRh).statusCode()).isEqualTo(403);
			assertThat(chamar("/auditoria/eventos?regra=" + regraPrivada, "").statusCode()).isEqualTo(401);
			assertThat(
					chamar("/auditoria/eventos?regra=" + regraPrivada + "&pagina=invalida", tokenAuditor).statusCode())
				.isEqualTo(400);
			eventos = captura.eventos();
		}
		finally {
			raiz.setLevel(nivelAnterior);
		}
		assertThat(eventos).isNotEmpty();
		for (ILoggingEvent evento : eventos) {
			assertThat(CapturaDeLog.emJson(evento)).doesNotContain(regraPrivada, tokenAuditor, tokenRh);
		}
		List<ILoggingEvent> consultas = eventos.stream()
			.filter(evento -> evento.getLoggerName().equals(EventosAuditoriaController.class.getName()))
			.toList();
		assertThat(consultas).hasSize(2);
		for (ILoggingEvent consulta : consultas) {
			String serializado = CapturaDeLog.emJson(consulta);
			ContratoDeEvento.validarLog(serializado);
			assertThat(JSON.readTree(serializado).path("user_id").asString()).isEqualTo(AUDITOR.toString());
		}
	}

	private static Historico historicoCompleto() {
		UUID jobA = job(A, NOME, "Texto inicial privado", OUTUBRO);
		UUID jobB = job(B, null, "Evento de novembro", NOVEMBRO);
		dono.update("UPDATE jobs SET status = 'erro' WHERE id = ?", jobA);
		UUID primeira = versao(jobA, 1, "extracao", NUCLEO_ANTIGO, null, OUTUBRO.plusSeconds(10));
		UUID ultima = versao(jobA, 2, "correcao", NUCLEO_ATUAL, primeira, OUTUBRO.plusSeconds(40));
		UUID correcao = inserir("""
				INSERT INTO submissoes (usuario_id, tipo, binario, formato, transcricao, criado_em)
				VALUES (?, 'voz', ?, 'ogg', ?, ?) RETURNING id
				""", A, "AUDIO-PRIVADO".getBytes(StandardCharsets.UTF_8), TEXTO_CORRECAO, ts(OUTUBRO.plusSeconds(30)));
		dono.update("""
				INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado, submissao_correcao_id,
				    regra_resultante_id, criada_em, atualizada_em)
				VALUES (?, ?, '[]'::jsonb, 'corrigida', ?, ?, ?, ?)
				""", jobA, primeira, correcao, ultima, ts(OUTUBRO.plusSeconds(20)), ts(OUTUBRO.plusSeconds(40)));
		UUID codigoErro = codigo(jobA, ultima, OUTUBRO.plusSeconds(50));
		UUID erro = resultado(jobA, codigoErro, "erro_codigo", "simulacao", OUTUBRO.plusSeconds(60));
		UUID codigoSucesso = codigo(jobA, ultima, OUTUBRO.plusSeconds(70));
		UUID sucesso = resultado(jobA, codigoSucesso, "sucesso", "simulacao", OUTUBRO.plusSeconds(80));
		UUID candidataErro = resultado(jobA, codigoSucesso, "erro_codigo", "busca_meta", OUTUBRO.plusSeconds(90));
		UUID candidataSucesso = resultado(jobA, codigoSucesso, "sucesso", "busca_meta", OUTUBRO.plusSeconds(100));
		dono.update("""
				INSERT INTO simulacoes (job_id, regra_id, codigo_gerado_id, resultado_id, criado_em)
				VALUES (?, ?, ?, ?, ?)
				""", jobA, ultima, codigoSucesso, candidataSucesso, ts(OUTUBRO.plusSeconds(70)));
		dono.update(
				"""
						INSERT INTO sugestoes_meta_venda (job_id, regra_id, resultado_id, resultado_anterior_id, criada_em, aceita_em)
						VALUES (?, ?, ?, ?, ?, ?)
						""",
				jobA, ultima, candidataSucesso, sucesso, ts(OUTUBRO.plusSeconds(110)), ts(OUTUBRO.plusSeconds(110)));
		UUID acao = inserir(
				"INSERT INTO job_acoes (job_id, acao, executado_em) VALUES (?, 'aceitar_meta', ?) RETURNING id", jobA,
				ts(OUTUBRO.plusSeconds(110)));
		UUID erroJob = inserir("""
				INSERT INTO job_transicoes (job_id, status_anterior, status_novo, ocorrido_em, ator)
				VALUES (?, 'simulando', 'erro', ?, 'evento') RETURNING id
				""", jobA, ts(OUTUBRO.plusSeconds(120)));
		dono.update("""
				INSERT INTO job_transicoes (job_id, status_anterior, status_novo, ocorrido_em, ator)
				VALUES (?, 'gerando_regra', 'simulando', ?, 'sistema')
				""", jobA, ts(OUTUBRO.plusSeconds(50)));
		return new Historico(jobA, jobB, ultima, correcao, erro, candidataErro, candidataSucesso, acao, erroJob);
	}

	private static UUID job(UUID usuario, @Nullable String nome, String texto, Instant instante) {
		UUID submissao = inserir("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em) VALUES (?, 'texto', ?, ?) RETURNING id
				""", usuario, texto, ts(instante));
		return inserir("""
				INSERT INTO jobs (usuario_id, submissao_id, nome, status, competencias, orcamento, criado_em)
				VALUES (?, ?, ?, 'gerando_regra', '{2026-10}', 600000, ?) RETURNING id
				""", usuario, submissao, nome, ts(instante));
	}

	private static UUID reprocessar(UUID origem, @Nullable String nome) {
		return inserir("""
				INSERT INTO jobs (usuario_id, job_origem_id, nome, status, competencias, orcamento, criado_em)
				VALUES (?, ?, ?, 'aguardando_confirmacao_parametros', '{2026-10}', 600000, ?) RETURNING id
				""", A, origem, nome, ts(OUTUBRO));
	}

	private static UUID versao(UUID job, int numero, String origem, String nucleo, @Nullable UUID anterior,
			Instant instante) {
		return inserir("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, regra_origem_id, criada_em)
				VALUES (?, ?, ?, ?::jsonb, '[]'::jsonb, ?, ?, ?) RETURNING id
				""", job, numero, origem, nucleo, Integer.toString(numero).repeat(64), anterior, ts(instante));
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

	private static UUID resultado(UUID job, UUID codigo, String status, String proposito, Instant instante) {
		return inserir(
				"""
						INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, proposito, veredito, assercoes, linhas, criado_em)
						VALUES (?, ?, ?, ?, CASE WHEN ? = 'sucesso' THEN 'viavel' ELSE NULL END, '[]'::jsonb,
						    '{"2026-10":{"MATRIC-PRIVADA":{"baseline":10,"simulado":11}}}'::jsonb, ?) RETURNING id
						""",
				job, codigo, status, proposito, status, ts(instante));
	}

	private static JsonNode consultar(String query) throws Exception {
		HttpResponse<String> resposta = chamar("/auditoria/eventos?" + query, auditor());
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("PaginaEventosAuditoria", resposta.body());
		return JSON.readTree(resposta.body());
	}

	private static JsonNode filtros() throws Exception {
		HttpResponse<String> resposta = chamar("/auditoria/eventos/filtros", auditor());
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("FiltrosEventosAuditoria", resposta.body());
		return JSON.readTree(resposta.body());
	}

	private static void assertContadores(JsonNode pagina, long eventos, long usuarios, long regras, long falhas) {
		assertThat(pagina.path("total").asLong()).isEqualTo(eventos);
		JsonNode contadores = pagina.path("contadores");
		assertThat(contadores.path("eventos").asLong()).isEqualTo(eventos);
		assertThat(contadores.path("usuarios").asLong()).isEqualTo(usuarios);
		assertThat(contadores.path("regras").asLong()).isEqualTo(regras);
		assertThat(contadores.path("simulacoes_com_falha").asLong()).isEqualTo(falhas);
	}

	private static JsonNode evento(JsonNode pagina, String tipo, UUID origem) {
		return StreamSupport.stream(pagina.path("itens").spliterator(), false)
			.filter(item -> item.path("tipo").asString().equals(tipo)
					&& item.path("origem_id").asString().equals(origem.toString()))
			.findFirst()
			.orElseThrow();
	}

	private static List<String> identidades(JsonNode itens) {
		return StreamSupport.stream(itens.spliterator(), false)
			.map(item -> item.path("job").path("id").asString() + ":" + item.path("tipo").asString() + ":"
					+ item.path("origem_id").asString())
			.toList();
	}

	private static List<UUID> jobs(JsonNode pagina) {
		return StreamSupport.stream(pagina.path("itens").spliterator(), false)
			.map(item -> UUID.fromString(item.path("job").path("id").asString()))
			.toList();
	}

	private static List<String> valores(JsonNode itens, String campo) {
		return StreamSupport.stream(itens.spliterator(), false).map(item -> item.path(campo).asString()).toList();
	}

	private static List<String> textos(JsonNode itens) {
		return StreamSupport.stream(itens.spliterator(), false).map(JsonNode::asString).toList();
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

	private static String codificar(String valor) {
		return URLEncoder.encode(valor, StandardCharsets.UTF_8);
	}

	private static String snapshotNegocio() {
		return Objects.requireNonNull(dono.queryForObject("""
				SELECT jsonb_build_object(
				  'jobs', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM jobs t),
				  'submissoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM submissoes t),
				  'regras', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM regras t),
				  'resultados', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM resultados_simulacao t),
				  'codigos', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM codigos_gerados t),
				  'rodadas', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM rodadas_correcao t),
				  'acoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM job_acoes t),
				  'transicoes', (SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM job_transicoes t),
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
		return token("subject-auditor", "auditoria", "auditor");
	}

	private static String token(String sub, String login, String papel) throws Exception {
		JWTClaimsSet claims = new JWTClaimsSet.Builder().subject(sub)
			.issuer(ISSUER)
			.issueTime(Date.from(Instant.now().minusSeconds(60)))
			.expirationTime(Date.from(Instant.now().plusSeconds(300)))
			.claim("preferred_username", login)
			.claim("realm_access", Map.of("roles", List.of(papel)))
			.build();
		SignedJWT jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID("teste-eventos").build(), claims);
		jwt.sign(new RSASSASigner(chave));
		return jwt.serialize();
	}

	private record Historico(UUID jobA, UUID jobB, UUID ultimaRegra, UUID correcao, UUID resultadoErro,
			UUID candidataErro, UUID candidataSucesso, UUID acao, UUID erroJob) {
	}

}
