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
import java.util.Objects;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.UUID;

import org.junit.jupiter.api.AfterAll;
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

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;

import synapse.api.ApiApplication;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * Único teste fim a fim do sistema: sobe api, codegen e worker contra um Postgres e um
 * RabbitMQ reais e submete uma regra exatamente como a tela de formulário a submete.
 * <p>
 * O corpo da requisição é o que {@code useFormularioRegra.montarRequisicao()} monta
 * ({@code frontend/src/features/formulario-regra/composables/useFormularioRegra.ts}):
 * {@code origem}, {@code orcamento} e {@code conteudo}. Copiar o corpo de outro teste da
 * api, que informa {@code competencias} diretamente, testaria um caminho que nenhum
 * usuário percorre.
 * <p>
 * As asserções descrevem o comportamento correto, não o observado. Onde as duas coisas
 * divergem o teste falha, que é o serviço que ele presta.
 */
@EnabledIf("ambienteCompleto")
class SubmissaoDeRegraFimAFimTests {

	/**
	 * A vigência que a tela envia: quando a regra proposta vale. Não se confunde com as
	 * competências da simulação, e é de propósito que este intervalo seja menor que elas
	 * - competência do job fora da vigência é simulada pelas regras do baseline e entra
	 * no total sem o efeito da regra ({@code contracts/domain/regra-nucleo.schema.json}).
	 */
	private static final String VIGENCIA_INICIO = "2025-10";

	private static final String VIGENCIA_FIM = "2025-12";

	/**
	 * O período que a simulação tem de cobrir. A tela não tem campo de período, então não
	 * envia {@code competencias} e a api preenche com o dataset inteiro, que é o padrão
	 * do contrato de {@code POST /jobs} e o que a {@code ARCHITECTURE.md} §1.3 chama de
	 * período inteiro - a pergunta é se a regra se sustenta ao longo do tempo, não se ela
	 * cabe no orçamento de um mês.
	 * <p>
	 * São cinco: Jul/2025 foi descartado no tratamento dos dados
	 * ({@code EXCLUDE_2025_07}) e não está no dataset embutido no sandbox
	 * ({@code worker/sandbox/data/domrock/}) nem tem baseline congelado.
	 */
	private static final List<String> COMPETENCIAS_DO_DATASET = List.of("2025-08", "2025-09", "2025-10", "2025-11",
			"2025-12");

	/**
	 * O que a tela envia com a vigência acima, loja 13, marca 10, cargo 100, percentual
	 * 2,5% e orçamento R$ 485.000,50. O percentual chega como fração
	 * ({@code converterPercentual} divide por 100) e {@code texto_livre} é {@code null}
	 * no formulário, que não tem campo de texto livre.
	 */
	private static final String CORPO_DO_FORMULARIO = """
			{"origem":"formulario","orcamento":485000.5,
			 "conteudo":{"nucleo":{"vigencia":{"inicio":"%s","fim":"%s"},
			 "loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.025},"texto_livre":null}}
			""".formatted(VIGENCIA_INICIO, VIGENCIA_FIM);

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

	private static GenericContainer<?> codegen;

	private static GenericContainer<?> worker;

	private static ConfigurableApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static int porta;

	/**
	 * O teste exige o ambiente inteiro: Docker, as imagens do compose (inclusive a do
	 * sandbox, que o worker instancia por job) e a chave do provedor de LLM, porque o
	 * codegen faz uma chamada real ao modelo. Faltando qualquer uma, o teste é pulado -
	 * não há como afirmar nada sobre o sistema sem elas.
	 */
	static boolean ambienteCompleto() {
		return DockerClientFactory.instance().isDockerAvailable() && chaveDoProvedor() != null
				&& ImagemDocker.existe("synapse-codegen:local") && ImagemDocker.existe("synapse-worker:local")
				&& ImagemDocker.existe("synapse-sandbox:local");
	}

	@BeforeAll
	static void subirOSistema() throws Exception {
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

		codegen = new GenericContainer<>("synapse-codegen:local").withNetwork(rede)
			.withNetworkAliases("codegen")
			.withEnv(ambienteDeBanco("SYNAPSE_CODEGEN_DB_USER", "synapse_codegen"))
			.withEnv("GOOGLE_API_KEY", Objects.requireNonNull(chaveDoProvedor()))
			.withExposedPorts(8000)
			.waitingFor(Wait.forHttp("/health").forPort(8000).withStartupTimeout(Duration.ofMinutes(2)));
		codegen.start();

		worker = new GenericContainer<>("synapse-worker:local").withNetwork(rede)
			.withNetworkAliases("worker")
			.withEnv(ambienteDeBanco("SYNAPSE_WORKER_DB_USER", "synapse_worker"))
			.withEnv("SANDBOX_IMAGE", "synapse-sandbox:local")
			// O worker instancia o sandbox pelo daemon do host, um container por job.
			.withFileSystemBind(SOCKET_DOCKER.toString(), SOCKET_DOCKER.toString(), BindMode.READ_WRITE)
			// O container roda como appuser (uid 1000); sem o grupo dono do socket ele
			// não
			// alcança o daemon. O GID sai do próprio socket, não de um nome de grupo, que
			// varia por distribuição.
			.withCreateContainerCmdModifier(comando -> comando.getHostConfig().withGroupAdd(List.of(gidDoSocket())))
			.withExposedPorts(8000)
			.waitingFor(Wait.forHttp("/health").forPort(8000).withStartupTimeout(Duration.ofMinutes(2)));
		worker.start();
	}

