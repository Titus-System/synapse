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
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import ch.qos.logback.classic.spi.ILoggingEvent;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.amqp.core.AmqpAdmin;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueInformation;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.sse.EmissoresSse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * Sobe a aplicação inteira contra um Postgres e um RabbitMQ reais e publica na exchange
 * fanout {@code simulacao-concluida} como o worker publicaria, para confirmar o
 * comportamento ponta a ponta: da exchange à transição do job e ao stream SSE. Uma fila
 * {@code simulacao-concluida.codegen} é declarada ao lado da fila da api - sem consumidor
 * nenhum - para provar o critério nº 6: os dois lados da exchange fanout recebem cópias
 * independentes.
 */
@EnabledIf("dockerIsAvailable")
class SimulacaoConcluidaConsumidorTests {

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "55555555-5555-4555-8555-555555555555";

	private static final String FILA_CODEGEN = "simulacao-concluida.codegen";

	/** Um núcleo completo: a consulta do job o devolve no contrato, sem campo nulo. */
	private static final String NUCLEO = """
			{"vigencia":{"inicio":"2025-08","fim":"2025-08"},"loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.02}
			"""
		.strip();

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = new JsonMapper();

	/**
	 * Os totais que o worker grava para um job sem orçamento: os quatro de sempre e
	 * nenhum {@code orcamento}, porque o comando de execução não o trouxe.
	 */
	private static final String TOTAIS_SEM_ORCAMENTO = """
			{"baseline":480312.00,"simulado":492100.00,"diferenca_abs":11788.00,"diferenca_pct":0.0245}
			""".strip();

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	private static int porta;

	private static EmissoresSse emissoresSse;

	private static RabbitTemplate rabbitTemplate;

