package synapse.api.job;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.JsonNode;

import org.springframework.amqp.core.AmqpAdmin;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.core.QueueInformation;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.awaitility.Awaitility.await;

/**
 * Sobe a aplicação inteira contra um Postgres e um RabbitMQ reais (as mesmas imagens do
 * compose) e publica na fila {@code etapa-alterada} como o codegen publicaria, para
 * confirmar o comportamento observável ponta a ponta: da fila ao stream SSE. O
 * comportamento interno de {@link EtapaAlteradaConsumidor} isolado de rede está coberto
 * por asserções mais finas caso um teste unitário seja necessário no futuro; hoje a fatia
 * inteira é pequena o bastante para caber num teste de integração só.
 */
@EnabledIf("dockerIsAvailable")
class EtapaAlteradaConsumidorTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "44444444-4444-4444-8444-444444444444";

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	private static int porta;

	private static EmissoresSse emissoresSse;

	private static RabbitTemplate rabbitTemplate;

	private static AmqpAdmin amqpAdmin;

	private static final JsonMapper JSON = new JsonMapper();

	private static final String CONFLITOS = """
			[{"elementos":["nucleo.percentual"],"motivo":"conflito reservado T215","futuro":{"dado":[1,true]}}]
			""";

	private static JdbcTemplate dono;

	private static MeterRegistry registry;

	private final List<StreamCliente> abertos = new ArrayList<>();

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void subirAplicacao() throws Exception {
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
					"--app.rabbitmq.password=" + rabbitmq.getAdminPassword(),
					"--management.health.rabbit.enabled=false", "--management.health.db.enabled=false",
					"--app.sse.heartbeat=200ms", "--spring.rabbitmq.listener.simple.concurrency=2",
					"--app.observability.log-level=INFO", "--debug=false");

		porta = Integer.parseInt(Objects.requireNonNull(contexto.getEnvironment().getProperty("local.server.port")));
		emissoresSse = contexto.getBean(EmissoresSse.class);
		rabbitTemplate = contexto.getBean(RabbitTemplate.class);
		amqpAdmin = contexto.getBean(AmqpAdmin.class);
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		registry = contexto.getBean(MeterRegistry.class);

		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("ALTER ROLE " + USUARIO_API + " WITH PASSWORD '" + SENHA + "'");
			statement.execute("""
					INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
					VALUES ('%s', 'rh', 'x', 'RH', 'profissional_rh', now())
					""".formatted(USUARIO_ID));
		}
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
	void fecharStreamsAbertosEConferirQueNaoVazou() {
		for (StreamCliente cliente : this.abertos) {
			cliente.fechar();
		}
		this.abertos.clear();
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> assertThat(emissoresSse.conexoesAtivas()).isZero());
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
	}

	// --- Cenários -----------------------------------------------------------------

	@Test
	void publicarNaFilaFazOEventoChegarAoClienteSseInscritoNaqueleJob() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "geracao_codigo", "iniciada");

		String bloco = cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));
		assertThat(bloco).contains("\"etapa\":\"geracao_codigo\"").contains("\"status\":\"iniciada\"");
	}

	@Test
	void oConsumoDoEventoNaoAlteraOStatusNemGeraTransicao() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "delegacao_worker", "iniciada");
		cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));

		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(contarTransicoes(jobId)).isZero();
	}

	@Test
	void entrarEmDelegacaoWorkerLevaOJobDeGerandoRegraASimulandoEAnunciaOEstado() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "delegacao_worker", "iniciada");

		String blocoEstado = cliente.aguardarBloco("\"status_anterior\":\"gerando_regra\"", Duration.ofSeconds(10));
		assertThat(blocoEstado).contains("\"status\":\"simulando\"");
		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(destinosDasTransicoes(jobId)).containsExactly("simulando");
		assertThat(cliente.conteudo().indexOf("event:etapa"))
			.isLessThan(cliente.conteudo().indexOf("\"status_anterior\""));
	}

	@Test
	void aMesmaEtapaEntregueDuasVezesProduzUmaUnicaTransicao() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);

		publicar(jobId, "delegacao_worker", "iniciada");
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("simulando"));
		publicar(jobId, "delegacao_worker", "iniciada");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
		assertThat(destinosDasTransicoes(jobId)).containsExactly("simulando");
	}

	@Test
	void statusErroLevaOJobDeGerandoRegraAErroFechaOStreamEGravaOMotivo() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "geracao_codigo", "erro");

		String blocoEstado = cliente.aguardarBloco("\"status_anterior\":\"gerando_regra\"", Duration.ofSeconds(10));
		assertThat(blocoEstado).contains("\"status\":\"erro\"").contains("\"motivo\"");
		cliente.aguardarFimDoStream(Duration.ofSeconds(10));
		assertThat(cliente.conteudo().indexOf("event:etapa"))
			.isLessThan(cliente.conteudo().indexOf("\"status_anterior\""));
		assertThat(statusPersistido(jobId)).isEqualTo("erro");
		assertThat(motivoDaUltimaTransicao(jobId)).isEqualTo("erro_geracao_codigo");

		// Depois do fim do stream, a consulta traz a mesma explicação que ele anunciou.
		criarRegra(jobId);
		JsonNode job = ClienteDoJob.consultar(porta, jobId);
		assertThat(job.path("motivo").asString())
			.isEqualTo(ClienteDoJob.dadosDoBloco(blocoEstado).path("motivo").asString())
			.isNotBlank();
		assertThat(job.propertyNames()).contains("finalizado_em").doesNotContain("simulacao");
	}

	@Test
	void aguardandoProvedorChegaAoClienteSemMudarOEstadoDoJob() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "geracao_codigo", "aguardando_provedor");

		String bloco = cliente.aguardarBloco("\"status\":\"aguardando_provedor\"", Duration.ofSeconds(10));
		assertThat(bloco).contains("\"etapa\":\"geracao_codigo\"").doesNotContain("causa");
		assertThat(statusPersistido(jobId)).isEqualTo("gerando_regra");
		assertThat(contarTransicoes(jobId)).isZero();
		assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(1);
	}

	@Test
	void erroComCausaProvedorIndisponivelGravaOMotivoProprioEExplicaNaConsulta() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "geracao_codigo", "erro", "provedor_indisponivel");

		String blocoEstado = cliente.aguardarBloco("\"status_anterior\":\"gerando_regra\"", Duration.ofSeconds(10));
		cliente.aguardarFimDoStream(Duration.ofSeconds(10));
		assertThat(statusPersistido(jobId)).isEqualTo("erro");
		assertThat(motivoDaUltimaTransicao(jobId)).isEqualTo("erro_provedor_indisponivel");
		String razao = ClienteDoJob.dadosDoBloco(blocoEstado).path("motivo").asString();
		assertThat(razao).isEqualTo(MotivoDaParada.PROVEDOR_INDISPONIVEL);

		criarRegra(jobId);
		JsonNode job = ClienteDoJob.consultar(porta, jobId);
		assertThat(job.path("motivo").asString()).isEqualTo(razao);
	}

	@Test
	void erroSemCausaOuComCausaDesconhecidaMantemOMotivoGenerico() throws Exception {
		UUID semCausa = criarJob(JobStatus.GERANDO_REGRA);
		UUID desconhecida = criarJob(JobStatus.GERANDO_REGRA);

		publicar(semCausa, "geracao_codigo", "erro");
		publicar(desconhecida, "geracao_codigo", "erro", "causa_futura");

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
			assertThat(statusPersistido(semCausa)).isEqualTo("erro");
			assertThat(statusPersistido(desconhecida)).isEqualTo("erro");
		});
		assertThat(motivoDaUltimaTransicao(semCausa)).isEqualTo("erro_geracao_codigo");
		assertThat(motivoDaUltimaTransicao(desconhecida)).isEqualTo("erro_geracao_codigo");
	}

	@Test
	void statusErroForaDeGerandoRegraSoRepassaAEtapa() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "geracao_codigo", "erro");
		cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));

		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(contarTransicoes(jobId)).isZero();
		assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(1);
	}

	@Test
	void etapaDeJobDesconhecidoEDescartadaSemDerrubarOConsumidor() throws Exception {
		publicar(UUID.randomUUID(), "delegacao_worker", "iniciada");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
		assertThat(infoDaFilaDeEtapaAlterada().getConsumerCount()).isGreaterThan(0);

		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);
		publicar(jobId, "delegacao_worker", "iniciada");
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("simulando"));
	}

	@Test
	void eventoDeJobSemClienteConectadoEConsumidoSemErro() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);

		publicar(jobId, "geracao_codigo", "iniciada");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
		assertThat(emissoresSse.conexoesAtivas()).isZero();
	}

	@Test
	void etapaForaDoVocabularioEDescartadaSemChegarAoCliente() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		publicar(jobId, "etapa_inventada", "iniciada");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());
		assertThat(infoDaFilaDeEtapaAlterada().getConsumerCount()).isGreaterThan(0);
		assertThat(cliente.conteudo()).doesNotContain("event:etapa");
	}

	@Test
	void jsonMalformadoEDescartadoSemDerrubarOConsumidor() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);

		Message mensagemInvalida = MessageBuilder.withBody("isto não é json".getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setType(RabbitTopologyConfig.ETAPA_ALTERADA)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.ETAPA_ALTERADA, mensagemInvalida);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFilaDeEtapaAlterada().getMessageCount()).isZero());

		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		publicar(jobId, "geracao_codigo", "iniciada");
		String bloco = cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));
		assertThat(bloco).contains("\"etapa\":\"geracao_codigo\"");
	}

	@Test
	void pausaValidaPersisteConflitosAnunciaDepoisDoCommitEDeduplica() throws Exception {
		UUID job = criarJob(JobStatus.GERANDO_REGRA);
		UUID regra = regra(job, 1);
		StreamCliente cliente = conectar(job);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		ObjectNode evento = pausa(job, regra);
		try (CapturaDeLog captura = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			publicarEEsperar(evento, "rodada_aberta");
			String estado = cliente.aguardarBloco("\"status_anterior\"", Duration.ofSeconds(10));
			String etapa = cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));
			JsonNode dados = ClienteDoJob.dadosDoBloco(etapa);
			assertThat(dados.path("conflitos")).isEqualTo(JSON.readTree(CONFLITOS));
			assertThat(dados.has("regra_id")).isFalse();
			ContratoDeEvento.validarEventoDoStream("etapa", dados.toString());
			ContratoDeEvento.validarEventoDoStream("estado", ClienteDoJob.dadosDoBloco(estado).toString());
			assertThat(ClienteDoJob.dadosDoBloco(estado).has("motivo")).isFalse();
			assertThat(cliente.conteudo().indexOf("event:etapa"))
				.isLessThan(cliente.conteudo().indexOf("\"status_anterior\""));
			assertThat(statusPersistido(job)).isEqualTo("aguardando_confirmacao_parametros");
			assertThat(destinosDasTransicoes(job)).containsExactly("aguardando_confirmacao_parametros");
			assertThat(motivoDaUltimaTransicao(job)).isEqualTo("validacao_com_conflitos");
			assertThat(dono.queryForObject("SELECT ator FROM job_transicoes WHERE job_id = ?", String.class, job))
				.isEqualTo("evento");
			var rodada = rodadas(job).getFirst();
			assertThat(rodada.get("estado")).isEqualTo("pendente");
			assertThat(rodada.get("regra_analisada_id")).isEqualTo(regra);
			assertThat(JSON.readTree(Objects.requireNonNull(rodada.get("conflitos")).toString()))
				.isEqualTo(JSON.readTree(CONFLITOS));
			assertThat(rodada.get("rodada_anterior_id")).isNull();
			assertThat(rodada.get("criada_em")).isEqualTo(rodada.get("atualizada_em"));
			assertThat(ClienteDoJob.consultar(porta, job).has("motivo")).isFalse();
			publicarEEsperar(evento, "duplicada");
			assertThat(rodadas(job)).hasSize(1);
			assertThat(contarTransicoes(job)).isEqualTo(1);
			assertThat(cliente.contarOcorrencias("event:etapa")).isEqualTo(1);
			assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(2);
			verificarLogs(captura, job, "rodada_aberta", "duplicada");
		}
		verificarScrape("rodada_aberta", "duplicada");
	}

	@Test
	void pausaAntigaDeduplicaAntesDeVerificarEstadoEVersao() throws Exception {
		UUID job = criarJob(JobStatus.GERANDO_REGRA);
		UUID antiga = regra(job, 1);
		publicarEEsperar(pausa(job, antiga), "rodada_aberta");
		dono.update("UPDATE rodadas_correcao SET estado = 'corrigida' WHERE job_id = ?", job);
		dono.update("UPDATE jobs SET status = 'gerando_regra' WHERE id = ?", job);
		regra(job, 2);
		publicarEEsperar(pausa(job, antiga), "duplicada");
		assertThat(statusPersistido(job)).isEqualTo("gerando_regra");
		assertThat(rodadas(job)).hasSize(1);
		assertThat(contarTransicoes(job)).isEqualTo(1);
	}

	@ParameterizedTest
	@ValueSource(strings = { "antiga", "outro_job", "ausentes", "null", "vazios", "objeto", "sem_regra", "inexistente",
			"etapa", "simulando", "erro" })
	void pausaInvalidaDescartaSemEscrita(String caso) throws Exception {
		UUID job = criarJob(JobStatus.GERANDO_REGRA);
		UUID regra = regra(job, 1);
		ObjectNode evento = pausa(job, regra);
		switch (caso) {
			case "antiga" -> regra(job, 2);
			case "outro_job" -> evento.put("regra_id", regra(criarJob(JobStatus.GERANDO_REGRA), 1).toString());
			case "ausentes" -> evento.remove("conflitos");
			case "null" -> evento.putNull("conflitos");
			case "vazios" -> evento.set("conflitos", JSON.createArrayNode());
			case "objeto" -> evento.set("conflitos", JSON.createObjectNode());
			case "sem_regra" -> evento.remove("regra_id");
			case "inexistente" -> evento.put("job_id", UUID.randomUUID().toString());
			case "etapa" -> evento.put("etapa", "geracao_codigo");
			case "simulando", "erro" -> dono.update("UPDATE jobs SET status = ? WHERE id = ?", caso, job);
			default -> throw new AssertionError(caso);
		}
		String antes = statusPersistido(job);
		try (CapturaDeLog captura = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			publicarEEsperar(evento, "descartada");
			UUID correlacao = UUID.fromString(evento.path("job_id").asString());
			verificarLogs(captura, correlacao, "descartada");
			String motivo = switch (caso) {
				case "antiga", "outro_job" -> "regra_nao_atual";
				case "ausentes", "null", "vazios", "objeto" -> "conflitos_invalidos";
				case "sem_regra" -> "regra_ausente";
				case "inexistente" -> "job_inexistente";
				case "etapa" -> "evento_invalido";
				default -> "estado_incompativel";
			};
			assertThat(JSON.readTree(CapturaDeLog.emJson(captura.eventos().getFirst()))
				.path("extra")
				.path("motivo_descarte")
				.asString()).isEqualTo(motivo);
		}
		assertThat(rodadas(job)).isEmpty();
		assertThat(contarTransicoes(job)).isZero();
		assertThat(statusPersistido(job)).isEqualTo(antes);
		verificarScrape("descartada");
	}

	@Test
	void rodadaNovaEncadeiaAUltimaRodadaFechada() throws Exception {
		UUID job = criarJob(JobStatus.GERANDO_REGRA);
		UUID primeira = regra(job, 1);
		UUID a = historico(job, primeira, "corrigida", null, "2026-01-01T00:00:00Z");
		UUID b = historico(job, primeira, "corrigida", a, "2026-01-02T00:00:00Z");
		UUID atual = regra(job, 2);
		publicarEEsperar(pausa(job, atual), "rodada_aberta");
		assertThat(rodadas(job).getLast().get("rodada_anterior_id")).isEqualTo(b);
	}

	@Test
	void falhaReextracaoIdentificadaReabreUmaVez() throws Exception {
		UUID job = criarJob(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS);
		UUID regra = regra(job, 1);
		UUID anterior = historico(job, regra, "em_reextracao", null, "2026-01-01T00:00:00Z");
		UUID submissao = iniciarTentativa(anterior);
		StreamCliente cliente = conectar(job);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		ObjectNode evento = falha(job, regra).put("submissao_id", submissao.toString());
		ContratoDeEvento.validar("etapa-alterada", evento.toString());
		try (CapturaDeLog captura = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			publicarEEsperar(evento, "reextracao_falhou");
			String etapa = cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));
			JsonNode dados = ClienteDoJob.dadosDoBloco(etapa);
			assertThat(dados.has("conflitos")).isFalse();
			ContratoDeEvento.validarEventoDoStream("etapa", dados.toString());
			assertThat(rodadas(job)).hasSize(2);
			var antiga = rodadas(job).getFirst();
			var nova = rodadas(job).getLast();
			assertThat(antiga.get("estado")).isEqualTo("reextracao_falhou");
			assertThat(nova.get("estado")).isEqualTo("pendente");
			assertThat(nova.get("regra_analisada_id")).isEqualTo(regra);
			assertThat(nova.get("rodada_anterior_id")).isEqualTo(anterior);
			assertThat(nova.get("conflitos")).isEqualTo(antiga.get("conflitos"));
			assertThat(nova.get("criada_em")).isEqualTo(nova.get("atualizada_em"))
				.isEqualTo(antiga.get("atualizada_em"));
			publicarEEsperar(evento, "duplicada");
			verificarLogs(captura, job, "reextracao_falhou", "duplicada");
		}
		assertThat(rodadas(job)).hasSize(2);
		assertThat(contarTransicoes(job)).isZero();
		assertThat(statusPersistido(job)).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(1);
		assertThat(cliente.contarOcorrencias("event:etapa")).isEqualTo(1);
		verificarScrape("reextracao_falhou", "duplicada");
	}

	@Test
	void reentregaDaTentativaANaoEncerraTentativaBDaMesmaRegra() throws Exception {
		UUID job = criarJob(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS);
		UUID regra = regra(job, 1);
		UUID rodadaA = historico(job, regra, "em_reextracao", null, "2026-01-01T00:00:00Z");
		UUID submissaoA = iniciarTentativa(rodadaA);
		ObjectNode eventoA = falha(job, regra).put("submissao_id", submissaoA.toString());
		StreamCliente cliente = conectar(job);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		publicarEEsperar(eventoA, "reextracao_falhou");
		cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));
		UUID rodadaB = (UUID) rodadas(job).getLast().get("id");
		UUID submissaoB = iniciarTentativa(Objects.requireNonNull(rodadaB));
		var antes = rodadas(job);
		double falhas = contagem("reextracao_falhou");
		double descartadas = contagem("descartada");
		publicarEEsperar(eventoA, "duplicada");
		assertThat(rodadas(job)).isEqualTo(antes).hasSize(2);
		assertThat(rodadas(job).getLast()).containsEntry("estado", "em_reextracao")
			.containsEntry("submissao_correcao_id", submissaoB);
		assertThat(contagem("reextracao_falhou")).isEqualTo(falhas);
		assertThat(contagem("descartada")).isEqualTo(descartadas);
		assertThat(statusPersistido(job)).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(contarTransicoes(job)).isZero();
		assertThat(cliente.contarOcorrencias("event:etapa")).isEqualTo(1);
		assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(1);
		verificarScrape("reextracao_falhou", "duplicada");
	}

	@ParameterizedTest
	@ValueSource(strings = { "identificada", "legada", "sem_regra" })
	void erroDaVersaoSuperadaNaoEncerraVersaoNova(String formato) throws Exception {
		UUID job = criarJob(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS);
		UUID antiga = regra(job, 1);
		UUID rodada = historico(job, antiga, "em_reextracao", null, "2026-01-01T00:00:00Z");
		UUID submissao = iniciarTentativa(rodada);
		UUID nova = regra(job, 2);
		dono.update("UPDATE rodadas_correcao SET estado = 'corrigida', regra_resultante_id = ? WHERE id = ?", nova,
				rodada);
		dono.update("UPDATE jobs SET status = 'gerando_regra' WHERE id = ?", job);
		StreamCliente cliente = conectar(job);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		ObjectNode evento = falha(job, "sem_regra".equals(formato) ? null : antiga);
		if ("identificada".equals(formato)) {
			evento.put("submissao_id", submissao.toString());
		}
		var antes = rodadas(job);
		publicarEEsperar(evento, "descartada");
		assertThat(statusPersistido(job)).isEqualTo("gerando_regra");
		assertThat(contarTransicoes(job)).isZero();
		assertThat(rodadas(job)).isEqualTo(antes);
		assertThat(cliente.contarOcorrencias("event:etapa")).isZero();
		assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(1);
		verificarScrape("descartada");
	}

	@ParameterizedTest
	@ValueSource(strings = { "sem_submissao", "sem_identificadores", "desconhecida", "outra_regra", "outro_job",
			"sem_regra", "ambigua", "pendente", "abandonada" })
	void falhaSemTentativaCorrespondenteNaoAlteraRodadas(String caso) throws Exception {
		UUID job = criarJob(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS);
		UUID regra = regra(job, 1);
		UUID rodada = historico(job, regra, "em_reextracao", null, "2026-01-01T00:00:00Z");
		UUID submissao = iniciarTentativa(rodada);
		ObjectNode evento = falha(job, regra).put("submissao_id", submissao.toString());
		switch (caso) {
			case "sem_submissao" -> evento.remove("submissao_id");
			case "sem_identificadores" -> {
				evento.remove("submissao_id");
				evento.remove("regra_id");
			}
			case "desconhecida" -> evento.put("submissao_id", UUID.randomUUID().toString());
			case "outra_regra" -> evento.put("regra_id", UUID.randomUUID().toString());
			case "outro_job" -> evento.put("job_id", criarJob(JobStatus.GERANDO_REGRA).toString());
			case "sem_regra" -> evento.remove("regra_id");
			case "ambigua" -> {
				UUID fechada = historico(job, regra, "reextracao_falhou", null, "2025-12-01T00:00:00Z");
				dono.update("UPDATE rodadas_correcao SET submissao_correcao_id = ? WHERE id = ?", submissao, fechada);
			}
			case "pendente", "abandonada" ->
				dono.update("UPDATE rodadas_correcao SET estado = ? WHERE id = ?", caso, rodada);
			default -> throw new AssertionError(caso);
		}
		var antes = rodadas(job);
		publicarEEsperar(evento, "descartada");
		assertThat(rodadas(job)).isEqualTo(antes);
		assertThat(contarTransicoes(job)).isZero();
		assertThat(statusPersistido(job)).isEqualTo("aguardando_confirmacao_parametros");
	}

	@Test
	void falhaDeOutraRegraNaoFechaRodada() throws Exception {
		UUID job = criarJob(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS);
		UUID regra = regra(job, 1);
		historico(job, regra, "em_reextracao", null, "2026-01-01T00:00:00Z");
		publicarEEsperar(falha(job, UUID.randomUUID()), "descartada");
		assertThat(rodadas(job)).hasSize(1);
		assertThat(rodadas(job).getFirst().get("estado")).isEqualTo("em_reextracao");
		assertThat(contarTransicoes(job)).isZero();
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void falhaDaExtracaoInicialContinuaTerminalSemRodadas(boolean provedorIndisponivel) throws Exception {
		UUID job = criarJob(JobStatus.GERANDO_REGRA);
		StreamCliente cliente = conectar(job);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		publicar(job, "extracao_parametros", "erro", provedorIndisponivel ? "provedor_indisponivel" : null);
		cliente.aguardarFimDoStream(Duration.ofSeconds(10));
		assertThat(statusPersistido(job)).isEqualTo("erro");
		assertThat(rodadas(job)).isEmpty();
		assertThat(motivoDaUltimaTransicao(job))
			.isEqualTo(provedorIndisponivel ? "erro_provedor_indisponivel" : "erro_extracao_parametros");
		assertThat(cliente.conteudo()).contains("event:etapa", "\"status\":\"erro\"");
	}

	@Test
	void esperaDoProvedorPreservaStreamSemConflitos() throws Exception {
		UUID job = criarJob(JobStatus.GERANDO_REGRA);
		StreamCliente cliente = conectar(job);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		publicar(job, "geracao_codigo", "aguardando_provedor");
		JsonNode dados = ClienteDoJob.dadosDoBloco(cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10)));
		assertThat(dados.has("conflitos")).isFalse();
		ContratoDeEvento.validarEventoDoStream("etapa", dados.toString());
		assertThat(statusPersistido(job)).isEqualTo("gerando_regra");
		assertThat(contarTransicoes(job)).isZero();
	}

	@ParameterizedTest
	@ValueSource(booleans = { false, true })
	void falhaNoInsertDesfazTodaOperacaoSemSseOuContadorDeSucesso(boolean reextracao) throws Exception {
		UUID job = criarJob(reextracao ? JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS : JobStatus.GERANDO_REGRA);
		UUID regra = regra(job, 1);
		UUID submissao = reextracao
				? iniciarTentativa(historico(job, regra, "em_reextracao", null, "2026-01-01T00:00:00Z")) : null;
		String status = statusPersistido(job);
		StreamCliente cliente = conectar(job);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		dono.execute(
				"CREATE FUNCTION t215_recusar_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'falha reservada'; END $$");
		dono.execute(
				"CREATE TRIGGER t215_recusar BEFORE INSERT ON rodadas_correcao FOR EACH ROW EXECUTE FUNCTION t215_recusar_insert()");
		double sucesso = contagem(reextracao ? "reextracao_falhou" : "rodada_aberta");
		ObjectNode evento = reextracao ? falha(job, regra) : pausa(job, regra);
		if (submissao != null) {
			evento.put("submissao_id", submissao.toString());
		}
		MDC.put("job_id", "contexto-anterior");
		try (CapturaDeLog captura = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			assertThatThrownBy(() -> contexto.getBean(EtapaAlteradaConsumidor.class)
				.receber(JSON.treeToValue(evento, EtapaAlteradaDto.class))).isInstanceOf(RuntimeException.class)
				.hasMessage("falha de persistência ao consumir etapa-alterada")
				.hasNoCause()
				.satisfies(ex -> assertThat(ex.getSuppressed()).isEmpty());
			assertThat(MDC.get("job_id")).isEqualTo("contexto-anterior");
			assertThat(captura.eventos()).hasSize(1);
			String linha = CapturaDeLog.emJson(captura.eventos().getFirst());
			ContratoDeEvento.validarLog(linha);
			assertThat(linha).contains(job.toString(), "banco")
				.doesNotContain("falha reservada", "conflito reservado", "exception");
		}
		finally {
			MDC.clear();
			dono.execute("DROP TRIGGER t215_recusar ON rodadas_correcao");
			dono.execute("DROP FUNCTION t215_recusar_insert()");
		}
		assertThat(statusPersistido(job)).isEqualTo(status);
		assertThat(contarTransicoes(job)).isZero();
		assertThat(rodadas(job)).hasSize(reextracao ? 1 : 0);
		if (reextracao) {
			assertThat(rodadas(job).getFirst().get("estado")).isEqualTo("em_reextracao");
		}
		assertThat(cliente.contarOcorrencias("event:etapa")).isZero();
		assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(1);
		assertThat(contagem(reextracao ? "reextracao_falhou" : "rodada_aberta")).isEqualTo(sucesso);
		assertThat(registry.get("etapa.alterada.consumo.duracao").tag("resultado", "falha").timer().count())
			.isPositive();
	}

	@Test
	void travaSerializaDuasPausasAntesDaDecisaoDeDeduplicar() throws Exception {
		UUID job = criarJob(JobStatus.GERANDO_REGRA);
		UUID regra = regra(job, 1);
		var servico = contexto.getBean(JobEventosService.class);
		CountDownLatch iniciadas = new CountDownLatch(2);
		try (var executor = Executors.newFixedThreadPool(2); Connection bloqueio = comoDono()) {
			bloqueio.setAutoCommit(false);
			try (var consulta = bloqueio.prepareStatement("SELECT id FROM jobs WHERE id = ? FOR UPDATE")) {
				consulta.setObject(1, job);
				consulta.executeQuery().close();
			}
			java.util.concurrent.Callable<EtapaAplicada> consumir = () -> {
				iniciadas.countDown();
				return servico.aplicarEtapaAlterada(job, EtapaDoGrafo.CONFIRMACAO, "aguardando_correcao", null, regra,
						JSON.readTree(CONFLITOS));
			};
			var a = executor.submit(consumir);
			var b = executor.submit(consumir);
			assertThat(iniciadas.await(5, TimeUnit.SECONDS)).isTrue();
			try {
				await().atMost(Duration.ofSeconds(10))
					.untilAsserted(() -> assertThat(dono.queryForObject(
							"SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND query LIKE '%FOR UPDATE%' AND usename = ?",
							Integer.class, USUARIO_API))
						.isEqualTo(2));
				assertThat(a.isDone()).isFalse();
				assertThat(b.isDone()).isFalse();
			}
			finally {
				bloqueio.commit();
			}
			assertThat(List.of(a.get(10, TimeUnit.SECONDS).desfecho(), b.get(10, TimeUnit.SECONDS).desfecho()))
				.containsExactlyInAnyOrder(DesfechoCorrecao.RODADA_ABERTA, DesfechoCorrecao.DUPLICADA);
		}
		assertThat(rodadas(job)).hasSize(1);
		assertThat(contarTransicoes(job)).isEqualTo(1);
	}

	@Test
	void duasEntregasRabbitConcorrentesAbremUmaRodada() throws Exception {
		UUID job = criarJob(JobStatus.GERANDO_REGRA);
		UUID regra = regra(job, 1);
		double abertas = contagem("rodada_aberta");
		double duplicadas = contagem("duplicada");
		Message mensagem = MessageBuilder.withBody(pausa(job, regra).toString().getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.ETAPA_ALTERADA, mensagem);
		rabbitTemplate.send("", RabbitTopologyConfig.ETAPA_ALTERADA, mensagem);
		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
			assertThat(contagem("rodada_aberta")).isEqualTo(abertas + 1);
			assertThat(contagem("duplicada")).isEqualTo(duplicadas + 1);
		});
		assertThat(rodadas(job)).hasSize(1);
		assertThat(contarTransicoes(job)).isEqualTo(1);
	}

	@Test
	void falhaTransitoriaNaFilaSofreRollbackEReentregaAteCommit() throws Exception {
		UUID job = criarJob(JobStatus.GERANDO_REGRA);
		UUID regra = regra(job, 1);
		StreamCliente cliente = conectar(job);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		dono.execute("CREATE SEQUENCE t215_tentativa");
		dono.execute("GRANT USAGE ON SEQUENCE t215_tentativa TO " + USUARIO_API);
		dono.execute("CREATE TABLE t215_bloqueio (ativo boolean NOT NULL)");
		dono.execute("INSERT INTO t215_bloqueio VALUES (true)");
		dono.execute("GRANT SELECT ON t215_bloqueio TO " + USUARIO_API);
		dono.execute("""
				CREATE FUNCTION t215_falhar_uma_vez() RETURNS trigger LANGUAGE plpgsql AS $$
				BEGIN PERFORM nextval('t215_tentativa');
				IF (SELECT ativo FROM t215_bloqueio) THEN
				  PERFORM pg_sleep(0.05);
				  RAISE EXCEPTION 'linha rejeitada: %', NEW.conflitos->0->>'motivo' USING ERRCODE = '40001';
				END IF;
				RETURN NEW; END $$
				""");
		dono.execute(
				"CREATE TRIGGER t215_falhar_uma_vez BEFORE INSERT ON rodadas_correcao FOR EACH ROW EXECUTE FUNCTION t215_falhar_uma_vez()");
		double abertas = contagem("rodada_aberta");
		try (CapturaDeLog consumidor = new CapturaDeLog(EtapaAlteradaConsumidor.class);
				CapturaDeLog framework = new CapturaDeLog("org.springframework.amqp");
				CapturaDeLog aplicacao = new CapturaDeLog(org.slf4j.Logger.ROOT_LOGGER_NAME)) {
			Message mensagem = MessageBuilder.withBody(pausa(job, regra).toString().getBytes(StandardCharsets.UTF_8))
				.setContentType(MessageProperties.CONTENT_TYPE_JSON)
				.build();
			rabbitTemplate.send("", RabbitTopologyConfig.ETAPA_ALTERADA, mensagem);
			await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
				assertThat(dono.queryForObject("SELECT last_value FROM t215_tentativa", Long.class)).isGreaterThan(1L);
				assertThat(framework.eventos()).anySatisfy(
						evento -> assertThat(evento.getLoggerName()).contains("ConditionalRejectingErrorHandler"));
			});
			assertThat(statusPersistido(job)).isEqualTo("gerando_regra");
			assertThat(contarTransicoes(job)).isZero();
			assertThat(rodadas(job)).isEmpty();
			assertThat(contagem("rodada_aberta")).isEqualTo(abertas);
			assertThat(cliente.contarOcorrencias("event:etapa")).isZero();
			dono.update("UPDATE t215_bloqueio SET ativo = false");
			await().atMost(Duration.ofSeconds(10))
				.untilAsserted(() -> assertThat(contagem("rodada_aberta")).isEqualTo(abertas + 1));
			cliente.aguardarBloco("event:etapa", Duration.ofSeconds(10));
			assertThat(rodadas(job)).hasSize(1);
			assertThat(contarTransicoes(job)).isEqualTo(1);
			assertThat(statusPersistido(job)).isEqualTo("aguardando_confirmacao_parametros");
			assertThat(cliente.contarOcorrencias("event:etapa")).isEqualTo(1);
			for (var captura : List.of(consumidor, framework)) {
				assertThat(captura.eventos()).isNotEmpty();
				for (var evento : captura.eventos()) {
					String linha = CapturaDeLog.emJson(evento);
					ContratoDeEvento.validarLog(linha);
					assertThat(linha).doesNotContain("conflito reservado T215", "linha rejeitada", "NEW.conflitos",
							"INSERT INTO rodadas_correcao");
				}
			}
			// Qualquer logger da aplicação, não só o do container, pode receber a exceção
			// do driver; o formato de cada um não é deste teste, só a ausência do
			// conteúdo.
			for (var evento : aplicacao.eventos()) {
				assertThat(CapturaDeLog.emJson(evento)).doesNotContain("conflito reservado T215", "linha rejeitada",
						"NEW.conflitos", "INSERT INTO rodadas_correcao");
			}
			assertThat(registry.get("etapa.alterada.consumo.duracao").tag("resultado", "falha").timer().count())
				.isPositive();
			verificarScrape("rodada_aberta");
		}
		finally {
			dono.update("UPDATE t215_bloqueio SET ativo = false");
			dono.execute("DROP TRIGGER t215_falhar_uma_vez ON rodadas_correcao");
			dono.execute("DROP FUNCTION t215_falhar_uma_vez()");
			dono.execute("DROP SEQUENCE t215_tentativa");
			dono.execute("DROP TABLE t215_bloqueio");
		}
	}

	@ParameterizedTest
	@CsvSource({ "sugestao_adaptacao,sem_alternativa,,SIMULANDO", "decisao,erro,,SIMULANDO",
			"decisao,erro,provedor_indisponivel,GERANDO_REGRA", "sugestao_adaptacao,erro,,GERANDO_REGRA",
			"sugestao_adaptacao,erro,provedor_indisponivel,SIMULANDO" })
	void fimDaIteracaoCoexisteComCorrecaoPelaFila(String etapa, String sinal, @Nullable String causa, JobStatus inicial)
			throws Exception {
		UUID correcao = criarJob(JobStatus.GERANDO_REGRA);
		ObjectNode pedido = pausa(correcao, regra(correcao, 1));
		publicarEEsperar(pedido, "rodada_aberta");
		publicarEEsperar(pedido, "duplicada");
		double correcoesAntes = registry.find("etapa.alterada.correcao")
			.counters()
			.stream()
			.mapToDouble(io.micrometer.core.instrument.Counter::count)
			.sum();
		boolean semAlternativa = "sem_alternativa".equals(sinal);
		String causaFim = semAlternativa ? "sem_alternativa" : "falha";
		double finaisAntes = contagemFim(causaFim, "aplicado");
		UUID job = criarJob(inicial);
		UUID resultado = alternativaInviavel(job);
		StreamCliente cliente = conectar(job);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		try (CapturaDeLog captura = new CapturaDeLog(EtapaAlteradaConsumidor.class)) {
			publicar(job, etapa, sinal, causa);
			cliente.aguardarBloco("\"status_anterior\"", Duration.ofSeconds(10));
			if (!semAlternativa) {
				cliente.aguardarFimDoStream(Duration.ofSeconds(10));
			}
			await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
				assertThat(contagemFim(causaFim, "aplicado")).isEqualTo(finaisAntes + 1);
				assertThat(captura.eventos()).anySatisfy(evento -> {
					String linha = CapturaDeLog.emJson(evento);
					assertThat(linha).contains("\"causa\":\"" + causaFim + "\"");
				});
			});
			for (var evento : captura.eventos()) {
				String linha = CapturaDeLog.emJson(evento);
				ContratoDeEvento.validarLog(linha);
				assertThat(JSON.readTree(linha).path("job_id").asString()).isEqualTo(job.toString());
				assertThat(linha).doesNotContain("conflito reservado", "fixture", "conteudo");
			}
		}
		String destino = semAlternativa ? "simulacao_inviavel" : "erro";
		assertThat(statusPersistido(job)).isEqualTo(destino);
		String motivo = semAlternativa ? "sem_alternativa" : "erro_" + (causa == null ? etapa : causa);
		assertThat(motivoDaUltimaTransicao(job)).isEqualTo(motivo);
		assertThat(contarTransicoes(job)).isEqualTo(inicial == JobStatus.GERANDO_REGRA ? 2 : 1);
		assertThat(dono.queryForObject("SELECT resultado_id FROM simulacoes WHERE job_id = ?", UUID.class, job))
			.isEqualTo(resultado);
		assertThat(rodadas(job)).isEmpty();
		String blocoEtapa = cliente.aguardarBloco("event:etapa", Duration.ofSeconds(5));
		String blocoEstado = cliente.aguardarBloco("\"status_anterior\"", Duration.ofSeconds(5));
		JsonNode dados = ClienteDoJob.dadosDoBloco(blocoEtapa);
		assertThat(dados.has("conflitos")).isFalse();
		assertThat(dados.has("regra_id")).isFalse();
		ContratoDeEvento.validarEventoDoStream("etapa", dados.toString());
		ContratoDeEvento.validarEventoDoStream("estado", ClienteDoJob.dadosDoBloco(blocoEstado).toString());
		assertThat(cliente.conteudo().indexOf("event:etapa"))
			.isLessThan(cliente.conteudo().indexOf("\"status_anterior\""));
		assertThat(registry.find("etapa.alterada.correcao")
			.counters()
			.stream()
			.mapToDouble(io.micrometer.core.instrument.Counter::count)
			.sum()).isEqualTo(correcoesAntes);
		assertThat(statusPersistido(correcao)).isEqualTo("aguardando_confirmacao_parametros");
		assertThat(rodadas(correcao)).hasSize(1);
		verificarScrape("rodada_aberta", "duplicada");
		var scrape = HTTP.send(
				HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/metrics")).GET().build(),
				HttpResponse.BodyHandlers.ofString());
		assertThat(scrape.body()).contains("sugestao_adaptacao_encerramento_total{causa=\"" + causaFim
				+ "\",resultado=\"aplicado\"} " + (finaisAntes + 1));
		assertThat(registry.get("sugestao.adaptacao.encerramento").counters()).allSatisfy(contador -> {
			assertThat(contador.getId().getTags()).hasSize(2);
			assertThat(contador.getId().getTag("causa")).isIn("sem_alternativa", "falha");
			assertThat(contador.getId().getTag("resultado")).isIn("aplicado", "sem_efeito");
		});
		if (semAlternativa) {
			double semEfeitoAntes = contagemFim(causaFim, "sem_efeito");
			publicar(job, etapa, sinal, causa);
			await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
				assertThat(contagemFim(causaFim, "sem_efeito")).isEqualTo(semEfeitoAntes + 1);
				assertThat(cliente.contarOcorrencias("event:etapa")).isEqualTo(2);
			});
			assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(2);
			assertThat(contagemFim(causaFim, "aplicado")).isEqualTo(finaisAntes + 1);
			assertThat(contarTransicoes(job)).isEqualTo(1);
		}
	}

	private static double contagemFim(String causa, String resultado) {
		var contador = registry.find("sugestao.adaptacao.encerramento")
			.tags("causa", causa, "resultado", resultado)
			.counter();
		return contador == null ? 0 : contador.count();
	}

	private static UUID alternativaInviavel(UUID job) {
		UUID original = regra(job, 1);
		UUID alternativa = regra(job, 2);
		dono.update("UPDATE regras SET origem = 'sugestao_adaptacao', regra_origem_id = ? WHERE id = ?", original,
				alternativa);
		UUID prompt = UUID.randomUUID();
		UUID codigo = UUID.randomUUID();
		UUID resultado = UUID.randomUUID();
		dono.update("""
				INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
				VALUES (?, ?, 'geracao_codigo', 'fixture', '{}'::jsonb, now())
				""", prompt, job);
		dono.update("""
				INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
				VALUES (?, ?, ?, 'python', 'fixture', ?, now())
				""", codigo, job, alternativa, prompt);
		dono.update(
				"""
						INSERT INTO resultados_simulacao (id, job_id, codigo_gerado_id, status, veredito, totais, assercoes, criado_em)
						VALUES (?, ?, ?, 'sucesso', 'inviavel',
						'{"baseline":900,"simulado":1100,"diferenca_abs":200,"diferenca_pct":22.22,"orcamento":1000}'::jsonb,
						'[]'::jsonb, now())
						""",
				resultado, job, codigo);
		dono.update("""
				INSERT INTO simulacoes (criado_em, regra_id, job_id, codigo_gerado_id)
				VALUES (now(), ?, ?, ?)
				""", alternativa, job, codigo);
		return resultado;
	}

	private static UUID regra(UUID job, int versao) {
		return Objects.requireNonNull(dono.queryForObject(
				"""
						INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
						VALUES (?, ?, 'confirmacao_usuario',
						'{"vigencia":{"inicio":"2025-08","fim":"2025-08"},"loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.02}'::jsonb,
						'[]'::jsonb, ?, now()) RETURNING id
						""",
				UUID.class, job, versao, String.valueOf(versao).repeat(64)));
	}

	private static UUID iniciarTentativa(UUID rodada) {
		UUID submissao = Objects.requireNonNull(dono.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em)
				VALUES (?::uuid, 'texto', 'correcao reservada T215', now()) RETURNING id
				""", UUID.class, USUARIO_ID));
		dono.update("UPDATE rodadas_correcao SET estado = 'em_reextracao', submissao_correcao_id = ? WHERE id = ?",
				submissao, rodada);
		return submissao;
	}

	private static UUID historico(UUID job, UUID regra, String estado, @Nullable UUID anterior, String criada) {
		return Objects.requireNonNull(dono.queryForObject(
				"""
						INSERT INTO rodadas_correcao (job_id, regra_analisada_id, conflitos, estado, rodada_anterior_id, criada_em, atualizada_em)
						VALUES (?, ?, ?::jsonb, ?, ?, ?::timestamptz, ?::timestamptz) RETURNING id
						""",
				UUID.class, job, regra, CONFLITOS, estado, anterior, criada, criada));
	}

	private static List<java.util.Map<String, Object>> rodadas(UUID job) {
		return dono.queryForList("SELECT * FROM rodadas_correcao WHERE job_id = ? ORDER BY criada_em, id", job);
	}

	private static ObjectNode pausa(UUID job, UUID regra) {
		ObjectNode evento = JSON.createObjectNode()
			.put("job_id", job.toString())
			.put("etapa", "confirmacao")
			.put("status", "aguardando_correcao")
			.put("regra_id", regra.toString());
		evento.set("conflitos", JSON.readTree(CONFLITOS));
		return evento;
	}

	private static ObjectNode falha(UUID job, @Nullable UUID regra) {
		ObjectNode evento = JSON.createObjectNode()
			.put("job_id", job.toString())
			.put("etapa", "extracao_parametros")
			.put("status", "erro");
		if (regra != null) {
			evento.put("regra_id", regra.toString());
		}
		return evento;
	}

	private static double contagem(String resultado) {
		var contador = registry.find("etapa.alterada.correcao").tag("resultado", resultado).counter();
		return contador == null ? 0 : contador.count();
	}

	private static void publicarEEsperar(ObjectNode evento, String resultado) {
		double antes = contagem(resultado);
		Message mensagem = MessageBuilder.withBody(evento.toString().getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.ETAPA_ALTERADA, mensagem);
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(contagem(resultado)).isEqualTo(antes + 1));
	}

	private static void verificarLogs(CapturaDeLog captura, UUID job, String... resultados) throws Exception {
		List<String> encontrados = new ArrayList<>();
		for (var evento : captura.eventos()) {
			String linha = CapturaDeLog.emJson(evento);
			ContratoDeEvento.validarLog(linha);
			JsonNode json = JSON.readTree(linha);
			assertThat(json.path("job_id").asString()).isEqualTo(job.toString());
			assertThat(linha).doesNotContain("conflito reservado", "elementos", "futuro", "payload");
			JsonNode extra = json.path("extra");
			assertThat(extra.has("numero_conflitos")).isTrue();
			assertThat(extra.has("motivo_descarte")).isTrue();
			if (!"descartada".equals(extra.path("resultado").asString())) {
				assertThat(extra.path("numero_conflitos").asInt()).isEqualTo(1);
				assertThat(extra.path("regra_id").asString()).isNotBlank();
				assertThat(extra.path("rodada_id").asString()).isNotBlank();
			}
			encontrados.add(extra.path("resultado").asString());
		}
		assertThat(encontrados).containsExactly(resultados);
	}

	private static void verificarScrape(String... resultados) throws Exception {
		var resposta = HTTP.send(
				HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/metrics")).GET().build(),
				HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(200);
		for (String resultado : resultados) {
			assertThat(resposta.body())
				.contains("etapa_alterada_correcao_total{resultado=\"" + resultado + "\"} " + contagem(resultado));
			assertThat(resposta.body())
				.contains("etapa_alterada_consumo_duracao_seconds_count{resultado=\"" + resultado + "\"}");
		}
		assertThat(registry.get("etapa.alterada.correcao").counters()).allSatisfy(contador -> {
			assertThat(contador.getId().getTags()).hasSize(1);
			assertThat(contador.getId().getTag("resultado")).isIn("rodada_aberta", "duplicada", "descartada",
					"reextracao_falhou");
		});
	}

	// --- Apoio ----------------------------------------------------------------------

	private static void publicar(UUID jobId, String etapa, String status) {
		publicar(jobId, etapa, status, null);
	}

	private static void publicar(UUID jobId, String etapa, String status, @Nullable String causa) {
		String campoCausa = (causa != null) ? ",\"causa\":\"%s\"".formatted(causa) : "";
		String corpo = """
				{"job_id":"%s","etapa":"%s","status":"%s"%s}
				""".formatted(jobId, etapa, status, campoCausa).strip();
		Message mensagem = MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setCorrelationId(jobId.toString())
			.setType(RabbitTopologyConfig.ETAPA_ALTERADA)
			.build();
		rabbitTemplate.send("", RabbitTopologyConfig.ETAPA_ALTERADA, mensagem);
	}

	private static URI uri(UUID jobId) {
		return URI.create("http://localhost:" + porta + "/jobs/" + jobId + "/events");
	}

	private StreamCliente conectar(UUID jobId) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest.newBuilder(uri(jobId)).GET().build();
		HttpResponse<InputStream> resposta = HTTP.send(requisicao, HttpResponse.BodyHandlers.ofInputStream());
		StreamCliente cliente = new StreamCliente(resposta);
		this.abertos.add(cliente);
		return cliente;
	}

	private static UUID criarJob(JobStatus status) throws SQLException {
		UUID jobId = UUID.randomUUID();
		UUID submissaoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			// Todo job tem uma procedência: a consulta a devolve como `origem`.
			statement.execute("""
					INSERT INTO submissoes (id, usuario_id, tipo, conteudo, criado_em)
					VALUES ('%s', '%s', 'formulario', '{}'::jsonb, now())
					""".formatted(submissaoId, USUARIO_ID));
			statement.execute("""
					INSERT INTO jobs (id, status, usuario_id, submissao_id, competencias, orcamento, criado_em)
					VALUES ('%s', '%s', '%s', '%s', '{2025-08}', 1000, now())
					""".formatted(jobId, status.paraColuna(), USUARIO_ID, submissaoId));
		}
		return jobId;
	}

	/** A consulta do job exige ao menos uma versão de regra, com o núcleo completo. */
	private static void criarRegra(UUID jobId) throws SQLException {
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute(
					"""
							INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
							VALUES ('%s', 1, 'confirmacao_usuario',
							        '{"vigencia":{"inicio":"2025-08","fim":"2025-08"},"loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.02}'::jsonb,
							        '[]'::jsonb, '%s', now())
							"""
						.formatted(jobId, "0".repeat(64)));
		}
	}

	private static String statusPersistido(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement.executeQuery("SELECT status FROM jobs WHERE id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getString("status");
		}
	}

	private static int contarTransicoes(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement
					.executeQuery("SELECT count(*) FROM job_transicoes WHERE job_id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getInt(1);
		}
	}

	private static List<String> destinosDasTransicoes(UUID jobId) throws SQLException {
		List<String> destinos = new ArrayList<>();
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement
					.executeQuery("SELECT status_novo FROM job_transicoes WHERE job_id = '%s' ORDER BY ocorrido_em"
						.formatted(jobId))) {
			while (rs.next()) {
				destinos.add(Objects.requireNonNull(rs.getString("status_novo")));
			}
		}
		return destinos;
	}

	private static @Nullable String motivoDaUltimaTransicao(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				var rs = statement.executeQuery(
						"SELECT motivo FROM job_transicoes WHERE job_id = '%s' ORDER BY ocorrido_em DESC LIMIT 1"
							.formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return rs.getString("motivo");
		}
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static QueueInformation infoDaFilaDeEtapaAlterada() {
		return Objects.requireNonNull(amqpAdmin.getQueueInfo(RabbitTopologyConfig.ETAPA_ALTERADA),
				"fila " + RabbitTopologyConfig.ETAPA_ALTERADA + " não encontrada");
	}

}
