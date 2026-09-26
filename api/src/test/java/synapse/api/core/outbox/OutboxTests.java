package synapse.api.core.outbox;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import liquibase.Contexts;
import liquibase.Liquibase;
import liquibase.database.DatabaseFactory;
import liquibase.database.jvm.JdbcConnection;
import liquibase.resource.ClassLoaderResourceAccessor;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.containers.Container.ExecResult;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.amqp.core.AmqpAdmin;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.IllegalTransactionStateException;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import synapse.api.ApiApplication;
import synapse.api.core.messaging.RabbitTopologyConfig;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.awaitility.Awaitility.await;

/**
 * Sobe a aplicação contra um Postgres e um RabbitMQ reais, com o poller agendado
 * desligado: cada ciclo é uma chamada explícita a
 * {@link PublicadorOutbox#publicarPendentes()}, para que "o ciclo seguinte" seja
 * determinístico. Só o último cenário religa o agendamento.
 */
@EnabledIf("dockerIsAvailable")
class OutboxTests {

	private static final String FILA = RabbitTopologyConfig.REGRA_SUBMETIDA;

	private static final String USUARIO_API = "synapse_api";

	private static final String SENHA = "senha-de-teste";

	private static final UUID USUARIO = UUID.fromString("5d6f1b2a-7c3e-4f10-9a8b-0c1d2e3f4a5b");

	private static final JsonMapper JSON = new JsonMapper();

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	/** Outra conexão, do dono do schema: enxerga só o que já foi confirmado. */
	private static JdbcTemplate dono;

	private static JdbcTemplate jdbc;

	private static TransactionTemplate transacao;

	private static Outbox outbox;

	private static PublicadorOutbox publicador;

	private static RabbitTemplate rabbit;