	private static AmqpAdmin amqpAdmin;

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
					"--app.sse.heartbeat=200ms");

		porta = Integer.parseInt(Objects.requireNonNull(contexto.getEnvironment().getProperty("local.server.port")));
		emissoresSse = contexto.getBean(EmissoresSse.class);
		rabbitTemplate = contexto.getBean(RabbitTemplate.class);
		amqpAdmin = contexto.getBean(AmqpAdmin.class);

		// Como o codegen declararia o próprio lado da mesma exchange fanout (T-049,
		// fora de escopo aqui) - sem consumidor nenhum, para provar o critério nº 6.
		amqpAdmin.declareQueue(new Queue(FILA_CODEGEN, true));
		amqpAdmin.declareBinding(new Binding(FILA_CODEGEN, Binding.DestinationType.QUEUE,
				RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE, "", null));

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
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API).getMessageCount())
				.isZero());
		amqpAdmin.purgeQueue(FILA_CODEGEN);
	}

	// --- Veredito e transição --------------------------------------------------------

	@Test
	void sucessoComVereditoViavelLevaAAguardandoDecisaoUsuario() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		UUID resultadoId = criarResultadoOrfao(jobId, "sucesso", "viavel");

		publicar(jobId, resultadoId, "sucesso", "viavel");

		String bloco = cliente.aguardarBloco("\"status\":\"aguardando_decisao_usuario\"", Duration.ofSeconds(10));
		assertThat(bloco).contains("event:estado").contains("\"status_anterior\":\"simulando\"");
		assertThat(statusPersistido(jobId)).isEqualTo("aguardando_decisao_usuario");
		List<Transicao> transicoes = transicoesRegistradas(jobId);
		assertThat(transicoes).hasSize(1);
		assertThat(transicoes.getFirst().ator()).isEqualTo("evento");
		assertThat(transicoes.getFirst().motivo()).isNull();
	}

	@Test
	void sucessoComVereditoIndeterminadoLevaAAguardandoDecisaoUsuario() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		UUID resultadoId = criarResultadoOrfao(jobId, "sucesso", "indeterminado");

		publicar(jobId, resultadoId, "sucesso", "indeterminado");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("aguardando_decisao_usuario"));
	}

	@Test
	void sucessoComVereditoInviavelLevaASimulacaoInviavelComMotivoNaTrilha() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		UUID resultadoId = criarResultadoOrfao(jobId, "sucesso", "inviavel");

		publicar(jobId, resultadoId, "sucesso", "inviavel");

		String bloco = cliente.aguardarBloco("\"status\":\"simulacao_inviavel\"", Duration.ofSeconds(10));
		assertThat(bloco).contains("Orçamento do período não comporta a regra proposta.");
		Transicao transicao = transicaoUnica(jobId);
		assertThat(transicao.destino()).isEqualTo("simulacao_inviavel");
		assertThat(transicao.motivo()).isEqualTo("inviavel");
	}

	/** Critério nº 3: asserção violada é erro, e não inviabilidade. */
	@Test
	void assercaoVioladaLevaAErroENaoASimulacaoInviavel() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		UUID resultadoId = criarResultadoOrfao(jobId, "assercao_violada", null);

		publicar(jobId, resultadoId, "assercao_violada", null);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("erro"));
		assertThat(transicaoUnica(jobId).motivo()).isEqualTo("assercao_violada");
	}

	/** Critério nº 4: os dois ficam registrados de forma distinguível. */
	@Test
	void erroCodigoEErroInfraLevamAErroComMotivosDistintosNaTrilha() throws Exception {
		UUID jobUm = criarJob(JobStatus.SIMULANDO);
		UUID resultadoUm = criarResultadoOrfao(jobUm, "erro_codigo", null);
		UUID jobDois = criarJob(JobStatus.SIMULANDO);
		UUID resultadoDois = criarResultadoOrfao(jobDois, "erro_infra", null);

		publicar(jobUm, resultadoUm, "erro_codigo", null);
		publicar(jobDois, resultadoDois, "erro_infra", null);

		await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
			assertThat(statusPersistido(jobUm)).isEqualTo("erro");
			assertThat(statusPersistido(jobDois)).isEqualTo("erro");
		});
		assertThat(transicaoUnica(jobUm).motivo()).isEqualTo("erro_codigo");
		assertThat(transicaoUnica(jobDois).motivo()).isEqualTo("erro_infra");
	}

	/** Destino terminal: o servidor encerra o stream depois do evento {@code estado}. */
	@Test
	void destinoErroFechaOStream() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		UUID resultadoId = criarResultadoOrfao(jobId, "erro_infra", null);

		publicar(jobId, resultadoId, "erro_infra", null);

		cliente.aguardarBloco("\"status\":\"erro\"", Duration.ofSeconds(10));
		cliente.aguardarFimDoStream(Duration.ofSeconds(10));
	}

	// --- Consulta do job depois da parada ---------------------------------------------

	/**
	 * O motivo que o usuário viu no stream tem de ser o que a consulta devolve depois de
	 * reconectar: a tela recarregada não perde a explicação da parada.
	 */
	@ParameterizedTest
	@CsvSource({ "sucesso,inviavel", "assercao_violada,", "erro_codigo,", "erro_infra," })
	void aConsultaDoJobDevolveOMesmoMotivoQueOSseAnunciou(String status, @Nullable String veredito) throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		UUID resultadoId = criarResultadoOrfao(jobId, status, veredito);

		publicar(jobId, resultadoId, status, veredito);

		String bloco = cliente.aguardarBloco("\"status_anterior\":\"simulando\"", Duration.ofSeconds(10));
		String motivoDoSse = ClienteDoJob.dadosDoBloco(bloco).path("motivo").asString();
		assertThat(motivoDoSse).isNotBlank();

		JsonNode job = ClienteDoJob.consultar(porta, jobId);

		assertThat(job.path("motivo").asString()).isEqualTo(motivoDoSse);
		assertThat(job.path("status").asString()).isEqualTo(statusPersistido(jobId));
	}

	@Test
	void reentregaDeUmDesfechoTerminalNaoAlteraOsTimestampsDaConsulta() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		UUID resultadoId = criarResultadoOrfao(jobId, "erro_infra", null);
		publicar(jobId, resultadoId, "erro_infra", null);
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("erro"));
		JsonNode primeira = ClienteDoJob.consultar(porta, jobId);
		String finalizadoEm = primeira.path("finalizado_em").asString();
		assertThat(finalizadoEm).isNotBlank();

		publicar(jobId, resultadoId, "erro_infra", null);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API).getMessageCount())
				.isZero());
		await().during(Duration.ofMillis(500))
			.atMost(Duration.ofSeconds(5))
			.untilAsserted(() -> assertThat(ClienteDoJob.consultar(porta, jobId).path("finalizado_em").asString())
				.isEqualTo(finalizadoEm));
		assertThat(ClienteDoJob.consultar(porta, jobId).path("motivo").asString())
			.isEqualTo(primeira.path("motivo").asString());
	}

	// --- Idempotência e isolamento entre consumidores --------------------------------

	/** Critério nº 5: o mesmo evento entregue duas vezes produz uma única transição. */
	@Test
	void aMesmaMensagemPublicadaDuasVezesProduzUmaUnicaTransicao() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		UUID resultadoId = criarResultadoOrfao(jobId, "sucesso", "viavel");

		publicar(jobId, resultadoId, "sucesso", "viavel");
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("aguardando_decisao_usuario"));
		publicar(jobId, resultadoId, "sucesso", "viavel");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API).getMessageCount())
				.isZero());
		assertThat(statusPersistido(jobId)).isEqualTo("aguardando_decisao_usuario");
		assertThat(transicoesRegistradas(jobId)).hasSize(1);
	}

	/**
	 * Critério nº 6: derrubar o consumidor do codegen não impede a api de receber, e
	 * vice-versa - os dois lados da exchange fanout recebem cópias independentes.
	 */
	@Test
	void aFilaDoCodegenRecebeUmaCopiaIndependenteSemConsumidor() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		UUID resultadoId = criarResultadoOrfao(jobId, "sucesso", "viavel");

		publicar(jobId, resultadoId, "sucesso", "viavel");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("aguardando_decisao_usuario"));
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(FILA_CODEGEN).getMessageCount()).isEqualTo(1));
	}

	// --- O evento "resultado" e a cadeia de simulação --------------------------------

	@Test
	void cadeiaCompletaEmiteResultadoAntesDeEstadoEAmarraOResultadoNaSimulacao() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		Simulacao simulacao = criarSimulacaoPendente(jobId);
		UUID resultadoId = criarResultado(jobId, simulacao.codigoGeradoId(), "sucesso", "inviavel");

		publicar(jobId, resultadoId, "sucesso", "inviavel");

		String blocoResultado = cliente.aguardarBloco("event:resultado", Duration.ofSeconds(10));
		assertThat(blocoResultado).contains("\"simulacao_id\":\"" + simulacao.id() + "\"")
			.contains("\"status\":\"sucesso\"")
			.contains("\"veredito\":\"inviavel\"");
		cliente.aguardarBloco("\"status\":\"simulacao_inviavel\"", Duration.ofSeconds(10));

		int indiceResultado = cliente.conteudo().indexOf("event:resultado");
		int indiceEstado = cliente.conteudo().indexOf("event:estado", indiceResultado);
		assertThat(indiceResultado).isGreaterThanOrEqualTo(0);
		assertThat(indiceEstado).isGreaterThan(indiceResultado);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(resultadoIdDaSimulacao(simulacao.id())).isEqualTo(resultadoId));
	}

	/**
	 * As filas de {@code etapa-alterada} e {@code simulacao-concluida} não têm ordem
	 * entre si: o resultado pode chegar com o job ainda em {@code gerando_regra}. O job
	 * passa por {@code simulando} e o stream anuncia as duas transições, na ordem.
	 */
	@Test
	void resultadoQueChegaComOJobEmGerandoRegraPassaPorSimulando() throws Exception {
		UUID jobId = criarJob(JobStatus.GERANDO_REGRA);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		Simulacao simulacao = criarSimulacaoPendente(jobId);
		UUID resultadoId = criarResultado(jobId, simulacao.codigoGeradoId(), "sucesso", "inviavel");

		publicar(jobId, resultadoId, "sucesso", "inviavel");

		cliente.aguardarBloco("\"status\":\"simulacao_inviavel\"", Duration.ofSeconds(10));
		String conteudo = cliente.conteudo();
		int paraSimulando = conteudo.indexOf("\"status\":\"simulando\"");
		int resultado = conteudo.indexOf("event:resultado");
		int paraInviavel = conteudo.indexOf("\"status\":\"simulacao_inviavel\"");
		assertThat(paraSimulando).isPositive().isLessThan(resultado);
		assertThat(resultado).isLessThan(paraInviavel);
		List<Transicao> transicoes = transicoesRegistradas(jobId);
		assertThat(transicoes).extracting(Transicao::destino).containsExactly("simulando", "simulacao_inviavel");
		assertThat(transicoes.getFirst().motivo()).isEqualTo("simulacao_concluida_antecipada");
	}

	/**
	 * O schema do evento HTTP {@code EventoResultado} declara {@code veredito} ausente
	 * fora de {@code status: sucesso}. Um veredito presente por engano num status de erro
	 * - dado não confiável, vindo do worker - não pode vazar para o SSE, mesmo quando há
	 * uma simulação amarrada para emitir o evento {@code resultado}.
	 */
	@Test
	void erroComSimulacaoLigadaNaoRepassaUmVereditoIndevidoAoResultado() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		Simulacao simulacao = criarSimulacaoPendente(jobId);
		UUID resultadoId = criarResultado(jobId, simulacao.codigoGeradoId(), "erro_codigo", null);

		publicar(jobId, resultadoId, "erro_codigo", "viavel");

		String blocoResultado = cliente.aguardarBloco("event:resultado", Duration.ofSeconds(10));
		assertThat(blocoResultado).contains("\"status\":\"erro_codigo\"").doesNotContain("veredito");
	}

	/**
	 * Estado atual do sistema: nada insere em {@code simulacoes} até a T-046. A transição
	 * e o evento {@code estado} - os critérios desta tarefa - saem do mesmo jeito; só o
	 * evento {@code resultado} fica ausente.
	 */
	@Test
	void semSimulacaoCorrespondenteATransicaoOcorreSemEmitirResultado() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		UUID resultadoId = criarResultadoOrfao(jobId, "sucesso", "viavel");

		publicar(jobId, resultadoId, "sucesso", "viavel");

		cliente.aguardarBloco("\"status\":\"aguardando_decisao_usuario\"", Duration.ofSeconds(10));
		assertThat(cliente.conteudo()).doesNotContain("event:resultado");
	}

	// --- Job sem orçamento -------------------------------------------------------------

	/**
	 * Sem orçamento, o worker confere o resultado e o publica como {@code sucesso} sem
	 * veredito. O job vai à decisão do usuário sem motivo de parada, o evento
	 * {@code resultado} sai sem veredito, e a consulta e a listagem respondem conforme o
	 * contrato, sem orçamento e sem veredito. O consumo aparece no log e na métrica com o
	 * desfecho {@code sem_orcamento}.
	 */
	@Test
	void sucessoSemVereditoDeJobSemOrcamentoLevaADecisaoDoUsuario() throws Exception {
		UUID jobId = criarJobSemOrcamento();
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		Simulacao simulacao = criarSimulacaoPendente(jobId);
		UUID resultadoId = criarResultadoSemOrcamento(jobId, simulacao.codigoGeradoId());
		double aplicadasAntes = consumos("sem_orcamento", "aplicada");

		List<ILoggingEvent> logs;
		try (CapturaDeLog captura = new CapturaDeLog(SimulacaoConcluidaConsumidor.class)) {
			publicar(jobId, resultadoId, "sucesso", null);
			String blocoEstado = cliente.aguardarBloco("\"status\":\"aguardando_decisao_usuario\"",
					Duration.ofSeconds(10));
			JsonNode estado = ClienteDoJob.dadosDoBloco(blocoEstado);
			ContratoDeEvento.validarEventoDoStream("estado", estado.toString());
			assertThat(estado.path("status_anterior").asString()).isEqualTo("simulando");
			assertThat(estado.has("motivo")).isFalse();
			await().atMost(Duration.ofSeconds(5))
				.untilAsserted(() -> assertThat(captura.eventos()).extracting(ILoggingEvent::getFormattedMessage)
					.contains("simulacao-concluida aplicada"));
			logs = captura.eventos();
		}

		String blocoResultado = cliente.aguardarBloco("event:resultado", Duration.ofSeconds(10));
		JsonNode resultado = ClienteDoJob.dadosDoBloco(blocoResultado);
		ContratoDeEvento.validarEventoDoStream("resultado", resultado.toString());
		assertThat(resultado.path("simulacao_id").asString()).isEqualTo(simulacao.id().toString());
		assertThat(resultado.path("status").asString()).isEqualTo("sucesso");
		assertThat(resultado.has("veredito")).isFalse();
		Transicao transicao = transicaoUnica(jobId);
		assertThat(transicao.destino()).isEqualTo("aguardando_decisao_usuario");
		assertThat(transicao.motivo()).isNull();

		JsonNode job = ClienteDoJob.consultar(porta, jobId);
		assertThat(job.path("status").asString()).isEqualTo("aguardando_decisao_usuario");
		assertThat(job.has("orcamento")).isFalse();
		assertThat(job.has("motivo")).isFalse();
		JsonNode simulacaoDoJob = job.path("simulacao");
		assertThat(simulacaoDoJob.path("status").asString()).isEqualTo("sucesso");
		assertThat(simulacaoDoJob.has("veredito")).isFalse();
		JsonNode totais = simulacaoDoJob.path("resultado").path("totais");
		assertThat(totais.has("orcamento")).isFalse();
		assertThat(totais.path("simulado").decimalValue()).isEqualByComparingTo("492100.00");

		JsonNode item = itemDaListagem(jobId);
		assertThat(item.path("status").asString()).isEqualTo("aguardando_decisao_usuario");
		assertThat(item.has("orcamento")).isFalse();
		assertThat(item.has("veredito")).isFalse();

		assertThat(consumos("sem_orcamento", "aplicada")).isEqualTo(aplicadasAntes + 1);
		ILoggingEvent aplicada = logs.stream()
			.filter(registro -> "simulacao-concluida aplicada".equals(registro.getFormattedMessage()))
			.findFirst()
			.orElseThrow();
		String linha = CapturaDeLog.emJson(aplicada);
		ContratoDeEvento.validarLog(linha);
		JsonNode envelope = JSON.readTree(linha);
		assertThat(envelope.path("job_id").asString()).isEqualTo(jobId.toString());
		assertThat(linha).contains("\"desfecho\":\"sem_orcamento\"")
			.contains("\"status\":\"aguardando_decisao_usuario\"")
			.contains("\"resultado_id\":\"" + resultadoId + "\"")
			.as("o log leva referências e o desfecho, nunca os números apurados")
			.doesNotContain("492100", "480312");
	}

	/**
	 * Um resultado sem orçamento pode ser liberado e salvo como campanha, como uma regra
	 * viável: as duas ações levam o job a {@code liberado} e ficam registradas.
	 */
	@ParameterizedTest
	@ValueSource(strings = { "confirmar_liberar", "salvar" })
	void resultadoSemOrcamentoPodeSerLiberadoOuSalvo(String acao) throws Exception {
		UUID jobId = criarJobSemOrcamento();
		UUID resultadoId = criarResultadoSemOrcamento(jobId, criarCodigoGerado(jobId));
		publicar(jobId, resultadoId, "sucesso", null);
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("aguardando_decisao_usuario"));

		HttpResponse<String> resposta = executarAcao(jobId, acao);

		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("JobDetalhado", resposta.body());
		assertThat(JSON.readTree(resposta.body()).path("status").asString()).isEqualTo("liberado");
		assertThat(statusPersistido(jobId)).isEqualTo("liberado");
		assertThat(acoesRegistradas(jobId)).containsExactly(acao);
	}

	/**
	 * O caminho de hoje não muda: um veredito {@code inviavel} continua parando o job em
	 * {@code simulacao_inviavel}, e liberar ou salvar essa simulação continua recusado.
	 */
	@ParameterizedTest
	@ValueSource(strings = { "confirmar_liberar", "salvar" })
	void aLiberacaoDeUmaSimulacaoInviavelContinuaRecusada(String acao) throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		UUID resultadoId = criarResultadoOrfao(jobId, "sucesso", "inviavel");
		publicar(jobId, resultadoId, "sucesso", "inviavel");
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("simulacao_inviavel"));

		HttpResponse<String> resposta = executarAcao(jobId, acao);

		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(409);
		assertThat(JSON.readTree(resposta.body()).path("codigo").asString()).isEqualTo("simulacao_inviavel");
		assertThat(statusPersistido(jobId)).isEqualTo("simulacao_inviavel");
		assertThat(acoesRegistradas(jobId)).isEmpty();
	}

	/**
	 * A métrica distingue o desfecho já aplicado de uma reentrega: a segunda entrega do
	 * mesmo resultado sem orçamento sai como {@code estado_incompativel} e não move o
	 * job.
	 */
	@Test
	void reentregaDoResultadoSemOrcamentoNaoContaOutraAplicacao() throws Exception {
		UUID jobId = criarJobSemOrcamento();
		UUID resultadoId = criarResultadoSemOrcamento(jobId, criarCodigoGerado(jobId));
		double aplicadasAntes = consumos("sem_orcamento", "aplicada");
		double incompativeisAntes = consumos("sem_orcamento", "estado_incompativel");

		publicar(jobId, resultadoId, "sucesso", null);
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("aguardando_decisao_usuario"));
		publicar(jobId, resultadoId, "sucesso", null);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(consumos("sem_orcamento", "estado_incompativel"))
				.isEqualTo(incompativeisAntes + 1));
		assertThat(consumos("sem_orcamento", "aplicada")).isEqualTo(aplicadasAntes + 1);
		assertThat(transicoesRegistradas(jobId)).hasSize(1);
	}

	// --- Entradas descartadas ---------------------------------------------------------

	@Test
	void statusForaDoVocabularioEDescartadoSemTransicaoNemStream() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));

		String corpo = """
				{"job_id":"%s","resultado_id":"%s","status":"cancelado"}
				""".formatted(jobId, UUID.randomUUID()).strip();
		enviarCorpo(corpo);

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API).getMessageCount())
				.isZero());
		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		// A fotografia da conexão já é um "event:estado" (o snapshot ao conectar); o que
		// se verifica aqui é que nenhum SEGUNDO apareceu por causa do evento descartado.
		assertThat(cliente.contarOcorrencias("event:estado")).isEqualTo(1);
		assertThat(cliente.conteudo()).doesNotContain("event:resultado");
	}

	@Test
	void jsonMalformadoEDescartadoSemDerrubarOConsumidor() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		enviarCorpo("isto não é json");

		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(infoDaFila(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API).getMessageCount())
				.isZero());

		UUID resultadoId = criarResultadoOrfao(jobId, "sucesso", "viavel");
		publicar(jobId, resultadoId, "sucesso", "viavel");
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(statusPersistido(jobId)).isEqualTo("aguardando_decisao_usuario"));
	}

	@ParameterizedTest
	@CsvSource({ "true,false", "false,false", "true,true", "false,true" })
	void candidatasNaoMudamJobESugestaoAceitaSubstituiResultadoSemNovaSimulacao(boolean comMetaVenda,
			boolean sugestaoAntecipada) throws Exception {
		JobStatus estadoInicial = sugestaoAntecipada ? JobStatus.GERANDO_REGRA : JobStatus.SIMULANDO;
		UUID jobId = criarJob(estadoInicial);
		Simulacao simulacao = criarSimulacaoPendente(jobId);
		UUID vigente = criarResultado(jobId, simulacao.codigoGeradoId(), "sucesso", "viavel");
		UUID candidata = criarResultado(jobId, simulacao.codigoGeradoId(), "sucesso", "viavel");
		UUID regraId;
		try (Connection conexao = comoDono(); Statement sql = conexao.createStatement()) {
			if (comMetaVenda) {
				sql.execute("UPDATE jobs SET meta_venda = 1000 WHERE id = '%s'".formatted(jobId));
			}
			sql.execute(
					"UPDATE resultados_simulacao SET meta_venda = %s, totais = '{\"baseline\":10,\"simulado\":20,\"diferenca_abs\":10,\"diferenca_pct\":1,\"orcamento\":1000,\"vendas_historicas\":500}' WHERE id = '%s'"
						.formatted(comMetaVenda ? "1000" : "NULL", vigente));
			sql.execute(
					"UPDATE resultados_simulacao SET meta_venda = 2000, proposito = 'busca_meta', totais = '{\"baseline\":10,\"simulado\":40,\"diferenca_abs\":30,\"diferenca_pct\":3,\"orcamento\":1000,\"vendas_historicas\":500}' WHERE id = '%s'"
						.formatted(candidata));
			try (ResultSet rs = sql
				.executeQuery("SELECT regra_id FROM simulacoes WHERE id = '%s'".formatted(simulacao.id()))) {
				assertThat(rs.next()).isTrue();
				regraId = rs.getObject(1, UUID.class);
			}
		}
		try (Connection connection = comoDono(); Statement sql = connection.createStatement()) {
			sql.execute(
					"UPDATE resultados_simulacao SET decomposicao = '{\"elemento\":{},\"loja\":{},\"marca\":{},\"cargo\":{},\"competencia\":{}}' WHERE job_id = '%s'"
						.formatted(jobId));
		}
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		var registro = contexto.getBean(io.micrometer.core.instrument.MeterRegistry.class);
		double antes = contexto.getBean(synapse.api.core.metrics.AppMetrics.class).execucaoCandidataConsumida().count();
		double registradasAntes = contexto.getBean(synapse.api.core.metrics.AppMetrics.class)
			.metaVendaSugeridaConsumida("registrada")
			.count();
		long duracoesAntes = registro.find("spring.rabbitmq.listener")
			.tag("queue", RabbitTopologyConfig.META_VENDA_SUGERIDA)
			.timers()
			.stream()
			.mapToLong(io.micrometer.core.instrument.Timer::count)
			.sum();
		try (CapturaDeLog captura = new CapturaDeLog("synapse.api.job")) {
			for (int i = 0; i < 3; i++) {
				enviarCorpo(
						"""
								{"job_id":"%s","resultado_id":"%s","status":"sucesso","veredito":"viavel","proposito":"busca_meta","meta_venda":2000}
								"""
							.formatted(jobId, candidata));
			}
			await().atMost(Duration.ofSeconds(10))
				.untilAsserted(() -> assertThat(registro.get("simulacao.candidata.consumo").counter().count())
					.isEqualTo(antes + 3));
			assertThat(statusPersistido(jobId)).isEqualTo(estadoInicial.paraColuna());
			assertThat(resultadoIdDaSimulacao(simulacao.id())).isNull();
			assertThat(cliente.conteudo()).doesNotContain("event:resultado").doesNotContain("status_anterior");
			assertThat(ClienteDoJob.consultar(porta, jobId).has("simulacao")).isFalse();
			String proposta = """
					{"job_id":"%s","regra_id":"%s","resultado_id":"%s","meta_venda":2000}
					""".formatted(jobId, regraId, candidata);
			if (sugestaoAntecipada) {
				publicarMeta(proposta);
				cliente.aguardarBloco("\"status\":\"meta_sugerida\"", Duration.ofSeconds(10));
				assertThat(statusPersistido(jobId)).isEqualTo(estadoInicial.paraColuna());
				assertThat(resultadoIdDaSimulacao(simulacao.id())).isNull();
				assertThat(transicoesRegistradas(jobId)).isEmpty();
				assertThat(executarAcao(jobId, "aceitar_meta").statusCode()).isEqualTo(409);
			}
			publicar(jobId, vigente, "sucesso", "viavel");
			cliente.aguardarBloco("event:resultado", Duration.ofSeconds(10));
			JsonNode original = ClienteDoJob.consultar(porta, jobId);
			assertThat(original.path("simulacao").has("meta_sugerida_aceita_em")).isFalse();
			assertThat(original.path("simulacao").has("meta_venda")).isEqualTo(comMetaVenda);
			if (comMetaVenda) {
				assertThat(original.path("simulacao").path("meta_venda").asInt()).isEqualTo(1000);
			}
			assertThat(original.path("simulacao").path("resultado").path("totais").path("vendas_historicas").asInt())
				.isEqualTo(500);
			if (!sugestaoAntecipada) {
				publicarMeta(proposta);
			}
			String bloco = cliente.aguardarBloco("\"status\":\"meta_sugerida\"", Duration.ofSeconds(10));
			ContratoDeEvento.validarEventoDoStream("etapa", ClienteDoJob.dadosDoBloco(bloco).toString());
			JsonNode sugerida = ClienteDoJob.consultar(porta, jobId).path("meta_sugerida");
			assertThat(sugerida.path("meta_venda").asInt()).isEqualTo(2000);
			assertThat(sugerida.path("total_simulado").asInt()).isEqualTo(40);
			assertThat(sugerida.path("orcamento").asInt()).isEqualTo(1000);
			assertThat(registro.get("meta.venda.sugerida.consumo").tag("resultado", "registrada").counter().count())
				.isEqualTo(registradasAntes + 1);
			double descartadas = contexto.getBean(synapse.api.core.metrics.AppMetrics.class)
				.metaVendaSugeridaConsumida("descartada")
				.count();
			publicarMeta(proposta);
			await().atMost(Duration.ofSeconds(10))
				.untilAsserted(() -> assertThat(
						registro.get("meta.venda.sugerida.consumo").tag("resultado", "descartada").counter().count())
					.isEqualTo(descartadas + 1));
			assertThat(cliente.contarOcorrencias("\"status\":\"meta_sugerida\"")).isEqualTo(1);
			var transacao = new org.springframework.transaction.support.TransactionTemplate(
					contexto.getBean(org.springframework.transaction.PlatformTransactionManager.class));
			transacao.executeWithoutResult(status -> {
				contexto.getBean(JobService.class).executarAcao(jobId, AcaoJob.ACEITAR_META);
				status.setRollbackOnly();
			});
			assertThat(resultadoIdDaSimulacao(simulacao.id())).isEqualTo(vigente);
			assertThat(acoesRegistradas(jobId)).isEmpty();
			assertThat(ClienteDoJob.consultar(porta, jobId).has("meta_sugerida")).isTrue();
			assertThat(ClienteDoJob.consultar(porta, jobId).path("simulacao").has("meta_sugerida_aceita_em")).isFalse();
			var primeira = java.util.concurrent.CompletableFuture.supplyAsync(() -> aceitarMetaConcorrentemente(jobId));
			var segunda = java.util.concurrent.CompletableFuture.supplyAsync(() -> aceitarMetaConcorrentemente(jobId));
			List<HttpResponse<String>> respostas = List.of(primeira.join(), segunda.join());
			assertThat(respostas).extracting(HttpResponse::statusCode).containsExactlyInAnyOrder(200, 409);
			HttpResponse<String> resposta = respostas.stream()
				.filter(r -> r.statusCode() == 200)
				.findFirst()
				.orElseThrow();
			assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
			ContratoDeEvento.validarRespostaHttp("JobDetalhado", resposta.body());
			JsonNode aceito = JSON.readTree(resposta.body());
			assertThat(aceito.has("meta_sugerida")).isFalse();
			assertThat(aceito.path("status").asString()).isEqualTo("aguardando_decisao_usuario");
			assertThat(aceito.path("simulacoes").size()).isEqualTo(1);
			assertThat(aceito.path("simulacao").path("id").asString()).isEqualTo(simulacao.id().toString());
			assertThat(aceito.path("simulacao").path("meta_venda").asInt()).isEqualTo(2000);
			JsonNode anterior = aceito.path("simulacao").path("anterior_a_meta_sugerida");
			assertThat(anterior.path("resultado_id").asString()).isEqualTo(vigente.toString());
			assertThat(anterior.has("meta_venda")).isEqualTo(comMetaVenda);
			if (comMetaVenda)
				assertThat(anterior.path("meta_venda").asInt()).isEqualTo(1000);
			assertThat(anterior.path("resultado").path("totais").path("simulado").asInt()).isEqualTo(20);
			String aceitaEm = aceito.path("simulacao").path("meta_sugerida_aceita_em").asString();
			assertThat(java.time.Instant.parse(aceitaEm)).isNotNull();
			assertThat(aceito.path("simulacoes").get(0).path("meta_sugerida_aceita_em").asString()).isEqualTo(aceitaEm);
			assertThat(aceito.path("simulacao").path("resultado").path("totais").path("simulado").asInt())
				.isEqualTo(40);
			assertThat(aceito.has("meta_venda")).isEqualTo(comMetaVenda);
			if (comMetaVenda) {
				assertThat(aceito.path("meta_venda").asInt()).isEqualTo(1000);
			}
			assertThat(acoesRegistradas(jobId)).containsExactly("aceitar_meta");
			assertThat(resultadoIdDaSimulacao(simulacao.id())).isEqualTo(candidata);
			await().atMost(Duration.ofSeconds(5))
				.untilAsserted(() -> assertThat(cliente.contarOcorrencias("event:resultado")).isEqualTo(2));
			assertThat(emissoresSse.conexoesAtivas()).isEqualTo(1);
			assertThat(transicoesRegistradas(jobId)).hasSize(sugestaoAntecipada ? 2 : 1);
			assertThat(executarAcao(jobId, "aceitar_meta").statusCode()).isEqualTo(409);
			publicarMeta(proposta);
			await().atMost(Duration.ofSeconds(10))
				.untilAsserted(() -> assertThat(
						registro.get("meta.venda.sugerida.consumo").tag("resultado", "descartada").counter().count())
					.isEqualTo(descartadas + 2));
			assertThat(ClienteDoJob.consultar(porta, jobId).has("meta_sugerida")).isFalse();
			assertThat(registro.get("meta.venda.sugerida.consumo").tag("resultado", "registrada").counter().count())
				.isEqualTo(registradasAntes + 1);
			HttpResponse<String> finalizada = executarAcao(jobId, "salvar");
			assertThat(finalizada.statusCode()).as(finalizada.body()).isEqualTo(200);
			JsonNode historico = ClienteDoJob.consultar(porta, jobId);
			assertThat(historico.path("status").asString()).isEqualTo("liberado");
			assertThat(historico.path("regras")).hasSize(1);
			assertThat(historico.path("simulacao").path("meta_sugerida_aceita_em").asString()).isEqualTo(aceitaEm);
			assertThat(historico.path("simulacao").path("meta_venda").asInt()).isEqualTo(2000);
			assertThat(historico.path("simulacao").path("anterior_a_meta_sugerida")).isEqualTo(anterior);
			for (ILoggingEvent log : captura.eventos()) {
				String linha = CapturaDeLog.emJson(log);
				ContratoDeEvento.validarLog(linha);
				assertThat(JSON.readTree(linha).path("job_id").asString()).isEqualTo(jobId.toString());
				assertThat(linha).doesNotContain("\"totais\"", "\"nucleo\"", "\"conteudo\"", "\"fonte\"");
			}
		}
		await().atMost(Duration.ofSeconds(5))
			.untilAsserted(() -> assertThat(registro.find("spring.rabbitmq.listener")
				.tag("queue", RabbitTopologyConfig.META_VENDA_SUGERIDA)
				.timers()
				.stream()
				.mapToLong(io.micrometer.core.instrument.Timer::count)
				.sum()).isEqualTo(duracoesAntes + 3));
		assertThat(registro.get("meta.venda.aceita").counter().count()).isGreaterThanOrEqualTo(1);
		String metricas = HTTP
			.send(HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/metrics")).GET().build(),
					HttpResponse.BodyHandlers.ofString())
			.body();
		assertThat(metricas).contains("simulacao_candidata_consumo_total", "meta_venda_sugerida_consumo_total",
				"meta_venda_aceita_total");
		double sugeridasExpostas = metricas.lines()
			.filter(linha -> linha.startsWith("meta_venda_sugerida_consumo_total{")
					&& linha.contains("resultado=\"registrada\""))
			.mapToDouble(linha -> Double.parseDouble(linha.substring(linha.lastIndexOf(' ') + 1)))
			.sum();
		assertThat(sugeridasExpostas).isEqualTo(registradasAntes + 1);
		double duracoesExpostas = metricas.lines()
			.filter(linha -> linha.startsWith("spring_rabbitmq_listener_seconds_count{")
					&& linha.contains("queue=\"" + RabbitTopologyConfig.META_VENDA_SUGERIDA + "\""))
			.mapToDouble(linha -> Double.parseDouble(linha.substring(linha.lastIndexOf(' ') + 1)))
			.sum();
		assertThat(duracoesExpostas).isEqualTo(duracoesAntes + 3);
	}

	@ParameterizedTest
	@ValueSource(strings = { "gerando_regra", "simulando", "aguardando_decisao_usuario" })
	void desfechoSemSolucaoApareceNoJobESseSemPermitirAceitar(String estadoInicial) throws Exception {
		UUID jobId = criarJob(JobStatus.deColuna(estadoInicial));
		UUID regraId = criarRegra(jobId);
		assertThat(executarAcao(jobId, "aceitar_meta").statusCode()).isEqualTo(409);
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		publicarMeta("""
				{"job_id":"%s","regra_id":"%s","sem_solucao":{"motivo":"nao_monotonica"}}
				""".formatted(jobId, regraId));
		cliente.aguardarBloco("\"status\":\"sem_solucao\"", Duration.ofSeconds(10));
		JsonNode sugestao = ClienteDoJob.consultar(porta, jobId).path("meta_sugerida");
		assertThat(sugestao.path("sem_solucao").path("motivo").asString()).isEqualTo("nao_monotonica");
		assertThat(sugestao.has("meta_venda")).isFalse();
		assertThat(statusPersistido(jobId)).isEqualTo(estadoInicial);
		assertThat(transicoesRegistradas(jobId)).isEmpty();
		assertThat(executarAcao(jobId, "aceitar_meta").statusCode()).isEqualTo(409);
		assertThat(acoesRegistradas(jobId)).isEmpty();
	}

	@ParameterizedTest
	@ValueSource(strings = { "400", "500" })
	void sugestaoSemMetaInformadaExigeAumentoSobreVendasHistoricas(String metaCandidata) throws Exception {
		UUID jobId = criarJob(JobStatus.AGUARDANDO_DECISAO_USUARIO);
		Simulacao simulacao = criarSimulacaoPendente(jobId);
		UUID candidata = criarResultado(jobId, simulacao.codigoGeradoId(), "sucesso", "viavel");
		UUID regraId;
		try (Connection conexao = comoDono(); Statement sql = conexao.createStatement()) {
			sql.execute(
					"""
							UPDATE resultados_simulacao SET meta_venda = %s, proposito = 'busca_meta',
							    totais = '{"baseline":10,"simulado":20,"diferenca_abs":10,"diferenca_pct":1,"orcamento":1000,"vendas_historicas":500}'
							WHERE id = '%s'
							"""
						.formatted(metaCandidata, candidata));
			try (ResultSet rs = sql
				.executeQuery("SELECT regra_id FROM simulacoes WHERE id = '%s'".formatted(simulacao.id()))) {
				assertThat(rs.next()).isTrue();
				regraId = rs.getObject(1, UUID.class);
			}
		}
		StreamCliente cliente = conectar(jobId);
		cliente.aguardarBloco("event:estado", Duration.ofSeconds(5));
		double antes = contexto.getBean(synapse.api.core.metrics.AppMetrics.class)
			.metaVendaSugeridaConsumida("descartada")
			.count();
		publicarMeta("""
				{"job_id":"%s","regra_id":"%s","resultado_id":"%s","meta_venda":%s}
				""".formatted(jobId, regraId, candidata, metaCandidata));
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(contexto.getBean(synapse.api.core.metrics.AppMetrics.class)
				.metaVendaSugeridaConsumida("descartada")
				.count()).isEqualTo(antes + 1));
		assertThat(ClienteDoJob.consultar(porta, jobId).has("meta_sugerida")).isFalse();
		assertThat(cliente.conteudo()).doesNotContain("meta_sugerida");
		assertThat(resultadoIdDaSimulacao(simulacao.id())).isNull();
		assertThat(executarAcao(jobId, "aceitar_meta").statusCode()).isEqualTo(409);
	}

	@ParameterizedTest
	@CsvSource({ "liberado,false", "cancelado,false", "arquivado,false", "gerando_regra,true" })
	void sugestaoDeMetaDescartaJobEncerradoOuVersaoAnterior(String estadoInicial, boolean versaoAnterior)
			throws Exception {
		UUID jobId = criarJob(JobStatus.deColuna(estadoInicial));
		UUID regraId = criarRegra(jobId);
		if (versaoAnterior) {
			try (Connection conexao = comoDono(); Statement sql = conexao.createStatement()) {
				sql.execute("""
						INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
						SELECT job_id, 2, origem, nucleo, especificacoes, '%s', now() FROM regras WHERE id = '%s'
						""".formatted("1".repeat(64), regraId));
			}
		}
		double antes = contexto.getBean(synapse.api.core.metrics.AppMetrics.class)
			.metaVendaSugeridaConsumida("descartada")
			.count();
		publicarMeta("""
				{"job_id":"%s","regra_id":"%s","sem_solucao":{"motivo":"intervalo_esgotado"}}
				""".formatted(jobId, regraId));
		await().atMost(Duration.ofSeconds(10))
			.untilAsserted(() -> assertThat(contexto.getBean(synapse.api.core.metrics.AppMetrics.class)
				.metaVendaSugeridaConsumida("descartada")
				.count()).isEqualTo(antes + 1));
		assertThat(ClienteDoJob.consultar(porta, jobId).has("meta_sugerida")).isFalse();
		assertThat(statusPersistido(jobId)).isEqualTo(estadoInicial);
		assertThat(transicoesRegistradas(jobId)).isEmpty();
		assertThat(acoesRegistradas(jobId)).isEmpty();
	}

	@Test
	void registroTardioDaSimulacaoNaoEscolheResultadoCandidato() throws Exception {
		UUID jobId = criarJob(JobStatus.SIMULANDO);
		UUID codigoId = criarCodigoGerado(jobId);
		UUID vigente = criarResultado(jobId, codigoId, "sucesso", "viavel");
		UUID candidata = criarResultado(jobId, codigoId, "sucesso", "inviavel");
		UUID regraId;
		try (Connection connection = comoDono(); Statement sql = connection.createStatement()) {
			sql.execute("UPDATE resultados_simulacao SET proposito = 'busca_meta', meta_venda = 9999 WHERE id = '%s'"
				.formatted(candidata));
			try (ResultSet rs = sql
				.executeQuery("SELECT regra_id FROM codigos_gerados WHERE id = '%s'".formatted(codigoId))) {
				assertThat(rs.next()).isTrue();
				regraId = rs.getObject(1, UUID.class);
			}
		}
		try (Connection connection = comoDono(); Statement sql = connection.createStatement()) {
			sql.execute(
					"UPDATE resultados_simulacao SET totais = '{\"baseline\":10,\"simulado\":20,\"diferenca_abs\":10,\"diferenca_pct\":1,\"orcamento\":1000}', decomposicao = '{\"elemento\":{},\"loja\":{},\"marca\":{},\"cargo\":{},\"competencia\":{}}' WHERE id = '%s'"
						.formatted(vigente));
		}
		UUID simulacaoId = contexto.getBean(JobRepository.class)
			.registrarSimulacao(jobId, regraId, codigoId, null, java.time.Instant.now());
		assertThat(resultadoIdDaSimulacao(simulacaoId)).isEqualTo(vigente);
		assertThat(contexto.getBean(JobEventosService.class)
			.concluirSimulacao(jobId, candidata, DesfechoDaSimulacao.INVIAVEL)).isNull();
		assertThat(statusPersistido(jobId)).isEqualTo("simulando");
		assertThat(ClienteDoJob.consultar(porta, jobId).path("simulacao").has("meta_venda")).isFalse();
	}

	private static HttpResponse<String> aceitarMetaConcorrentemente(UUID jobId) {
		try {
			return executarAcao(jobId, "aceitar_meta");
		}
		catch (IOException ex) {
			throw new java.io.UncheckedIOException(ex);
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
			throw new IllegalStateException(ex);
		}
	}

	private static void publicarMeta(String corpo) throws IOException {
		ContratoDeEvento.validar("meta-venda-sugerida", corpo);
		rabbitTemplate.send(RabbitTopologyConfig.META_VENDA_SUGERIDA,
				MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
					.setContentType(MessageProperties.CONTENT_TYPE_JSON)
					.build());
	}

	// --- Apoio ----------------------------------------------------------------------

	private record Simulacao(UUID id, UUID codigoGeradoId) {
	}

	private record Transicao(String destino, String ator, @Nullable String motivo) {
	}

	private static void publicar(UUID jobId, UUID resultadoId, String status, @Nullable String veredito) {
		String corpo = (veredito != null) ? """
				{"job_id":"%s","resultado_id":"%s","status":"%s","veredito":"%s"}
				""".formatted(jobId, resultadoId, status, veredito).strip() : """
				{"job_id":"%s","resultado_id":"%s","status":"%s"}
				""".formatted(jobId, resultadoId, status).strip();
		enviarCorpo(corpo);
	}

	private static void enviarCorpo(String corpo) {
		Message mensagem = MessageBuilder.withBody(corpo.getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setType(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE)
			.build();
		rabbitTemplate.send(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE, "", mensagem);
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

	private static UUID criarJobSemOrcamento() throws SQLException {
		UUID jobId = UUID.randomUUID();
		UUID submissaoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO submissoes (id, usuario_id, tipo, conteudo, criado_em)
					VALUES ('%s', '%s', 'texto', '{}'::jsonb, now())
					""".formatted(submissaoId, USUARIO_ID));
			statement.execute("""
					INSERT INTO jobs (id, status, usuario_id, submissao_id, competencias, orcamento, criado_em)
					VALUES ('%s', 'simulando', '%s', '%s', '{2025-08}', NULL, now())
					""".formatted(jobId, USUARIO_ID, submissaoId));
		}
		return jobId;
	}

	/** O resultado como o worker o grava para um job sem orçamento. */
	private static UUID criarResultadoSemOrcamento(UUID jobId, UUID codigoGeradoId) throws SQLException {
		UUID resultadoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute(
					"""
							INSERT INTO resultados_simulacao
							    (id, job_id, codigo_gerado_id, status, veredito, totais, assercoes, decomposicao, criado_em)
							VALUES ('%s', '%s', '%s', 'sucesso', NULL, '%s'::jsonb, '[]'::jsonb,
							    '{"elemento":{},"loja":{},"marca":{},"cargo":{},"competencia":{"2025-08":11788.00}}'::jsonb, now())
							"""
						.formatted(resultadoId, jobId, codigoGeradoId, TOTAIS_SEM_ORCAMENTO));
		}
		return resultadoId;
	}

	private static HttpResponse<String> executarAcao(UUID jobId, String acao) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest
			.newBuilder(URI.create("http://localhost:" + porta + "/jobs/" + jobId + "/actions"))
			.header("Content-Type", "application/json")
			.POST(HttpRequest.BodyPublishers.ofString("{\"acao\":\"" + acao + "\"}"))
			.build();
		return HTTP.send(requisicao, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
	}

	/** O item do job em {@code GET /jobs}, com a página conferida contra o contrato. */
	private static JsonNode itemDaListagem(UUID jobId) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest
			.newBuilder(URI.create("http://localhost:" + porta + "/jobs?pagina=0&tamanho=100"))
			.header("Accept", "application/json")
			.GET()
			.build();
		HttpResponse<String> resposta = HTTP.send(requisicao,
				HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("PaginaJobs", resposta.body());
		return JSON.readTree(resposta.body())
			.path("itens")
			.valueStream()
			.filter(item -> jobId.toString().equals(item.path("id").asString()))
			.findFirst()
			.orElseThrow(() -> new AssertionError("job " + jobId + " fora da listagem"));
	}

	/**
	 * A amostra de {@code simulacao_concluida_consumo_total} com as duas tags em
	 * {@code /metrics}, ou zero quando a combinação ainda não apareceu.
	 */
	private static double consumos(String desfecho, String resultado) throws IOException, InterruptedException {
		HttpResponse<String> resposta = HTTP.send(
				HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/metrics")).GET().build(),
				HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
		assertThat(resposta.statusCode()).isEqualTo(200);
		return resposta.body()
			.lines()
			.filter(linha -> linha.startsWith("simulacao_concluida_consumo_total{"))
			.filter(linha -> linha.contains("desfecho=\"" + desfecho + "\"")
					&& linha.contains("resultado=\"" + resultado + "\""))
			.mapToDouble(linha -> Double.parseDouble(linha.substring(linha.lastIndexOf(' ') + 1)))
			.sum();
	}

	private static List<String> acoesRegistradas(UUID jobId) throws SQLException {
		List<String> acoes = new ArrayList<>();
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery(
						"SELECT acao FROM job_acoes WHERE job_id = '%s' ORDER BY executado_em".formatted(jobId))) {
			while (rs.next()) {
				acoes.add(Objects.requireNonNull(rs.getString("acao")));
			}
		}
		return acoes;
	}

	private static UUID criarRegra(UUID jobId) throws SQLException {
		UUID regraId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO regras (id, job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
					VALUES ('%s', '%s', 1, 'confirmacao_usuario', '%s'::jsonb, '[]'::jsonb, '%s', now())
					""".formatted(regraId, jobId, NUCLEO, "0".repeat(64)));
		}
		return regraId;
	}

	// prompts, codigos_gerados e resultados_simulacao só o codegen/worker escrevem em
	// produção (AGENTS.md); a fixture usa o usuário dono para simular o que eles já
	// teriam gravado.
	private static UUID criarCodigoGerado(UUID jobId) throws SQLException {
		UUID regraId = criarRegra(jobId);
		UUID promptId = UUID.randomUUID();
		UUID codigoGeradoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
					VALUES ('%s', '%s', 'geracao_codigo', 'x', '{}'::jsonb, now())
					""".formatted(promptId, jobId));
			statement.execute("""
					INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
					VALUES ('%s', '%s', '%s', 'python', 'x', '%s', now())
					""".formatted(codigoGeradoId, jobId, regraId, promptId));
		}
		return codigoGeradoId;
	}

	/**
	 * Uma simulação já registrada, ainda sem resultado amarrado - o estado normal antes
	 * da T-046.
	 */
	private static Simulacao criarSimulacaoPendente(UUID jobId) throws SQLException {
		UUID codigoGeradoId = criarCodigoGerado(jobId);
		UUID simulacaoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute("""
					INSERT INTO simulacoes (id, criado_em, regra_id, job_id, codigo_gerado_id, resultado_id)
					SELECT '%s', now(), regra_id, job_id, id, NULL FROM codigos_gerados WHERE id = '%s'
					""".formatted(simulacaoId, codigoGeradoId));
		}
		return new Simulacao(simulacaoId, codigoGeradoId);
	}

	private static UUID criarResultado(UUID jobId, UUID codigoGeradoId, String status, @Nullable String veredito)
			throws SQLException {
		UUID resultadoId = UUID.randomUUID();
		try (Connection connection = comoDono(); Statement statement = connection.createStatement()) {
			statement.execute(
					"""
							INSERT INTO resultados_simulacao (id, job_id, codigo_gerado_id, status, veredito, assercoes, criado_em)
							VALUES ('%s', '%s', '%s', '%s', %s, '[]'::jsonb, now())
							"""
						.formatted(resultadoId, jobId, codigoGeradoId, status,
								(veredito != null) ? "'" + veredito + "'" : "NULL"));
		}
		return resultadoId;
	}

	/**
	 * Um resultado sem simulação correspondente - o caso comum hoje, já que nada insere
	 * em {@code simulacoes} até a T-046.
	 */
	private static UUID criarResultadoOrfao(UUID jobId, String status, @Nullable String veredito) throws SQLException {
		return criarResultado(jobId, criarCodigoGerado(jobId), status, veredito);
	}

	private static String statusPersistido(UUID jobId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery("SELECT status FROM jobs WHERE id = '%s'".formatted(jobId))) {
			assertThat(rs.next()).isTrue();
			return Objects.requireNonNull(rs.getString("status"));
		}
	}

	private static @Nullable UUID resultadoIdDaSimulacao(UUID simulacaoId) throws SQLException {
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement
					.executeQuery("SELECT resultado_id FROM simulacoes WHERE id = '%s'".formatted(simulacaoId))) {
			assertThat(rs.next()).isTrue();
			return rs.getObject("resultado_id", UUID.class);
		}
	}

	private static List<Transicao> transicoesRegistradas(UUID jobId) throws SQLException {
		List<Transicao> transicoes = new ArrayList<>();
		try (Connection connection = comoDono();
				Statement statement = connection.createStatement();
				ResultSet rs = statement.executeQuery(
						"SELECT status_novo, ator, motivo FROM job_transicoes WHERE job_id = '%s' ORDER BY ocorrido_em"
							.formatted(jobId))) {
			while (rs.next()) {
				transicoes.add(new Transicao(Objects.requireNonNull(rs.getString("status_novo")),
						Objects.requireNonNull(rs.getString("ator")), rs.getString("motivo")));
			}
		}
		return transicoes;
	}

	private static Transicao transicaoUnica(UUID jobId) throws SQLException {
		List<Transicao> transicoes = transicoesRegistradas(jobId);
		assertThat(transicoes).hasSize(1);
		return transicoes.getFirst();
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

	private static QueueInformation infoDaFila(String nome) {
		return Objects.requireNonNull(amqpAdmin.getQueueInfo(nome), "fila " + nome + " não encontrada");
	}

}
