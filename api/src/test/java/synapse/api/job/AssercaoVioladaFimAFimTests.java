package synapse.api.job;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

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

import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;

import synapse.api.ApiApplication;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * O desfecho {@code assercao_violada}, fim a fim: o código rodou e produziu números, mas
 * uma invariante foi violada e o número não vale. É o erro de semântica mais sutil dos
 * três - {@code erro_codigo} é código que quebrou e {@code erro_infra} é execução que não
 * aconteceu, enquanto aqui houve execução e houve resultado, e é justamente o resultado
 * que se recusa. Distinto também de {@code veredito: inviavel}, onde a regra é coerente e
 * o número é confiável, só não cabe no orçamento.
 * <p>
 * O modelo não produz esse desfecho sob encomenda, então este teste ocupa o lugar do
 * codegen: grava a linha de {@code codigos_gerados} com um {@code regra.py} escrito à mão
 * que viola a invariante, e publica os três eventos que o codegen publicaria, na mesma
 * ordem ({@code no-concluido}, {@code etapa-alterada}, {@code executar-codigo}). O que se
 * exercita é worker → api → SSE, com o worker e a execução no sandbox reais.
 * <p>
 * O caminho feliz está em {@link SubmissaoDeRegraFimAFimTests} e os outros dois desfechos
 * em {@link JobComErroFimAFimTests}.
 */
@EnabledIf("ambienteDeExecucao")
class AssercaoVioladaFimAFimTests {

	/**
	 * A única invariante que o harness confere sobre a apuração simulada
	 * ({@code worker/app/sandbox/harness.py::comissao_nao_negativa}). As outras duas da
	 * T-031 não rodam ali, e a docstring de lá explica por quê.
	 */
	private static final String INVARIANTE = "sem_comissao_negativa";

	/**
	 * Uma {@code regra.py} que passa por tudo e falha só onde deve: devolve as duas
	 * tabelas com as colunas do contrato, sem import nenhum, e põe comissão negativa em
	 * toda linha. O harness curto-circuita na asserção antes de agregar, então
	 * {@code contribuicoes} não precisa reconciliar com nada - o que se está testando é a
	 * recusa, não a agregação.
	 */
	private static final String REGRA_COM_COMISSAO_NEGATIVA = """
			def aplicar_regra(bases, apuracao_base, competencias):
			    dimensoes = ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]
			    simulada = apuracao_base.copy()
			    simulada["comissao"] = -1.0
			    contribuicoes = apuracao_base[dimensoes].copy()
			    contribuicoes["elemento_ref"] = "nucleo.percentual"
			    contribuicoes["delta"] = 0.0
			    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
			""";

	/** O mesmo corpo dos outros dois e2e: o que {@code useFormularioRegra} monta. */
	private static final String CORPO_DO_FORMULARIO = """
			{"origem":"formulario","orcamento":485000.5,
			 "conteudo":{"nucleo":{"vigencia":{"inicio":"2025-10","fim":"2025-12"},
			 "loja":["13"],"marca":["10"],"cargo":["100"],"percentual":0.025},"texto_livre":null}}
			""";

	/**
	 * Trecho da razão localizada que a api põe no {@code motivo} do evento {@code estado}
	 * ({@code DesfechoDaSimulacao.ASSERCAO_VIOLADA}). Sem acento de propósito: serve de
	 * marcador de busca no stream, e o marcador não deve depender de como o serializador
	 * trata caracteres fora do ASCII.
	 */
	private static final String RAZAO_ASSERCAO = "invariante violada na execu";

	private static final List<String> COMPETENCIAS_DO_DATASET = List.of("2025-08", "2025-09", "2025-10", "2025-11",
			"2025-12");

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

	private static GenericContainer<?> worker;

	private static ConfigurableApplicationContext contexto;

	private static JdbcTemplate jdbc;

	private static int porta;

	/**
	 * Não precisa da chave do provedor: o codegen não roda aqui, e é o teste que produz o
	 * código. Precisa do worker e da imagem do sandbox, porque a execução é real - é ela
	 * que decide a asserção.
	 */
	static boolean ambienteDeExecucao() {
		return DockerClientFactory.instance().isDockerAvailable() && imagemExiste("synapse-worker:local")
				&& imagemExiste("synapse-sandbox:local");
	}