	private static AmqpAdmin admin;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void preparar() throws Exception {
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		rabbitmq = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		postgres.start();
		rabbitmq.start();
		try (Connection conexao = DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(),
				postgres.getPassword());
				Liquibase liquibase = new Liquibase("db/changelog/changelog.yaml", new ClassLoaderResourceAccessor(),
						DatabaseFactory.getInstance().findCorrectDatabaseImplementation(new JdbcConnection(conexao)))) {
			liquibase.getChangeLogParameters().set("usuario_api", USUARIO_API);
			liquibase.getChangeLogParameters().set("usuario_codegen", "synapse_codegen");
			liquibase.getChangeLogParameters().set("usuario_worker", "synapse_worker");
			liquibase.update(new Contexts());
		}
		dono = new JdbcTemplate(
				new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword()));
		dono.execute("ALTER ROLE " + USUARIO_API + " WITH PASSWORD '" + SENHA + "'");
		dono.update("""
				INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
				VALUES (?, 'rh-t038', 'x', 'RH', 'profissional_rh', now())
				""", USUARIO);

		contexto = subirAApi();
		jdbc = contexto.getBean(JdbcTemplate.class);
		transacao = new TransactionTemplate(contexto.getBean(PlatformTransactionManager.class));
		outbox = contexto.getBean(Outbox.class);
		publicador = contexto.getBean(PublicadorOutbox.class);
		rabbit = contexto.getBean(RabbitTemplate.class);
		admin = contexto.getBean(AmqpAdmin.class);
	}

	@AfterAll
	static void encerrar() {
		if (contexto != null) {
			contexto.close();
		}
		if (rabbitmq != null) {
			rabbitmq.stop();
		}
		if (postgres != null) {
			postgres.stop();
		}
	}

	@BeforeEach
	void limpar() {
		dono.update("DELETE FROM outbox_events");
		admin.declareQueue(QueueBuilder.durable(FILA).build());
		admin.purgeQueue(FILA, false);
	}

	// --- Mesma transação --------------------------------------------------------------

	@Test
	void jobEEventoSaoConfirmadosJuntos() {
		UUID jobId = Objects.requireNonNull(transacao.execute((status) -> {
			UUID criado = inserirJob();
			outbox.registrar(criado, EventoOutbox.REGRA_SUBMETIDA, payload(criado));
			assertThat(jobs(criado)).as("job antes do commit").isZero();
			assertThat(eventos(criado)).as("evento antes do commit").isZero();
			return criado;
		}));

		assertThat(jobs(jobId)).isOne();
		Map<String, Object> evento = evento(jobId);
		assertThat(evento).containsEntry("tipo", FILA)
			.containsEntry("publicado_em", null)
			.containsEntry("tentativas", 0)
			.containsEntry("job_id", jobId);
		assertThat(evento.get("criado_em")).isNotNull();
		assertThat(json(evento.get("payload"))).isEqualTo(JSON.valueToTree(payload(jobId)));
	}

	@Test
	void registrarForaDeTransacaoFalhaSemGravar() {
		UUID jobId = inserirJob();

		assertThatThrownBy(() -> outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, payload(jobId)))
			.isInstanceOf(IllegalTransactionStateException.class);

		assertThat(eventos(jobId)).isZero();
	}

	@Test
	void rollbackNaoDeixaEventoOrfao() {
		UUID jobId = UUID.randomUUID();

		assertThatThrownBy(() -> transacao.executeWithoutResult((status) -> {
			inserirJob(jobId);
			outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, payload(jobId));
			throw new IllegalStateException("falha depois do outbox");
		})).isInstanceOf(IllegalStateException.class);

		assertThat(jobs(jobId)).isZero();
		assertThat(eventos(jobId)).isZero();
	}

	@Test
	void falhaAoGravarOEventoDesfazOJob() {
		UUID jobId = UUID.randomUUID();
		dono.execute("REVOKE INSERT ON outbox_events FROM " + USUARIO_API);
		try {
			assertThatThrownBy(() -> transacao.executeWithoutResult((status) -> {
				inserirJob(jobId);
				outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, payload(jobId));
			})).isInstanceOf(DataAccessException.class).hasMessageContaining("INSERT INTO outbox_events");
		}
		finally {
			dono.execute("GRANT INSERT ON outbox_events TO " + USUARIO_API);
		}

		assertThat(jobs(jobId)).isZero();
	}

	// --- Falha de publicação ----------------------------------------------------------

	@Test
	void brokerForaNaPrimeiraTentativaPublicaNoCicloSeguinte() throws Exception {
		UUID jobId = registrarNovoEvento();
		pararOBroker();
		try {
			publicador.publicarPendentes();

			assertThat(evento(jobId)).containsEntry("publicado_em", null).containsEntry("tentativas", 1);
		}
		finally {
			religarOBroker();
		}

		publicador.publicarPendentes();

		Map<String, Object> evento = evento(jobId);
		assertThat(evento.get("publicado_em")).isNotNull();
		assertThat(evento).containsEntry("tentativas", 2);
		List<Message> mensagens = drenarAFila();
		assertThat(mensagens).hasSize(1);
		MessageProperties propriedades = mensagens.getFirst().getMessageProperties();
		assertThat(propriedades.getMessageId()).isEqualTo(String.valueOf(evento.get("id")));
		assertThat(propriedades.getCorrelationId()).isEqualTo(jobId.toString());
		assertThat(propriedades.getType()).isEqualTo(FILA);
		assertThat(propriedades.getContentType()).isEqualTo(MessageProperties.CONTENT_TYPE_JSON);
		assertThat(propriedades.getContentEncoding()).isEqualTo("utf-8");
		assertThat(propriedades.getReceivedDeliveryMode()).isEqualTo(MessageDeliveryMode.PERSISTENT);
		assertThat(JSON.readTree(mensagens.getFirst().getBody())).isEqualTo(JSON.valueToTree(payload(jobId)));
	}

	/** Sem {@code mandatory} o broker confirmaria a mensagem e a descartaria. */
	@Test
	void mensagemSemFilaDeDestinoContinuaPendente() {
		UUID jobId = registrarNovoEvento();
		admin.deleteQueue(FILA);
		try {
			publicador.publicarPendentes();

			assertThat(evento(jobId)).containsEntry("publicado_em", null).containsEntry("tentativas", 1);
		}
		finally {
			admin.declareQueue(QueueBuilder.durable(FILA).build());
		}

		publicador.publicarPendentes();

		assertThat(evento(jobId).get("publicado_em")).isNotNull();
		assertThat(drenarAFila()).hasSize(1);
	}

	@Test
	void falhaNoPrimeiroEventoSeguraOsSeguintesEPreservaAOrdem() throws Exception {
		UUID jobId = inserirJob();
		for (int i = 0; i < 3; i++) {
			transacao.executeWithoutResult(
					(status) -> outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, payload(jobId)));
		}
		List<String> ordem = dono.queryForList(
				"SELECT id::text FROM outbox_events WHERE job_id = ? ORDER BY criado_em, id", String.class, jobId);
		pararOBroker();
		try {
			publicador.publicarPendentes();

			assertThat(dono.queryForList(
					"SELECT tentativas FROM outbox_events WHERE job_id = ? AND publicado_em IS NULL ORDER BY criado_em, id",
					Integer.class, jobId))
				.containsExactly(1, 0, 0);
		}
		finally {
			religarOBroker();
		}

		publicador.publicarPendentes();

		assertThat(drenarAFila()).extracting((mensagem) -> mensagem.getMessageProperties().getMessageId())
			.containsExactlyElementsOf(ordem);
	}

	// --- Nada é publicado duas vezes ------------------------------------------------

	@Test
	void eventoPublicadoNaoEPublicadoDeNovo() {
		UUID jobId = registrarNovoEvento();

		publicador.publicarPendentes();
		publicador.publicarPendentes();
		publicador.publicarPendentes();

		assertThat(drenarAFila()).hasSize(1);
		assertThat(evento(jobId)).containsEntry("tentativas", 1);
	}

	/** A outra transação faz o papel de um ciclo concorrente com o evento em voo. */
	@Test
	void eventoTravadoPorOutroCicloNaoEPublicado() throws Exception {
		UUID jobId = registrarNovoEvento();
		try (Connection outroCiclo = DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(),
				postgres.getPassword())) {
			outroCiclo.setAutoCommit(false);
			try (PreparedStatement trava = outroCiclo
				.prepareStatement("SELECT id FROM outbox_events WHERE job_id = ? FOR UPDATE")) {
				trava.setObject(1, jobId);
				trava.executeQuery().close();
			}

			// Numa thread à parte: um ciclo que esperasse a trava em vez de pular a linha
			// travaria o teste em vez de falhar.
			CompletableFuture<Void> ciclo = CompletableFuture.runAsync(publicador::publicarPendentes);
			try {
				ciclo.get(10, TimeUnit.SECONDS);
			}
			catch (TimeoutException ex) {
				outroCiclo.rollback();
				ciclo.join();
				throw new AssertionError("o ciclo esperou a trava em vez de pular o evento", ex);
			}

			assertThat(drenarAFila()).isEmpty();
			assertThat(evento(jobId)).containsEntry("publicado_em", null).containsEntry("tentativas", 0);
			outroCiclo.rollback();
		}

		publicador.publicarPendentes();

		assertThat(drenarAFila()).hasSize(1);
	}

	@Test
	void ciclosConcorrentesPublicamCadaEventoUmaVez() throws Exception {
		int total = PublicadorOutbox.LOTE * 2 + 5;
		UUID jobId = inserirJob();
		transacao.executeWithoutResult((status) -> {
			for (int i = 0; i < total; i++) {
				outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, payload(jobId));
			}
		});
		ExecutorService pool = Executors.newFixedThreadPool(4);
		try {
			CountDownLatch largada = new CountDownLatch(1);
			List<Future<?>> ciclos = new ArrayList<>();
			for (int i = 0; i < 4; i++) {
				ciclos.add(pool.submit(() -> {
					largada.await();
					for (int ciclo = 0; ciclo < 3; ciclo++) {
						publicador.publicarPendentes();
					}
					return null;
				}));
			}
			largada.countDown();
			for (Future<?> ciclo : ciclos) {
				ciclo.get(60, TimeUnit.SECONDS);
			}
		}
		finally {
			pool.shutdownNow();
		}

		List<Message> mensagens = drenarAFila();
		assertThat(mensagens).hasSize(total);
		assertThat(mensagens).extracting((mensagem) -> mensagem.getMessageProperties().getMessageId())
			.doesNotHaveDuplicates();
		assertThat(dono.queryForObject("SELECT count(*) FROM outbox_events WHERE publicado_em IS NULL", Integer.class))
			.isZero();
		assertThat(dono.queryForList("SELECT DISTINCT tentativas FROM outbox_events", Integer.class))
			.containsExactly(1);
	}

	// --- Agendamento ----------------------------------------------------------------

	@Test
	void pollerAgendadoPublicaNoIntervaloConfigurado() {
		assertThat(contexto.getBeanProvider(OutboxConfig.class).getIfAvailable())
			.as("poller agendado desligado por app.outbox.enabled=false")
			.isNull();

		try (ConfigurableApplicationContext agendado = subirAApi("--app.outbox.enabled=true",
				"--app.outbox.poll-interval=200ms")) {
			UUID jobId = inserirJob();
			new TransactionTemplate(agendado.getBean(PlatformTransactionManager.class))
				.executeWithoutResult((status) -> agendado.getBean(Outbox.class)
					.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, payload(jobId)));

			await().atMost(Duration.ofSeconds(10))
				.untilAsserted(() -> assertThat(evento(jobId).get("publicado_em")).isNotNull());
			assertThat(drenarAFila()).hasSize(1);
		}
	}

	// --- Apoio ----------------------------------------------------------------------

	/**
	 * O perfil {@code test} desliga Liquibase (o changelog já rodou acima) e o poller
	 * agendado; aqui o banco e o broker são religados aos containers, e a topologia é
	 * declarada para que a fila exista.
	 */
	private static ConfigurableApplicationContext subirAApi(String... ajustes) {
		List<String> argumentos = new ArrayList<>(List.of("--app.postgres.host=" + postgres.getHost(),
				"--app.postgres.port=" + postgres.getMappedPort(5432),
				"--app.postgres.database=" + postgres.getDatabaseName(), "--app.postgres.user=" + USUARIO_API,
				"--app.postgres.password=" + SENHA, "--app.rabbitmq.host=" + rabbitmq.getHost(),
				"--app.rabbitmq.port=" + rabbitmq.getAmqpPort(), "--app.rabbitmq.user=" + rabbitmq.getAdminUsername(),
				"--app.rabbitmq.password=" + rabbitmq.getAdminPassword(), "--spring.rabbitmq.dynamic=true"));
		argumentos.addAll(List.of(ajustes));
		return new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.NONE)
			.profiles("test")
			.run(argumentos.toArray(String[]::new));
	}

	/** Derruba só a aplicação RabbitMQ: a porta mapeada continua a mesma ao religar. */
	private static void pararOBroker() throws Exception {
		rabbitmqctl("stop_app");
	}

	private static void religarOBroker() throws Exception {
		rabbitmqctl("start_app");
		rabbitmqctl("await_startup");
	}

	private static void rabbitmqctl(String comando) throws Exception {
		ExecResult resultado = rabbitmq.execInContainer("rabbitmqctl", comando);
		assertThat(resultado.getExitCode()).as("rabbitmqctl %s: %s", comando, resultado.getStderr()).isZero();
	}

	private static UUID inserirJob() {
		return inserirJob(UUID.randomUUID());
	}

	private static UUID inserirJob(UUID jobId) {
		jdbc.update("""
				INSERT INTO jobs (id, status, usuario_id, competencias, orcamento, criado_em)
				VALUES (?, 'aguardando_confirmacao_parametros', ?, ARRAY['2025-11'], 1000, now())
				""", jobId, USUARIO);
		return jobId;
	}

	private static UUID registrarNovoEvento() {
		UUID jobId = inserirJob();
		transacao
			.executeWithoutResult((status) -> outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, payload(jobId)));
		return jobId;
	}

	private static Map<String, Object> payload(UUID jobId) {
		return Map.of("job_id", jobId.toString(), "origem", "formulario", "competencias", List.of("2025-11"),
				"submissao_id", "b81e0f4c-52a9-4f0b-8a3d-7c2e5d10ab93", "regra_id",
				"9c7d3e21-4a6b-4c8d-9e0f-1a2b3c4d5e6f");
	}

	private static Map<String, Object> evento(UUID jobId) {
		return dono.queryForMap("""
				SELECT id, job_id, tipo, payload::text AS payload, criado_em, publicado_em, tentativas
				FROM outbox_events WHERE job_id = ?
				""", jobId);
	}

	private static int jobs(UUID jobId) {
		return Objects
			.requireNonNull(dono.queryForObject("SELECT count(*) FROM jobs WHERE id = ?", Integer.class, jobId));
	}

	private static int eventos(UUID jobId) {
		return Objects.requireNonNull(
				dono.queryForObject("SELECT count(*) FROM outbox_events WHERE job_id = ?", Integer.class, jobId));
	}

	private static JsonNode json(@Nullable Object texto) {
		return JSON.readTree(String.valueOf(texto));
	}

	private static List<Message> drenarAFila() {
		List<Message> mensagens = new ArrayList<>();
		for (Message mensagem = rabbit.receive(FILA); mensagem != null; mensagem = rabbit.receive(FILA)) {
			mensagens.add(mensagem);
		}
		return mensagens;
	}

}