	@AfterAll
	static void derrubarOSistema() {
		for (GenericContainer<?> container : new GenericContainer<?>[] { worker, codegen }) {
			if (container != null) {
				container.stop();
			}
		}
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
	void formularioAtravessaOPipelineEOClienteAcompanhaPorSse() throws Exception {
		HttpResponse<String> resposta = HTTP
			.send(HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/jobs"))
				.header("Content-Type", "application/json")
				.POST(HttpRequest.BodyPublishers.ofString(CORPO_DO_FORMULARIO))
				.build(), HttpResponse.BodyHandlers.ofString());

		assertThat(resposta.statusCode()).isEqualTo(201);
		JsonNode job = JSON.readTree(resposta.body());
		UUID jobId = UUID.fromString(job.path("id").asString());
		assertThat(job.path("status").asString()).isEqualTo("gerando_regra");

		// A tela não tem campo de período, então a api preenche com o dataset inteiro.
		// Toda
		// competência preenchida tem de existir no dataset: uma que não exista chega ao
		// worker sem baseline para comparar, e o job morre depois de já ter pago a
		// geração.
		assertThat(job.path("competencias").valueStream().map(JsonNode::asString).toList())
			.isEqualTo(COMPETENCIAS_DO_DATASET);
		// O orçamento é o insumo do veredito: tem de chegar com a precisão informada.
		assertThat(job.path("orcamento").decimalValue()).isEqualByComparingTo("485000.5");

		// A tela abre o stream depois de navegar para /jobs/{id}, ou seja, já com o job
		// criado e a geração em curso. É por isso que a conexão vem aqui e não antes do
		// POST: assinar antes testaria uma ordem que o usuário nunca produz.
		StreamCliente stream = conectarAoStream(jobId);
		try {
			// O enquadramento que `frontend/src/services/sse.ts` sabe ler.
			assertThat(stream.status()).isEqualTo(200);
			assertThat(stream.cabecalho("Content-Type")).startsWith("text/event-stream");

			// Na abertura vem a fotografia do estado corrente, e não um stream vazio - é
			// o
			// que permite à tela pintar o andamento sem um GET adicional.
			assertThat(conforme("estado", stream.aguardarBloco("event:estado", Duration.ofSeconds(10))))
				.contains(jobId.toString())
				.contains("\"status\":\"gerando_regra\"");

			// O evento leva referências e os escalares que o codegen não tem permissão de
			// ler em `jobs` - entre eles o orçamento, com a mesma precisão.
			String corpoDoEvento = Objects.requireNonNull(jdbc.queryForObject(
					"SELECT payload::text FROM outbox_events WHERE job_id = ? AND tipo = 'regra-submetida'",
					String.class, jobId));
			JsonNode evento = JSON.readTree(corpoDoEvento);
			ContratoDeEvento.validar("regra-submetida", corpoDoEvento);
			assertThat(evento.path("orcamento").decimalValue()).isEqualByComparingTo("485000.5");
			assertThat(evento.path("competencias").valueStream().map(JsonNode::asString).toList())
				.isEqualTo(COMPETENCIAS_DO_DATASET);

			// O primeiro sinal de progresso, na entrada da etapa: sem ele a tela ficaria
			// muda
			// durante a geração, que é a parte demorada.
			assertThat(conforme("etapa", stream.aguardarBloco("\"etapa\":\"geracao_codigo\"", Duration.ofSeconds(30))))
				.contains(jobId.toString())
				.contains("\"status\":\"iniciada\"");

			// A geração passa pelo provedor de LLM; minutos, não segundos. Este segundo
			// `etapa` é o que o codegen publica ao delegar ao worker.
			assertThat(conforme("etapa", stream.aguardarBloco("\"etapa\":\"delegacao_worker\"", Duration.ofMinutes(3))))
				.contains(jobId.toString())
				.contains("\"status\":\"iniciada\"");

			// O mesmo evento move o job, e a transição chega ao cliente como `estado`.
			assertThat(conforme("estado", stream.aguardarBloco("\"status\":\"simulando\"", Duration.ofMinutes(1))))
				.contains("event:estado")
				.contains("\"status_anterior\":\"gerando_regra\"");

			await().atMost(Duration.ofMinutes(3))
				.pollInterval(Duration.ofSeconds(2))
				.untilAsserted(
						() -> assertThat(status(jobId)).isIn("simulacao_inviavel", "aguardando_decisao_usuario"));

			// O desfecho também chega pelo stream, e não só no banco: sem ele a tela
			// ficaria
			// parada em "simulando" até alguém recarregar a página.
			String desfecho = conforme("estado",
					stream.aguardarBloco("\"status\":\"" + status(jobId) + "\"", Duration.ofSeconds(30)));
			assertThat(desfecho).contains("event:estado").contains("\"status_anterior\":\"simulando\"");

			// O `resultado` leva a referência da simulação, nunca os números: é por ela
			// que
			// a tela busca o que foi apurado. Sem este evento o cliente sabe que o job
			// acabou e não tem como mostrar o resultado.
			String recebido = stream.conteudo();
			assertThat(recebido).contains("event:resultado");
			assertThat(conforme("resultado", stream.aguardarBloco("event:resultado", Duration.ofSeconds(5))))
				.contains(jobId.toString())
				.contains("\"simulacao_id\"")
				.contains("\"status\":\"sucesso\"");
			// E vem antes do desfecho: um `estado` terminal fecha o stream, e o que
			// viesse
			// depois se perderia (skill sse).
			assertThat(recebido.indexOf("event:resultado")).isLessThan(recebido.indexOf(desfecho));
		}
		finally {
			stream.fechar();
		}

		// Cada artefato é gravado uma vez só. Uma reentrega da mensagem retoma do
		// checkpoint e não pode duplicar linha nenhuma.
		assertThat(contar("prompts", jobId)).isEqualTo(1);
		assertThat(contar("respostas_modelo", jobId)).isEqualTo(1);
		assertThat(contar("codigos_gerados", jobId)).isEqualTo(1);
		assertThat(contar("resultados_simulacao", jobId)).isEqualTo(1);

		// A regra foi simulada integralmente: nenhum resultado parcial, nenhuma asserção
		// violada, e os números vêm da execução sobre os dados reais.
		JsonNode resultado = JSON.readTree(Objects.requireNonNull(jdbc
			.queryForObject("SELECT to_jsonb(r) FROM resultados_simulacao r WHERE job_id = ?", String.class, jobId)));
		assertThat(resultado.path("status").asString()).isEqualTo("sucesso");
		assertThat(resultado.path("veredito").asString()).isIn("viavel", "inviavel");
		assertThat(resultado.path("totais").path("orcamento").decimalValue()).isEqualByComparingTo("485000.5");
		assertThat(resultado.path("totais").path("baseline").decimalValue()).isPositive();
		assertThat(resultado.path("totais").path("simulado").decimalValue()).isPositive();

		// O caminho de estados prova quem avisou a api: `simulando` só vem do
		// `etapa-alterada` que o codegen publica ao delegar ao worker.
		assertThat(jdbc.queryForList("SELECT status_novo FROM job_transicoes WHERE job_id = ? ORDER BY ocorrido_em",
				String.class, jobId))
			.startsWith("gerando_regra", "simulando")
			.doesNotContain("erro");
	}

	// --- Apoio ----------------------------------------------------------------------

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

	private static String status(UUID jobId) {
		return Objects.requireNonNull(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId));
	}