	@BeforeAll
	static void subirOSistema() throws Exception {
		rede = Network.newNetwork();
		postgres = new PostgreSQLContainer("postgres:18-alpine");
		postgres.withNetwork(rede).withNetworkAliases("postgres").start();
		rabbitmq = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		rabbitmq.withNetwork(rede).withNetworkAliases("rabbitmq").start();

		// A api roda fora da rede do Docker e alcança as portas publicadas no host; o
		// worker
		// roda dentro dela e usa os apelidos de rede. O codegen não sobe de propósito: um
		// consumer de `regra-submetida` competiria com o código que este teste grava.
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
		if (worker != null) {
			worker.stop();
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
	void invarianteVioladaRecusaONumeroEEncerraOJobEmErro() throws Exception {
		HttpResponse<String> resposta = HTTP
			.send(HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/jobs"))
				.header("Content-Type", "application/json")
				.POST(HttpRequest.BodyPublishers.ofString(CORPO_DO_FORMULARIO))
				.build(), HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(201);
		JsonNode job = JSON.readTree(resposta.body());
		UUID jobId = UUID.fromString(job.path("id").asString());
		UUID regraId = UUID.fromString(job.path("regra").path("id").asString());
		assertThat(job.path("status").asString()).isEqualTo("gerando_regra");

		// No lugar do codegen: o prompt e o código que ele teria gravado. Como dono do
		// banco, porque a role da api não escreve em tabela de artefato de outro serviço.
		UUID promptId = UUID.randomUUID();
		UUID codigoGeradoId = UUID.randomUUID();
		gravarArtefatosDoCodegen(jobId, regraId, promptId, codigoGeradoId);

		StreamCliente stream = conectarAoStream(jobId);
		try {
			assertThat(conforme("estado", stream.aguardarBloco("event:estado", Duration.ofSeconds(10))))
				.contains(jobId.toString())
				.contains("\"status\":\"gerando_regra\"");

			// A mesma sequência e a mesma ordem do codegen: o `no-concluido` cria a linha
			// de
			// `simulacoes`, que é o que liga o job ao resultado; o `etapa-alterada` move
			// o
			// job; e só então o comando vai ao worker.
			publicar("no-concluido", noConcluido(jobId, regraId, promptId, codigoGeradoId));
			publicar("etapa-alterada", etapaAlterada(jobId));
			publicar("executar-codigo", executarCodigo(jobId, codigoGeradoId));

			assertThat(conforme("etapa", stream.aguardarBloco("event:etapa", Duration.ofSeconds(30))))
				.contains("\"etapa\":\"delegacao_worker\"")
				.contains("\"status\":\"iniciada\"");
			assertThat(conforme("estado", stream.aguardarBloco("\"status\":\"simulando\"", Duration.ofSeconds(30))))
				.contains("\"status_anterior\":\"gerando_regra\"");

			// O `resultado` anuncia o desfecho com a referência da simulação e **sem
			// veredito**: veredito é juízo sobre um número, e o número acabou de ser
			// recusado. É o que separa este caso de `veredito: inviavel`, onde o número
			// vale
			// e só não cabe.
			String resultadoSse = conforme("resultado", stream.aguardarBloco("event:resultado", Duration.ofMinutes(2)));
			assertThat(resultadoSse).contains(jobId.toString())
				.contains("\"simulacao_id\"")
				.contains("\"status\":\"assercao_violada\"")
				.doesNotContain("veredito");

			String desfecho = conforme("estado", stream.aguardarBloco(RAZAO_ASSERCAO, Duration.ofSeconds(30)));
			assertThat(desfecho).contains("\"status\":\"erro\"").contains("\"status_anterior\":\"simulando\"");

			// A mesma ordem dos outros dois, e pelo mesmo motivo: o `estado` terminal
			// fecha o
			// stream, então o `resultado` tem de chegar antes (skill sse).
			String recebido = stream.conteudo();
			assertThat(recebido.indexOf("event:resultado")).isLessThan(recebido.indexOf(desfecho));
			stream.aguardarFimDoStream(Duration.ofSeconds(15));
		}
		finally {
			stream.fechar();
		}

		assertThat(status(jobId)).isEqualTo("erro");
		assertThat(transicoes(jobId)).containsExactly("gerando_regra", "simulando", "erro");
		assertThat(motivoDaUltimaTransicao(jobId)).isEqualTo("assercao_violada");

		// Uma linha de resultado, e nela o que caracteriza este desfecho: a invariante
		// que
		// falhou está nomeada, e não há totais nem veredito. Gravar um total aqui seria
		// publicar um número que o próprio sandbox recusou.
		JsonNode resultado = JSON.readTree(Objects.requireNonNull(jdbc
			.queryForObject("SELECT to_jsonb(r) FROM resultados_simulacao r WHERE job_id = ?", String.class, jobId)));
		assertThat(resultado.path("status").asString()).isEqualTo("assercao_violada");
		assertThat(resultado.path("totais").isNull()).isTrue();
		assertThat(resultado.path("veredito").isNull()).isTrue();
		assertThat(resultado.path("codigo_gerado_id").asString()).isEqualTo(codigoGeradoId.toString());

		JsonNode assercoes = resultado.path("assercoes");
		ContratoDeEvento.validarDominio("resultado-assercoes.schema.json", assercoes.toString());
		JsonNode violada = assercoes.valueStream()
			.filter(item -> INVARIANTE.equals(item.path("nome").asString()))
			.findFirst()
			.orElseThrow(() -> new AssertionError("asserção %s ausente em %s".formatted(INVARIANTE, assercoes)));
		assertThat(violada.path("resultado").asString()).isEqualTo("violada");
		// O detalhe existe para uma pessoa entender o que falhou, e cita a comissão
		// negativa
		// que a regra devolveu.
		assertThat(violada.path("detalhe").asString()).contains("negativa");

		// A simulação continua ligada ao resultado: é por ela que as telas de relatório e
		// de
		// histórico alcançam o desfecho.
		assertThat(contar("simulacoes", jobId)).isEqualTo(1);
		assertThat(jdbc.queryForObject("SELECT resultado_id FROM simulacoes WHERE job_id = ?", UUID.class, jobId))
			.isEqualTo(UUID.fromString(resultado.path("id").asString()));

		// Asserção violada é desfecho classificado, não falha de infraestrutura: o
		// comando é
		// confirmado, não repetido nem mandado para a DLQ.
		assertThat(contexto.getBean(RabbitTemplate.class).receive("executar-codigo.dlq"))
			.as("comando na DLQ para um desfecho que o worker soube classificar")
			.isNull();
	}

	// --- No lugar do codegen --------------------------------------------------------

	private static void gravarArtefatosDoCodegen(UUID jobId, UUID regraId, UUID promptId, UUID codigoGeradoId)
			throws SQLException {
		try (Connection conexao = comoDono(); Statement comando = conexao.createStatement()) {
			comando.execute("""
					INSERT INTO prompts (id, job_id, no, conteudo, modelo, criado_em)
					VALUES ('%s', '%s', 'geracao_codigo', 'prompt do teste',
						'{"provedor":"teste","modelo":"escrito-a-mao","versao":"1"}'::jsonb, now())
					""".formatted(promptId, jobId));
			comando.execute("""
					INSERT INTO codigos_gerados (id, job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
					VALUES ('%s', '%s', '%s', 'python', %s, '%s', now())
					""".formatted(codigoGeradoId, jobId, regraId, literal(REGRA_COM_COMISSAO_NEGATIVA), promptId));
		}
	}

	private static String noConcluido(UUID jobId, UUID regraId, UUID promptId, UUID codigoGeradoId) {
		return """
				{"evento_id":"%s","job_id":"%s","no":"geracao_codigo","concluido_em":"%s",
				 "conclusao":{"resumo":"código escrito à mão pelo teste, com comissão negativa"},
				 "regra_id":"%s","prompt_id":"%s","codigo_gerado_id":"%s"}
				""".formatted(UUID.randomUUID(), jobId, Instant.now(), regraId, promptId, codigoGeradoId);
	}

	private static String etapaAlterada(UUID jobId) {
		return """
				{"job_id":"%s","etapa":"delegacao_worker","status":"iniciada"}
				""".formatted(jobId);
	}

	private static String executarCodigo(UUID jobId, UUID codigoGeradoId) {
		return """
				{"job_id":"%s","codigo_gerado_id":"%s","competencias":["%s"],"orcamento":485000.5}
				""".formatted(jobId, codigoGeradoId, String.join("\",\"", COMPETENCIAS_DO_DATASET));
	}

	/**
	 * Publica o que o codegen publicaria, validado antes de sair: um payload que o teste
	 * monta à mão e não confere seria um teste do próprio fixture, não do sistema.
	 */
	private static void publicar(String evento, String corpo) throws IOException {
		ContratoDeEvento.validar(evento, corpo);
		MessageProperties propriedades = new MessageProperties();
		propriedades.setContentType(MessageProperties.CONTENT_TYPE_JSON);
		propriedades.setType(evento);
		contexto.getBean(RabbitTemplate.class)
			.send(evento, new Message(corpo.getBytes(StandardCharsets.UTF_8), propriedades));
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

	private static Map<String, String> ambienteDeBanco(String variavelDoUsuario, String usuario) {
		return Map.of("POSTGRES_HOST", "postgres", "POSTGRES_PORT", "5432", "POSTGRES_DB", postgres.getDatabaseName(),
				variavelDoUsuario, usuario, variavelDoUsuario.replace("_USER", "_PASSWORD"), SENHA, "RABBITMQ_HOST",
				"rabbitmq", "RABBITMQ_PORT", "5672", "RABBITMQ_USER", rabbitmq.getAdminUsername(), "RABBITMQ_PASSWORD",
				rabbitmq.getAdminPassword());
	}

	private static String literal(String texto) {
		return "$sql$" + texto + "$sql$";
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
