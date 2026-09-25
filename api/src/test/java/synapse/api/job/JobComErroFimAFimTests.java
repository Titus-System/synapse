package synapse.api.job;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.jspecify.annotations.Nullable;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.containers.BindMode;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.Network;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;

import synapse.api.ApiApplication;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * Os dois desfechos em {@code erro} do ponto de vista do cliente, fim a fim. O caminho
 * feliz está em {@link SubmissaoDeRegraFimAFimTests}, e a regra submetida é a mesma: o
 * corpo que a tela de formulário monta.
 * <p>
 * Existem dois caminhos para {@code erro}, e eles não se substituem. Um é falha
 * permanente do codegen, que o leva de {@code gerando_regra} a {@code erro} pelo
 * {@code etapa-alterada}; o outro é falha do worker, que o leva de {@code simulando} a
 * {@code erro} pelo {@code simulacao-concluida}, com um evento {@code resultado} de
 * status de erro no meio. Um job que morre sem avisar a `api` fica pendurado para sempre,
 * então o que estes testes guardam é o aviso, não a falha.
 * <p>
 * Cada cenário sobe os serviços de que precisa e os derruba no fim: o primeiro depende de
 * a mensagem ficar retida na fila enquanto o teste remove a regra, e o segundo depende de
 * um worker apontado para uma imagem de sandbox que não existe.
 */
@EnabledIf("dockerEImagemDoCodegen")
class JobComErroFimAFimTests {

	/** O mesmo corpo do caminho feliz: o que {@code useFormularioRegra} monta. */
	private static final String CORPO_DO_FORMULARIO = """
			{"origem":"formulario","orcamento":485000.5,
			 "conteudo":{"nucleo":{"vigencia":{"inicio":"2025-10","fim":"2025-12"},
			 "loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.025},"texto_livre":null}}
			""";

	/**
	 * Trechos das razões localizadas que a api põe no campo {@code motivo} do evento
	 * {@code estado} ({@code EtapaAlteradaService} e {@code DesfechoDaSimulacao}). Sem
	 * acento de propósito: servem de marcador de busca no stream, e o marcador não deve
	 * depender de como o serializador trata caracteres fora do ASCII.
	 */
	private static final String RAZAO_FALHA_NA_GERACAO = "Falha durante o processamento da regra";

	private static final String RAZAO_FALHA_DE_INFRA = "Falha de infraestrutura";

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "66666666-6666-4666-8666-666666666666";

	private static final Path SOCKET_DOCKER = Path.of("/var/run/docker.sock");

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static Network rede;

	private static PostgreSQLContainer postgres;

	private static RabbitMQContainer rabbitmq;

	private static ConfigurableApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static int porta;

	private static @Nullable GenericContainer<?> codegen;

	private static @Nullable GenericContainer<?> worker;

	/**
	 * O mínimo dos dois cenários. O primeiro falha antes de qualquer chamada ao modelo, e
	 * por isso roda sem chave do provedor e sem worker - o que o torna o mais barato de
	 * manter em CI.
	 */
	static boolean dockerEImagemDoCodegen() {
		return DockerClientFactory.instance().isDockerAvailable() && imagemExiste("synapse-codegen:local");
	}

	/**
	 * O segundo cenário chega até a execução, então exige o worker, o sandbox e a chave.
	 */
	static boolean ambienteDeExecucao() {
		return dockerEImagemDoCodegen() && imagemExiste("synapse-worker:local") && imagemExiste("synapse-sandbox:local")
				&& chaveDoProvedor() != null;
	}