	private static int contar(String tabela, UUID jobId) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT count(*) FROM " + tabela + " WHERE job_id = ?", Integer.class, jobId));
	}

	/**
	 * Variáveis que codegen e worker compartilham: o mesmo Postgres e o mesmo RabbitMQ,
	 * pelos apelidos de rede, com o usuário de banco próprio de cada serviço.
	 */
	private static java.util.Map<String, String> ambienteDeBanco(String variavelDoUsuario, String usuario) {
		return java.util.Map.of("POSTGRES_HOST", "postgres", "POSTGRES_PORT", "5432", "POSTGRES_DB",
				postgres.getDatabaseName(), variavelDoUsuario, usuario, variavelDoUsuario.replace("_USER", "_PASSWORD"),
				SENHA, "RABBITMQ_HOST", "rabbitmq", "RABBITMQ_PORT", "5672", "RABBITMQ_USER",
				rabbitmq.getAdminUsername(), "RABBITMQ_PASSWORD", rabbitmq.getAdminPassword());
	}

	private static @Nullable String chaveDoProvedor() {
		String chave = System.getenv("GOOGLE_API_KEY");
		return chave == null || chave.isBlank() ? null : chave;
	}

	private static String gidDoSocket() {
		try {
			return String.valueOf(Files.getAttribute(SOCKET_DOCKER, "unix:gid"));
		}
		catch (java.io.IOException ex) {
			throw new IllegalStateException("não foi possível ler o grupo dono de " + SOCKET_DOCKER, ex);
		}
	}

	private static Connection comoDono() throws SQLException {
		return DriverManager.getConnection(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
	}

}
