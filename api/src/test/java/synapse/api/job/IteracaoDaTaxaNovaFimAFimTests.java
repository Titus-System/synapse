package synapse.api.job;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import ch.qos.logback.classic.spi.ILoggingEvent;
import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.amqp.core.AmqpAdmin;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * As tentativas de taxa nova pelo caminho real: a aplicação inteira contra RabbitMQ e
 * PostgreSQL, com o teste no lugar do codegen e do worker - grava os artefatos que eles
 * gravariam e publica nas filas o que eles publicariam. O que se confere é o que o
 * usuário vê: o job em processamento enquanto o codegen pode tentar outra taxa, o stream
 * sem o resultado de nenhuma alternativa intermediária, e o desfecho só na alternativa
 * que coube ou no fim das tentativas. As filas não têm ordem entre si, e as duas ordens
 * de chegada são exercitadas.
 */
@EnabledIf("dockerIsAvailable")
class IteracaoDaTaxaNovaFimAFimTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final UUID USUARIO_ID = UUID.fromString("75757575-7575-4575-8575-757575757575");

	private static final String NUCLEO = """
			{"vigencia":{"inicio":"2025-11","fim":"2025-11"},"loja":["13"],"marca":["10"],"cargo":["100"],"percentual":%s}
			""";

	/**
	 * Os valores que nenhum log pode levar: as taxas, os totais, o orçamento e a meta.
	 */
	private static final List<String> VALORES = List.of("0.0246", "0.0240", "0.0235", "492100", "490000", "486000",
			"485000", "26000000");

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = new JsonMapper();

	private static final Pattern AMOSTRA = Pattern.compile("^([a-z_]+)\\{([^}]*)\\} (\\S+)$", Pattern.MULTILINE);

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	private static int porta;

	private static RabbitTemplate rabbitTemplate;

	private static AmqpAdmin amqpAdmin;

	private static JdbcTemplate dono;

	private final List<StreamCliente> abertos = new ArrayList<>();

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void subirAplicacao() {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.start();
		rabbitmq = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		rabbitmq.start();

		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=" + USUARIO_API,
					"--app.postgres.password=" + SENHA, "--app.rabbitmq.host=" + rabbitmq.getHost(),
					"--app.rabbitmq.port=" + rabbitmq.getAmqpPort(),
					"--app.rabbitmq.user=" + rabbitmq.getAdminUsername(),
					"--app.rabbitmq.password=" + rabbitmq.getAdminPassword(), "--app.keycloak.enabled=false",
					"--app.transcription.processor.enabled=false", "--management.health.rabbit.enabled=false",
					"--management.health.db.enabled=false", "--app.outbox.poll-interval=200ms",
					"--app.sse.heartbeat=200ms");

		porta = Integer.parseInt(Objects.requireNonNull(contexto.getEnvironment().getProperty("local.server.port")));
		rabbitTemplate = contexto.getBean(RabbitTemplate.class);
		amqpAdmin = contexto.getBean(AmqpAdmin.class);
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE " + USUARIO_API + " WITH PASSWORD '" + SENHA + "'");
		dono.update("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES (?, 'rh-t275-e2e', 'x', 'RH', 'profissional_rh', now())
				""", USUARIO_ID);
	}

	@AfterAll
	static void derrubarTudo() {
		if (contexto != null) {
			contexto.close();
		}
		if (postgres != null) {
			postgres.stop();
		}
		if (rabbitmq != null) {
			rabbitmq.stop();
		}
	}

	@AfterEach
	void fecharStreamsEConferirFilasDrenadas() {
		for (StreamCliente cliente : this.abertos) {
			cliente.fechar();
		}
		this.abertos.clear();
		await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
			for (String fila : List.of(RabbitTopologyConfig.SUGESTAO_ADAPTACAO_PROPOSTA,
					RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API, RabbitTopologyConfig.ETAPA_ALTERADA)) {
				assertThat(Objects.requireNonNull(amqpAdmin.getQueueInfo(fila)).getMessageCount()).as(fila).isZero();
			}
		});
		assertThat(rabbitTemplate.receive(RabbitTopologyConfig.REGRA_SUBMETIDA, 1000))
			.as("nenhum regra-submetida além dos conferidos")
			.isNull();
	}

	/**
	 * Três alternativas que não cabem e o fim sem alternativa. A segunda proposta chega
	 * depois do resultado de que parte, a terceira antes, e o {@code sem_alternativa}
	 * antes do resultado da terceira alternativa.
	 */
	@Test
	void tresTentativasQueNaoCabemTerminamSemAlternativaSemMostrarAsIntermediarias() throws Exception {
		UUID jobId = criarJob();
		UUID original = criarVersaoRaiz(jobId);
		StreamCliente stream = conectar(jobId);
		stream.aguardarBloco("event:estado", Duration.ofSeconds(5));
		Map<String, Double> antes = metricas();

		List<ILoggingEvent> logs = new ArrayList<>();
		try (var sugestoes = new CapturaDeLog(SugestaoAdaptacaoConsumidor.class);
				var conclusoes = new CapturaDeLog(SimulacaoConcluidaConsumidor.class);
				var etapas = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			UUID resultadoOriginal = gravarResultado(jobId, original, "inviavel", "492100");
			publicarSimulacaoConcluida(jobId, resultadoOriginal, "inviavel");
			aguardarStatus(jobId, "simulacao_inviavel");

			publicarProposta(jobId, original, resultadoOriginal, "0.0246", 1);
			UUID primeira = aguardarVersao(jobId, 2);
			conferirRegraSubmetida(jobId, primeira);

			UUID resultadoPrimeira = gravarResultado(jobId, primeira, "inviavel", "490000");
			publicarSimulacaoConcluida(jobId, resultadoPrimeira, "inviavel");
			aguardarStatus(jobId, "simulando");
			publicarProposta(jobId, primeira, resultadoPrimeira, "0.0240", 2);
			UUID segunda = aguardarVersao(jobId, 3);
			conferirRegraSubmetida(jobId, segunda);

			UUID resultadoSegunda = gravarResultado(jobId, segunda, "inviavel", "490000");
			publicarProposta(jobId, segunda, resultadoSegunda, "0.0235", 3);
			UUID terceira = aguardarVersao(jobId, 4);
			conferirRegraSubmetida(jobId, terceira);
			publicarSimulacaoConcluida(jobId, resultadoSegunda, "inviavel");
			publicarProposta(jobId, segunda, resultadoSegunda, "0.0235", 3);

			UUID resultadoTerceira = gravarResultado(jobId, terceira, "inviavel", "486000");
			publicarSemAlternativa(jobId);
			aguardarStatus(jobId, "simulacao_inviavel");
			publicarSimulacaoConcluida(jobId, resultadoTerceira, "inviavel");
			publicarSemAlternativa(jobId);

			await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
				Map<String, Double> depois = metricas();
				assertThat(variacao(antes, depois, "sugestao_adaptacao_proposta_consumo_total",
						"resultado=\"aplicada\",tentativa=\"1\""))
					.isEqualTo(1.0);
				assertThat(variacao(antes, depois, "sugestao_adaptacao_proposta_consumo_total",
						"resultado=\"aplicada\",tentativa=\"2\""))
					.isEqualTo(1.0);
				assertThat(variacao(antes, depois, "sugestao_adaptacao_proposta_consumo_total",
						"resultado=\"aplicada\",tentativa=\"3\""))
					.isEqualTo(1.0);
				assertThat(variacao(antes, depois, "sugestao_adaptacao_proposta_consumo_total",
						"resultado=\"descartada\",tentativa=\"3\""))
					.isEqualTo(1.0);
				assertThat(variacao(antes, depois, "simulacao_concluida_consumo_total",
						"desfecho=\"inviavel\",resultado=\"aplicada\""))
					.isEqualTo(1.0);
				assertThat(variacao(antes, depois, "simulacao_concluida_consumo_total",
						"desfecho=\"inviavel\",resultado=\"intermediaria\""))
					.isEqualTo(1.0);
				assertThat(variacao(antes, depois, "simulacao_concluida_consumo_total",
						"desfecho=\"inviavel\",resultado=\"versao_anterior\""))
					.isEqualTo(1.0);
				assertThat(variacao(antes, depois, "simulacao_concluida_consumo_total",
						"desfecho=\"inviavel\",resultado=\"estado_incompativel\""))
					.isEqualTo(1.0);
				assertThat(variacao(antes, depois, "sugestao_adaptacao_encerramento_total",
						"causa=\"sem_alternativa\",resultado=\"aplicado\""))
					.isEqualTo(1.0);
				assertThat(variacao(antes, depois, "sugestao_adaptacao_encerramento_total",
						"causa=\"sem_alternativa\",resultado=\"sem_efeito\""))
					.isEqualTo(1.0);
			});
			logs.addAll(sugestoes.eventos());
			logs.addAll(conclusoes.eventos());
			logs.addAll(etapas.eventos());
		}

		assertThat(dono.queryForList("SELECT tentativa FROM regras WHERE job_id = ? ORDER BY versao", Integer.class,
				jobId))
			.containsExactly(null, 1, 2, 3);
		assertThat(transicoes(jobId)).containsExactly("simulando>simulacao_inviavel:inviavel",
				"simulacao_inviavel>gerando_regra:sugestao_adaptacao_proposta",
				"gerando_regra>simulando:simulacao_concluida_antecipada",
				"simulando>gerando_regra:sugestao_adaptacao_proposta",
				"gerando_regra>simulando:simulacao_concluida_antecipada",
				"simulando>gerando_regra:sugestao_adaptacao_proposta",
				"gerando_regra>simulando:simulacao_concluida_antecipada",
				"simulando>simulacao_inviavel:sem_alternativa");
		JobDetalhadoDto job = contexto.getBean(JobService.class).buscar(jobId);
		assertThat(job.status()).isEqualTo("simulacao_inviavel");
		assertThat(job.motivo()).isEqualTo(MotivoDaParada.NENHUMA_TAXA_COUBE);

		// O único resultado anunciado é o da regra original; o fim chega pela etapa e
		// pelo estado com o motivo próprio.
		stream.aguardarBloco(MotivoDaParada.NENHUMA_TAXA_COUBE, Duration.ofSeconds(10));
		assertThat(stream.contarOcorrencias("event:resultado")).isEqualTo(1);
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(stream.contarOcorrencias("\"status\":\"sem_alternativa\"")).isEqualTo(2));
		validarStream(stream);
		assertThat(stream.contarOcorrencias("\"status\":\"simulacao_inviavel\"")).isEqualTo(2);

		assertThat(logs).extracting(ILoggingEvent::getFormattedMessage)
			.contains("sugestao-adaptacao-proposta aplicada; ciclo do codegen reaberto",
					"sugestão descartada: origem inválida ou proposta já aplicada",
					"resultado inviável de alternativa registrado; job aguarda a próxima tentativa ou o fim da iteração",
					"tentativas de taxa nova encerradas sem alternativa; job inviável",
					"sem_alternativa sem iteração em curso; estado do job mantido");
		for (ILoggingEvent registro : logs) {
			String linha = CapturaDeLog.emJson(registro);
			ContratoDeEvento.validarLog(linha);
			JsonNode log = JSON.readTree(linha);
			assertThat(log.path("job_id").asString()).isEqualTo(jobId.toString());
			// Só a mensagem e o extra: o horário do envelope pode conter os mesmos
			// dígitos.
			String conteudo = log.path("message").asString() + log.path("extra").toString();
			assertThat(conteudo).as("nenhum log leva taxa, total, orçamento ou meta")
				.doesNotContain(VALORES)
				.doesNotContain("nucleo", "percentual");
		}
	}

	/** A alternativa que coube encerra a iteração no fluxo de aceitar ou cancelar. */
	@ParameterizedTest
	@ValueSource(ints = { 1, 2, 3 })
	void alternativaQueCabeEmQualquerTentativaVaiADecisaoDoUsuario(int tentativaViavel) throws Exception {
		UUID jobId = criarJob();
		UUID original = criarVersaoRaiz(jobId);
		StreamCliente stream = conectar(jobId);
		stream.aguardarBloco("event:estado", Duration.ofSeconds(5));
		UUID resultadoOriginal = gravarResultado(jobId, original, "inviavel", "492100");
		publicarSimulacaoConcluida(jobId, resultadoOriginal, "inviavel");
		aguardarStatus(jobId, "simulacao_inviavel");
		UUID segunda = original;
		UUID anterior = resultadoOriginal;
		List<String> taxas = List.of("0.0246", "0.0240", "0.0235");
		for (int tentativa = 1; tentativa <= tentativaViavel; tentativa++) {
			publicarProposta(jobId, segunda, anterior, taxas.get(tentativa - 1), tentativa);
			segunda = aguardarVersao(jobId, tentativa + 1);
			conferirRegraSubmetida(jobId, segunda);
			if (tentativa < tentativaViavel) {
				anterior = gravarResultado(jobId, segunda, "inviavel", "490000");
				publicarSimulacaoConcluida(jobId, anterior, "inviavel");
				aguardarStatus(jobId, "simulando");
			}
		}

		UUID resultadoSegunda = gravarResultado(jobId, segunda, "viavel", "484000");
		publicarSimulacaoConcluida(jobId, resultadoSegunda, "viavel");
		aguardarStatus(jobId, "aguardando_decisao_usuario");

		JobDetalhadoDto job = contexto.getBean(JobService.class).buscar(jobId);
		assertThat(Objects.requireNonNull(job.simulacao()).regra_id()).isEqualTo(segunda);
		assertThat(Objects.requireNonNull(job.simulacao()).veredito()).isEqualTo("viavel");
		stream.aguardarBloco("\"status\":\"aguardando_decisao_usuario\"", Duration.ofSeconds(10));
		assertThat(stream.contarOcorrencias("event:resultado")).isEqualTo(2);
		assertThat(stream.contarOcorrencias("\"veredito\":\"viavel\"")).isEqualTo(1);
		validarStream(stream);
	}

	/** O fim das tentativas que chega depois do resultado da última alternativa. */
	@Test
	void semAlternativaDepoisDoResultadoDaUltimaAlternativaTambemEncerra() throws Exception {
		UUID jobId = criarJob();
		UUID original = criarVersaoRaiz(jobId);
		UUID resultadoOriginal = gravarResultado(jobId, original, "inviavel", "492100");
		publicarSimulacaoConcluida(jobId, resultadoOriginal, "inviavel");
		aguardarStatus(jobId, "simulacao_inviavel");
		publicarProposta(jobId, original, resultadoOriginal, "0.0246", 1);
		UUID primeira = aguardarVersao(jobId, 2);
		conferirRegraSubmetida(jobId, primeira);
		UUID resultadoPrimeira = gravarResultado(jobId, primeira, "inviavel", "490000");
		publicarSimulacaoConcluida(jobId, resultadoPrimeira, "inviavel");
		aguardarStatus(jobId, "simulando");

		publicarSemAlternativa(jobId);
		aguardarStatus(jobId, "simulacao_inviavel");

		assertThat(transicoes(jobId)).last().isEqualTo("simulando>simulacao_inviavel:sem_alternativa");
		assertThat(contexto.getBean(JobService.class).buscar(jobId).motivo())
			.isEqualTo(MotivoDaParada.NENHUMA_TAXA_COUBE);
		assertThat(dono.queryForObject("SELECT resultado_id FROM simulacoes WHERE regra_id = ?", UUID.class, primeira))
			.isEqualTo(resultadoPrimeira);
	}

	@ParameterizedTest
	@ValueSource(strings = { "erro_codigo", "assercao_violada" })
	void erroNaAlternativaEncerraSemEsperarOutraTaxa(String statusResultado) throws Exception {
		UUID jobId = criarJob();
		UUID original = criarVersaoRaiz(jobId);
		UUID resultadoOriginal = gravarResultado(jobId, original, "inviavel", "492100");
		publicarProposta(jobId, original, resultadoOriginal, "0.0246", 1);
		UUID alternativa = aguardarVersao(jobId, 2);
		conferirRegraSubmetida(jobId, alternativa);
		StreamCliente stream = conectar(jobId);
		stream.aguardarBloco("event:estado", Duration.ofSeconds(5));
		UUID resultado = gravarResultado(jobId, alternativa, "inviavel", "490000");
		dono.update("UPDATE resultados_simulacao SET status = ?, veredito = NULL WHERE id = ?", statusResultado,
				resultado);
		publicar(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API, "simulacao-concluida", """
				{"job_id":"%s","resultado_id":"%s","status":"%s"}
				""".formatted(jobId, resultado, statusResultado));
		aguardarStatus(jobId, "erro");
		stream.aguardarFimDoStream(Duration.ofSeconds(10));
		assertThat(stream.conteudo()).contains("\"status\":\"erro\"");
		assertThat(transicoes(jobId)).last().isEqualTo("simulando>erro:" + statusResultado);
	}

	@Test
	void falhaNaSugestaoPreservaACausaEContaOEncerramentoUmaVez() throws Exception {
		UUID jobId = criarJob();
		UUID original = criarVersaoRaiz(jobId);
		UUID resultadoOriginal = gravarResultado(jobId, original, "inviavel", "492100");
		publicarProposta(jobId, original, resultadoOriginal, "0.0246", 1);
		UUID alternativa = aguardarVersao(jobId, 2);
		conferirRegraSubmetida(jobId, alternativa);
		gravarResultado(jobId, alternativa, "inviavel", "490000");
		Map<String, Double> antes = metricas();
		String evento = """
				{"job_id":"%s","etapa":"sugestao_adaptacao","status":"erro","causa":"provedor_indisponivel"}
				""".formatted(jobId);
		try (var captura = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			publicar(RabbitTopologyConfig.ETAPA_ALTERADA, "etapa-alterada", evento);
			aguardarStatus(jobId, "erro");
			publicar(RabbitTopologyConfig.ETAPA_ALTERADA, "etapa-alterada", evento);
			await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
				assertThat(variacao(antes, metricas(), "sugestao_adaptacao_encerramento_total",
						"causa=\"falha\",resultado=\"aplicado\""))
					.isEqualTo(1.0);
				assertThat(captura.eventos()).anySatisfy(registro -> {
					assertThat(registro.getFormattedMessage())
						.isEqualTo("tentativas de taxa nova interrompidas por falha; job em erro");
				});
			});
			for (ILoggingEvent registro : captura.eventos()) {
				String linha = CapturaDeLog.emJson(registro);
				ContratoDeEvento.validarLog(linha);
				assertThat(JSON.readTree(linha).path("job_id").asString()).isEqualTo(jobId.toString());
				assertThat(linha).doesNotContain("percentual", "0.0246");
			}
		}
		assertThat(contexto.getBean(MeterRegistry.class)
			.get("sugestao.adaptacao.encerramento")
			.tags("causa", "falha", "resultado", "aplicado")
			.counter()
			.count()).isEqualTo(1.0);
		assertThat(contexto.getBean(JobService.class).buscar(jobId).motivo())
			.isEqualTo(MotivoDaParada.PROVEDOR_INDISPONIVEL);
		assertThat(transicoes(jobId)).filteredOn(t -> t.contains(">erro:")).hasSize(1);
	}

	@Test
	void confirmacaoDuranteASimulacaoRetorna409SemCriarVersaoOuEvento() throws Exception {
		UUID jobId = criarJob();
		criarVersaoRaiz(jobId);
		String corpo = """
				{"regra":{"nucleo":%s,"especificacoes":[]}}
				""".formatted(NUCLEO.formatted("0.03").strip());
		HttpResponse<String> resposta = HTTP
			.send(HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/jobs/" + jobId + "/parameters"))
				.header("Content-Type", "application/json")
				.POST(HttpRequest.BodyPublishers.ofString(corpo))
				.build(), HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(409);
		assertThat(JSON.readTree(resposta.body()).path("codigo").asString()).isEqualTo("estado_invalido");
		assertThat(dono.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId))
			.isEqualTo("simulando");
		assertThat(dono.queryForObject("SELECT count(*) FROM regras WHERE job_id = ?", Integer.class, jobId))
			.isEqualTo(1);
		assertThat(dono.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId))
			.isZero();
		assertThat(transicoes(jobId)).isEmpty();
	}

	// --- O lugar do codegen e do worker ------------------------------------------------

	/** O job de uma regra que o usuário enviou, já simulando, com orçamento e meta. */
	private static UUID criarJob() {
		UUID submissaoId = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, conteudo, criado_em)
				VALUES (?, 'formulario', '{}'::jsonb, now()) RETURNING id
				""", UUID.class, USUARIO_ID));
		return Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO jobs (status, usuario_id, submissao_id, competencias, orcamento, meta_venda, criado_em)
				VALUES ('simulando', ?, ?, '{2025-11}', 485000, 26000000, now()) RETURNING id
				""", UUID.class, USUARIO_ID, submissaoId));
	}

	private static UUID criarVersaoRaiz(UUID jobId) {
		return Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
				VALUES (?, 1, 'confirmacao_usuario', ?::jsonb, '[]'::jsonb, repeat('0', 64), now()) RETURNING id
				""", UUID.class, jobId, NUCLEO.formatted("0.025")));
	}

	/**
	 * O que codegen e worker gravam por ciclo: prompt, código gerado e resultado, e a
	 * linha de {@code simulacoes} que o {@code no-concluido} da geração deixa sem
	 * resultado, porque chega antes da execução.
	 */
	private static UUID gravarResultado(UUID jobId, UUID regraId, String veredito, String simulado) {
		UUID prompt = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
				VALUES (?, 'geracao_codigo', 'fixture', '{}'::jsonb, now()) RETURNING id
				""", UUID.class, jobId));
		UUID codigo = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO codigos_gerados (job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES (?, ?, 'python', 'fixture', ?, now()) RETURNING id
				""", UUID.class, jobId, regraId, prompt));
		dono.update("""
				INSERT INTO simulacoes (criado_em, regra_id, job_id, codigo_gerado_id)
				VALUES (now(), ?, ?, ?)
				""", regraId, jobId, codigo);
		return Objects.requireNonNull(dono.queryForObject(
				"""
						INSERT INTO resultados_simulacao (job_id, codigo_gerado_id, status, veredito, totais, assercoes, criado_em)
						VALUES (?, ?, 'sucesso', ?, jsonb_build_object('baseline', 480000, 'simulado', ?::numeric,
						    'diferenca_abs', 0, 'diferenca_pct', 0, 'orcamento', 485000), '[]'::jsonb, now())
						RETURNING id
						""",
				UUID.class, jobId, codigo, veredito, simulado));
	}

	private static void publicarSimulacaoConcluida(UUID jobId, UUID resultadoId, String veredito) throws IOException {
		publicar(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API, "simulacao-concluida", """
				{"job_id":"%s","resultado_id":"%s","status":"sucesso","veredito":"%s"}
				""".formatted(jobId, resultadoId, veredito));
	}

	private static void publicarProposta(UUID jobId, UUID origem, UUID resultadoId, String percentual, int tentativa)
			throws IOException {
		publicar(RabbitTopologyConfig.SUGESTAO_ADAPTACAO_PROPOSTA, "sugestao-adaptacao-proposta", """
				{"job_id":"%s","regra_origem_id":"%s","resultado_id":"%s","tentativa":%d,
				 "representacao":{"nucleo":%s,"especificacoes":[]}}
				""".formatted(jobId, origem, resultadoId, tentativa, NUCLEO.formatted(percentual).strip()));
	}

	private static void publicarSemAlternativa(UUID jobId) throws IOException {
		publicar(RabbitTopologyConfig.ETAPA_ALTERADA, "etapa-alterada", """
				{"job_id":"%s","etapa":"sugestao_adaptacao","status":"sem_alternativa"}
				""".formatted(jobId));
	}

	/** Toda mensagem publicada aqui é conferida contra o contrato antes de sair. */
	private static void publicar(String fila, String evento, String corpo) throws IOException {
		ContratoDeEvento.validar(evento, corpo);
		Message mensagem = MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setType(evento)
			.build();
		rabbitTemplate.send("", fila, mensagem);
	}

	/**
	 * O {@code regra-submetida} que reabre o ciclo da alternativa, na fila do codegen:
	 * conforme o contrato e com o orçamento e a meta do job.
	 */
	private static void conferirRegraSubmetida(UUID jobId, UUID regraId) throws IOException {
		AtomicReference<Message> recebida = new AtomicReference<>();
		await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
			recebida.compareAndSet(null, rabbitTemplate.receive(RabbitTopologyConfig.REGRA_SUBMETIDA));
			assertThat(recebida.get()).isNotNull();
		});
		String payload = new String(Objects.requireNonNull(recebida.get()).getBody(), StandardCharsets.UTF_8);
		ContratoDeEvento.validar("regra-submetida", payload);
		JsonNode corpo = JSON.readTree(payload);
		assertThat(corpo.path("job_id").asString()).isEqualTo(jobId.toString());
		assertThat(corpo.path("regra_id").asString()).isEqualTo(regraId.toString());
		assertThat(corpo.path("orcamento").decimalValue()).isEqualByComparingTo("485000");
		assertThat(corpo.path("meta_venda").decimalValue()).isEqualByComparingTo("26000000");
	}

	private static void validarStream(StreamCliente stream) throws IOException {
		for (String bloco : stream.conteudo().split("\\n\\n")) {
			Matcher nome = Pattern.compile("(?m)^event:(.+)$").matcher(bloco);
			Matcher dados = Pattern.compile("(?m)^data:(.+)$").matcher(bloco);
			if (nome.find() && dados.find()) {
				ContratoDeEvento.validarEventoDoStream(nome.group(1).strip(), dados.group(1).strip());
			}
		}
	}

	// --- Apoio ------------------------------------------------------------------------

	private static void aguardarStatus(UUID jobId, String status) {
		await().atMost(Duration.ofSeconds(15))
			.untilAsserted(
					() -> assertThat(dono.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId))
						.isEqualTo(status));
	}

	private static UUID aguardarVersao(UUID jobId, int versao) {
		AtomicReference<UUID> id = new AtomicReference<>();
		await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
			List<UUID> encontradas = dono.queryForList("SELECT id FROM regras WHERE job_id = ? AND versao = ?",
					UUID.class, jobId, versao);
			assertThat(encontradas).hasSize(1);
			id.set(encontradas.getFirst());
		});
		return Objects.requireNonNull(id.get());
	}

	/** As transições do job, como {@code anterior>novo:motivo}. */
	private static List<String> transicoes(UUID jobId) {
		return dono.queryForList("""
				SELECT status_anterior || '>' || status_novo || ':' || COALESCE(motivo, '') FROM job_transicoes
				WHERE job_id = ? AND status_anterior IS NOT NULL ORDER BY ocorrido_em, id
				""", String.class, jobId);
	}

	private StreamCliente conectar(UUID jobId) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest
			.newBuilder(URI.create("http://localhost:" + porta + "/jobs/" + jobId + "/events"))
			.GET()
			.build();
		HttpResponse<InputStream> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofInputStream());
		StreamCliente cliente = new StreamCliente(resposta);
		this.abertos.add(cliente);
		return cliente;
	}

	/**
	 * As amostras de {@code /metrics}, por nome e rótulos como a exposição os escreve.
	 */
	private static Map<String, Double> metricas() throws Exception {
		HttpResponse<String> resposta = HTTP.send(
				HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/metrics")).GET().build(),
				HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(200);
		Map<String, Double> amostras = new HashMap<>();
		Matcher amostra = AMOSTRA.matcher(resposta.body());
		while (amostra.find()) {
			amostras.put(amostra.group(1) + "{" + amostra.group(2) + "}", Double.parseDouble(amostra.group(3)));
		}
		return amostras;
	}

	private static double variacao(Map<String, Double> antes, Map<String, Double> depois, String nome, String rotulos) {
		String chave = nome + "{" + rotulos + "}";
		return depois.getOrDefault(chave, 0.0) - antes.getOrDefault(chave, 0.0);
	}

}