	@BeforeAll
	static void subirAInfraestrutura() throws Exception {
		rede = Network.newNetwork();
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.withNetwork(rede).withNetworkAliases("postgres").start();
		rabbitmq = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		rabbitmq.withNetwork(rede).withNetworkAliases("rabbitmq").start();

		// A api roda fora da rede do Docker e alcança as portas publicadas no host; o
		// codegen e o worker rodam dentro dela e usam os apelidos de rede.
		contexto = new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.SERVLET)
			.run("--server.port=0", "--app.postgres.host=" + postgres.getHost(),
					"--app.postgres.port=" + postgres.getMappedPort(5432),
					"--app.postgres.database=" + postgres.getDatabaseName(),
					"--app.postgres.owner.user=" + postgres.getUsername(),
					"--app.postgres.owner.password=" + postgres.getPassword(), "--app.postgres.user=synapse_api",
					"--app.postgres.password=" + SENHA, "--app.rabbitmq.host=" + rabbitmq.getHost(),
					"--app.rabbitmq.port=" + rabbitmq.getAmqpPort(),
					"--app.rabbitmq.user=" + rabbitmq.getAdminUsername(),
					"--app.rabbitmq.password=" + rabbitmq.getAdminPassword(),
					"--management.health.rabbit.enabled=false", "--management.health.db.enabled=false",
					"--app.keycloak.enabled=false", "--app.outbox.poll-interval=200ms");
		porta = Integer.parseInt(Objects.requireNonNull(contexto.getEnvironment().getProperty("local.server.port")));
		jdbc = contexto.getBean(JdbcTemplate.class);

		// As migrations criam as três roles sem senha (changeset 000); cada serviço só
		// consegue se conectar depois que o teste define a dele.
		try (Connection conexao = comoDono(); Statement comando = conexao.createStatement()) {
			for (String role : List.of("synapse_api", "synapse_codegen", "synapse_worker")) {
				comando.execute("ALTER ROLE " + role + " WITH PASSWORD '" + SENHA + "'");
			}
			// Sem Keycloak a api resolve o primeiro usuário ativo; o job precisa de um
			// dono.
			comando.execute("""
					INSERT INTO usuarios (id, login, senha_hash, nome, papel, criado_em)
					VALUES ('%s', 'rh', 'x', 'RH', 'profissional_rh', now())
					""".formatted(USUARIO_ID));
		}
	}

	/**
	 * Um cenário não pode herdar o consumer do outro: dois codegens na mesma fila
	 * disputariam a mensagem e o resultado dependeria de quem a pegasse primeiro.
	 */
	@AfterEach
	void derrubarOsServicos() {
		if (worker != null) {
			worker.stop();
			worker = null;
		}
		if (codegen != null) {
			codegen.stop();
			codegen = null;
		}
	}

	@AfterAll
	static void derrubarAInfraestrutura() {
		if (contexto != null) {
			contexto.close();
		}
		if (rabbitmq != null) {
			rabbitmq.stop();
		}
		if (postgres != null) {
			postgres.stop();
		}
		if (rede != null) {
			rede.close();
		}
	}

	@Test
	void falhaPermanenteNaGeracaoEncerraOJobEEncerraOStream() throws Exception {
		JsonNode job = criarJob();
		UUID jobId = UUID.fromString(job.path("id").asString());
		UUID regraId = UUID.fromString(job.path("regra").path("id").asString());
		assertThat(job.path("status").asString()).isEqualTo("gerando_regra");

		// O codegen ainda não subiu, então a `regra-submetida` espera na fila. Esperar a
		// publicação antes de mexer no banco é o que torna o cenário determinístico: sem
		// isso, o consumer poderia ler a regra antes de o teste removê-la.
		await().atMost(Duration.ofSeconds(30))
			.untilAsserted(() -> assertThat(publicado(jobId, "regra-submetida")).isTrue());

		// A regra desaparece: `load_rule` não tem o que carregar, e nenhuma reentrega a
		// recria. É a condição permanente que `RegraInvalidaError` representa.
		//
		// Removida como dono do banco, e não pela conexão da api: a role `synapse_api`
		// não
		// tem `DELETE` em `regras`, porque apagar regra não é operação da api. O teste
		// encena uma linha que sumiu, não uma que a api tenha apagado.
		try (Connection conexao = comoDono(); Statement comando = conexao.createStatement()) {
			assertThat(comando.executeUpdate("DELETE FROM regras WHERE id = '" + regraId + "'")).isEqualTo(1);
		}

		StreamCliente stream = conectarAoStream(jobId);
		try {
			assertThat(conforme("estado", stream.aguardarBloco("event:estado", Duration.ofSeconds(10))))
				.contains(jobId.toString())
				.contains("\"status\":\"gerando_regra\"");

			codegen = iniciarCodegen();

			// A etapa que falhou chega ao cliente antes da transição: é o que permite à
			// tela
			// dizer em que passo o job morreu, e não só que morreu.
			assertThat(conforme("etapa", stream.aguardarBloco("event:etapa", Duration.ofMinutes(1))))
				.contains(jobId.toString())
				.contains("\"etapa\":\"geracao_codigo\"")
				.contains("\"status\":\"erro\"");

			// A razão localizada é o que a tela mostra; o vocabulário de máquina fica na
			// trilha. O marcador é a razão porque `"status":"erro"` também aparece no
			// bloco
			// de `etapa` acima.
			assertThat(conforme("estado", stream.aguardarBloco(RAZAO_FALHA_NA_GERACAO, Duration.ofSeconds(30))))
				.contains("event:estado")
				.contains("\"status\":\"erro\"")
				.contains("\"status_anterior\":\"gerando_regra\"");

			// `erro` é terminal, então o servidor encerra o stream (contrato de
			// `GET /jobs/{id}/events`). É esse fim que faz o cliente parar de reconectar,
			// em
			// vez de reabrir para sempre um job que já acabou.
			stream.aguardarFimDoStream(Duration.ofSeconds(15));
		}
		finally {
			stream.fechar();
		}

		assertThat(status(jobId)).isEqualTo("erro");
		assertThat(jdbc.queryForObject("SELECT finalizado_em IS NOT NULL FROM jobs WHERE id = ?", Boolean.class, jobId))
			.isTrue();

		// Nenhum artefato: a falha é antes da chamada ao modelo, e um job que falha não
		// deixa resultado parcial atrás de si.
		for (String tabela : List.of("prompts", "respostas_modelo", "codigos_gerados", "resultados_simulacao",
				"simulacoes", "trilhas_auditoria")) {
			assertThat(contar(tabela, jobId)).as("%s do job que falhou", tabela).isZero();
		}

		assertThat(transicoes(jobId)).containsExactly("gerando_regra", "erro");
		assertThat(motivoDaUltimaTransicao(jobId)).isEqualTo("erro_geracao_codigo");

		// A mensagem foi rejeitada sem requeue, não devolvida à fila: uma falha
		// permanente
		// que volta a ser entregue gira para sempre, e era esse o defeito antes do
		// `FalhaDoJobError`.
		assertThat(receberDaFila("regra-submetida")).as("mensagem reenfileirada após falha permanente").isNull();
	}

	@Test
	@EnabledIf("ambienteDeExecucao")
	void falhaDeInfraestruturaNaExecucaoEncerraOJobDepoisDeGerarOCodigo() throws Exception {
		codegen = iniciarCodegen();
		// Uma etiqueta que não existe no daemon: o worker falha ao criar o container do
		// sandbox (`SandboxInfraError`), repete conforme a DEC-091 e, na última
		// tentativa,
		// grava `erro_infra` e publica antes de o comando ir para a DLQ - sem isso o job
		// ficaria em `simulando` para sempre (DEC-094).
		worker = iniciarWorker("synapse-sandbox:ausente-" + UUID.randomUUID());

		JsonNode job = criarJob();
		UUID jobId = UUID.fromString(job.path("id").asString());

		StreamCliente stream = conectarAoStream(jobId);
		try {
			assertThat(conforme("estado", stream.aguardarBloco("event:estado", Duration.ofSeconds(10))))
				.contains("\"status\":\"gerando_regra\"");

			// A geração acontece normalmente: o que falha é a execução. Este cenário só
			// tem
			// sentido depois de o código existir.
			assertThat(conforme("etapa", stream.aguardarBloco("event:etapa", Duration.ofMinutes(3))))
				.contains("\"etapa\":\"delegacao_worker\"")
				.contains("\"status\":\"iniciada\"");
			assertThat(conforme("estado", stream.aguardarBloco("\"status\":\"simulando\"", Duration.ofMinutes(1))))
				.contains("\"status_anterior\":\"gerando_regra\"");

			// O `resultado` anuncia o desfecho mesmo quando ele é uma falha, com a
			// referência da simulação e sem veredito: veredito é juízo sobre um número, e
			// aqui não houve número.
			String resultadoSse = conforme("resultado", stream.aguardarBloco("event:resultado", Duration.ofMinutes(2)));
			assertThat(resultadoSse).contains(jobId.toString())
				.contains("\"simulacao_id\"")
				.contains("\"status\":\"erro_infra\"")
				.doesNotContain("veredito");

			String desfecho = conforme("estado", stream.aguardarBloco(RAZAO_FALHA_DE_INFRA, Duration.ofSeconds(30)));
			assertThat(desfecho).contains("\"status\":\"erro\"").contains("\"status_anterior\":\"simulando\"");

			// A mesma ordem do caminho feliz, e pelo mesmo motivo: o `estado` terminal
			// fecha
			// o stream, então o `resultado` tem de chegar antes (skill sse).
			String recebido = stream.conteudo();
			assertThat(recebido.indexOf("event:resultado")).isLessThan(recebido.indexOf(desfecho));
			stream.aguardarFimDoStream(Duration.ofSeconds(15));
		}
		finally {
			stream.fechar();
		}

		assertThat(status(jobId)).isEqualTo("erro");
		assertThat(transicoes(jobId)).containsExactly("gerando_regra", "simulando", "erro");
		assertThat(motivoDaUltimaTransicao(jobId)).isEqualTo("erro_infra");

		// O que o codegen produziu continua gravado, uma linha de cada: a falha foi
		// depois
		// dele, e o que ele fez permanece auditável.
		assertThat(contar("prompts", jobId)).isEqualTo(1);
		assertThat(contar("respostas_modelo", jobId)).isEqualTo(1);
		assertThat(contar("codigos_gerados", jobId)).isEqualTo(1);
		assertThat(contar("simulacoes", jobId)).isEqualTo(1);
		assertThat(contar("resultados_simulacao", jobId)).isEqualTo(1);

		// Sem número não há totais nem veredito - o contrato os declara nulos fora do
		// status
		// `sucesso`, e inventá-los aqui seria afirmar uma apuração que não houve.
		JsonNode resultado = JSON.readTree(Objects.requireNonNull(jdbc
			.queryForObject("SELECT to_jsonb(r) FROM resultados_simulacao r WHERE job_id = ?", String.class, jobId)));
		assertThat(resultado.path("status").asString()).isEqualTo("erro_infra");
		assertThat(resultado.path("totais").isNull()).isTrue();
		assertThat(resultado.path("veredito").isNull()).isTrue();

		// Esgotadas as tentativas, o comando vai para a DLQ em vez de ficar girando na
		// fila.
		assertThat(receberDaFila("executar-codigo.dlq")).as("comando na DLQ após esgotar as tentativas").isNotNull();
	}

	// --- Apoio ----------------------------------------------------------------------

	private static JsonNode criarJob() throws Exception {
		HttpResponse<String> resposta = HTTP
			.send(HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/jobs"))
				.header("Content-Type", "application/json")
				.POST(HttpRequest.BodyPublishers.ofString(CORPO_DO_FORMULARIO))
				.build(), HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(201);
		return JSON.readTree(resposta.body());
	}

	/**
	 * Confere o bloco contra o contrato do stream antes de qualquer asserção sobre o
	 * conteúdo: comparar texto prova que o campo está lá, não que a forma é a publicada.
	 */
	private static String conforme(String nomeDoEvento, String bloco) throws IOException {
		assertThat(bloco).contains("event:" + nomeDoEvento).containsPattern("(?m)^id:\\d+$");
		Matcher dados = Pattern.compile("(?m)^data:(.*)$").matcher(bloco);
		assertThat(dados.find()).as("bloco sem linha data:: %s", bloco).isTrue();
		ContratoDeEvento.validarEventoDoStream(nomeDoEvento, dados.group(1));
		return bloco;
	}

	private static StreamCliente conectarAoStream(UUID jobId) throws Exception {
		return new StreamCliente(
				HTTP.send(HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/jobs/" + jobId + "/events"))
					.GET()
					.build(), HttpResponse.BodyHandlers.ofInputStream()));
	}

	private static GenericContainer<?> iniciarCodegen() {
		GenericContainer<?> container = new GenericContainer<>("synapse-codegen:local").withNetwork(rede)
			.withNetworkAliases("codegen")
			.withEnv(ambienteDeBanco("SYNAPSE_CODEGEN_DB_USER", "synapse_codegen"))
			.withExposedPorts(8000)
			.waitingFor(Wait.forHttp("/health").forPort(8000).withStartupTimeout(Duration.ofMinutes(2)));
		String chave = chaveDoProvedor();
		if (chave != null) {
			container.withEnv("GOOGLE_API_KEY", chave);
		}
		container.start();
		return container;
	}

	private static GenericContainer<?> iniciarWorker(String imagemDoSandbox) {
		GenericContainer<?> container = new GenericContainer<>("synapse-worker:local").withNetwork(rede)
			.withNetworkAliases("worker")
			.withEnv(ambienteDeBanco("SYNAPSE_WORKER_DB_USER", "synapse_worker"))
			.withEnv("SANDBOX_IMAGE", imagemDoSandbox)
			// O worker instancia o sandbox pelo daemon do host, um container por job.
			.withFileSystemBind(SOCKET_DOCKER.toString(), SOCKET_DOCKER.toString(), BindMode.READ_WRITE)
			// O container roda como appuser (uid 1000); sem o grupo dono do socket ele
			// não
			// alcança o daemon. O GID sai do próprio socket, não de um nome de grupo, que
			// varia por distribuição.
			.withCreateContainerCmdModifier(comando -> comando.getHostConfig().withGroupAdd(List.of(gidDoSocket())))
			.withExposedPorts(8000)
			.waitingFor(Wait.forHttp("/health").forPort(8000).withStartupTimeout(Duration.ofMinutes(2)));
		container.start();
		return container;
	}

	private static Map<String, String> ambienteDeBanco(String variavelDoUsuario, String usuario) {
		return Map.of("POSTGRES_HOST", "postgres", "POSTGRES_PORT", "5432", "POSTGRES_DB", postgres.getDatabaseName(),
				variavelDoUsuario, usuario, variavelDoUsuario.replace("_USER", "_PASSWORD"), SENHA, "RABBITMQ_HOST",
				"rabbitmq", "RABBITMQ_PORT", "5672", "RABBITMQ_USER", rabbitmq.getAdminUsername(), "RABBITMQ_PASSWORD",
				rabbitmq.getAdminPassword());
	}

	private static String status(UUID jobId) {
		return Objects.requireNonNull(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId));
	}

	private static int contar(String tabela, UUID jobId) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT count(*) FROM " + tabela + " WHERE job_id = ?", Integer.class, jobId));
	}

	private static List<String> transicoes(UUID jobId) {
		return jdbc.queryForList("SELECT status_novo FROM job_transicoes WHERE job_id = ? ORDER BY ocorrido_em",
				String.class, jobId);
	}

	private static @Nullable String motivoDaUltimaTransicao(UUID jobId) {
		return jdbc.queryForObject(
				"SELECT motivo FROM job_transicoes WHERE job_id = ? ORDER BY ocorrido_em DESC LIMIT 1", String.class,
				jobId);
	}

	private static boolean publicado(UUID jobId, String tipo) {
		return Boolean.TRUE.equals(
				jdbc.queryForObject("SELECT publicado_em IS NOT NULL FROM outbox_events WHERE job_id = ? AND tipo = ?",
						Boolean.class, jobId, tipo));
	}

	private static @Nullable Object receberDaFila(String fila) {
		return contexto.getBean(RabbitTemplate.class).receive(fila);
	}

	private static @Nullable String chaveDoProvedor() {
		String chave = System.getenv("GOOGLE_API_KEY");
		return chave == null || chave.isBlank() ? null : chave;
	}

	private static boolean imagemExiste(String etiqueta) {
		try {
			return !DockerClientFactory.instance()
				.client()
				.listImagesCmd()
				.withImageNameFilter(etiqueta)
				.exec()
				.isEmpty();
		}
		catch (RuntimeException ex) {
			return false;
		}
	}

	private static String gidDoSocket() {
		try {
			return String.valueOf(Files.getAttribute(SOCKET_DOCKER, "unix:gid"));
		}
		catch (IOException ex) {
			throw new IllegalStateException("não foi possível ler o grupo dono de " + SOCKET_DOCKER, ex);
		}
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

}
