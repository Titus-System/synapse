package synapse.api.job;

import java.io.IOException;
import java.math.BigDecimal;
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
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
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
 * O fluxo inteiro com os três serviços reais: a api em processo, o codegen e o worker em
 * containers, um Postgres e um RabbitMQ reais e chamadas reais ao modelo. O teste entra
 * pelo caminho da tela de entrada, {@code POST /submissoes} com o texto da regra
 * ({@code frontend/src/features/entrada-regra/services/submissoes.api.ts}), acompanha o
 * job pelo stream e por {@code GET /jobs/{id}} e executa as ações das telas de simulação
 * e de finalização até o job ser salvo. {@link SubmissaoDeRegraFimAFimTests} cobre o
 * primeiro ciclo pelo formulário, que termina sem alternativa.
 * <p>
 * Os valores vêm do dataset embutido no sandbox. As vendas de nov/2025 somam R$
 * 13.271.681,51, então a meta dita no texto simula as vendas como estão. Com 3% sobre as
 * vendas dos vendedores de loja (cargo 100), a comissão do mês passa de R$ 527 mil e fica
 * abaixo de R$ 600 mil, e a dos demais cargos, que a regra não alcança, fica bem abaixo
 * de R$ 527 mil. Assim, R$ 527 mil exigem uma taxa menor que 3% e R$ 600 mil comportam os
 * 3%.
 */
@EnabledIf("ambienteCompleto")
class FluxoCompletoFimAFimTests {

	private static final String META_DO_TEXTO = "13271681.51";

	/**
	 * A regra só de núcleo que não cabe: o codegen propõe a taxa nova sem o usuário
	 * pedir, e a alternativa que cabe recebe a busca da meta maior.
	 */
	private static final String REGRA_QUE_NAO_CABE = """
			Simule novembro de 2025.

			A meta de vendas total é de R$ 13.271.681,51 e o orçamento total de comissões para o mesmo período é de R$ 527.000,00.

			A regra vale em todas as lojas e em todas as marcas, somente para o cargo 100, vendedor de loja, com comissão de 3% sobre suas vendas individuais.

			Não há vigência adicional: use as competências da simulação.
			""";

	/**
	 * A mesma regra, com orçamento que comporta os 3% e sem a meta, que a validação
	 * exige.
	 */
	private static final String REGRA_SEM_META = """
			Simule novembro de 2025.

			O orçamento total de comissões para o período é de R$ 600.000,00.

			A regra vale em todas as lojas e em todas as marcas, somente para o cargo 100, vendedor de loja, com comissão de 3% sobre suas vendas individuais.

			Não há vigência adicional: use as competências da simulação.
			""";

	private static final String CORRECAO_COM_A_META = "A meta de vendas total é de R$ 13.271.681,51.";

	/**
	 * A regra da demonstração: três cargos com taxas próprias, um bônus fixo e lojas e
	 * marcas fora dela, cuja comissão (R$ 1.140.409,88) a sugestão não move. O orçamento
	 * entra no lugar de {@code {orcamento}}.
	 */
	private static final String REGRA_DA_DEMONSTRACAO = """
			Simule agosto, setembro e novembro de 2025.

			A meta de vendas total para esse conjunto de competências é de R$ 30.000.000,00. O orçamento total de comissões para o mesmo período é de R$ {orcamento}.

			A regra vale somente para as lojas 13 e 58, nas marcas PRETO e BRANCO, e abrange os cargos 100, 150 e 200.

			As taxas são:
			- Vendedor de loja, cargo 100: 3% sobre suas vendas individuais.
			- Vendedor de balcão, cargo 200: 2,5% sobre suas vendas individuais.
			- Gerente de loja ou gerente de quiosque, cargo 150: 5% sobre as vendas totais da sua loja no mês.

			Para cada vendedor do cargo 100 abrangido pela regra, acrescente um bônus fixo de R$ 350,00 quando suas vendas individuais no mês forem iguais ou superiores a R$ 40.000,00. Pague esse bônus uma única vez por colaborador em cada competência.

			Os demais cargos e os registros fora das lojas e marcas indicadas devem conservar as comissões do baseline.

			Não há vigência adicional: aplique a regra às competências selecionadas para esta simulação.
			""";

	/**
	 * Os estados em que o job não sai mais sozinho. Esperar outro estado a partir de um
	 * deles só gastaria o tempo limite. A pausa por conflito só é parada com a rodada à
	 * espera do usuário: com a correção enviada, o job segue nela até a reextração
	 * terminar.
	 */
	private static final Set<String> PARADAS = Set.of("aguardando_confirmacao_parametros", "erro", "cancelado",
			"liberado", "arquivado");

	private static final Pattern AMOSTRA = Pattern.compile("^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\\{([^}]*)\\})? (\\S+)$",
			Pattern.MULTILINE);

	private static final String SENHA = "senha-de-teste";

	private static final String USUARIO_ID = "68686868-6868-4868-8868-686868686868";

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
	 * Docker, as imagens dos dois serviços e a do sandbox, e a chave do provedor: a
	 * extração, a correção e cada geração de código chamam o modelo.
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
			// Sem Keycloak a api resolve o primeiro usuário ativo, que será o dono
			// dos jobs.
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
			// O worker instancia o sandbox pelo daemon do host, um container
			// por execução.
			.withFileSystemBind(SOCKET_DOCKER.toString(), SOCKET_DOCKER.toString(), BindMode.READ_WRITE)
			// O container roda como appuser (uid 1000) e só alcança o daemon
			// com o grupo dono do socket, lido do próprio socket porque o nome
			// do grupo varia por distribuição.
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
	void regraQueNaoCabeGanhaTaxaQueCabeEMetaMaiorQueOUsuarioAceitaAntesDeSalvar() throws Exception {
		String codegenAntes = metricas(urlDoCodegen());
		String apiAntes = metricas(urlDaApi());

		UUID jobId = submeterTexto(REGRA_QUE_NAO_CABE);
		StreamCliente stream = conectarAoStream(jobId);
		try {
			// A taxa nova é proposta, gerada e simulada sem ação do usuário; a tela só
			// recebe a decisão quando a alternativa coube.
			aguardarStatus(jobId, "aguardando_decisao_usuario", Duration.ofMinutes(15));
			JsonNode job = consultar(jobId);
			assertThat(textos(job.path("competencias"))).containsExactly("2025-11");
			assertThat(job.path("orcamento").decimalValue()).isEqualByComparingTo("527000");
			assertThat(job.path("meta_venda").decimalValue()).isEqualByComparingTo(META_DO_TEXTO);

			JsonNode original = versao(job, 1);
			JsonNode alternativa = versao(job, 2);
			assertThat(job.path("regras").size()).as("só a primeira alternativa foi tentada").isEqualTo(2);
			assertThat(original.path("origem").asString()).isEqualTo("extracao");
			assertThat(alternativa.path("origem").asString()).isEqualTo("sugestao_adaptacao");
			conferirNucleoDosVendedoresDeLoja(original.path("representacao").path("nucleo"));
			conferirNucleoDosVendedoresDeLoja(alternativa.path("representacao").path("nucleo"));
			assertThat(original.path("representacao").path("nucleo").path("percentual").decimalValue())
				.isEqualByComparingTo("0.03");
			BigDecimal taxaNova = alternativa.path("representacao").path("nucleo").path("percentual").decimalValue();
			assertThat(taxaNova).isPositive().isLessThan(new BigDecimal("0.03"));

			JsonNode totaisOriginais = simulacaoDa(job, original).path("resultado").path("totais");
			assertThat(simulacaoDa(job, original).path("veredito").asString()).isEqualTo("inviavel");
			assertThat(totaisOriginais.path("simulado").decimalValue()).isGreaterThan(new BigDecimal("527000"));

			// A primeira alternativa cabe e aproveita o orçamento. A estimativa
			// só perde o truncamento da taxa, um centésimo de ponto percentual,
			// perto de R$ 1 mil nas vendas do mês, e a folga aceita aqui é de 1%
			// do orçamento. Uma taxa estimada sobre a comissão inteira, como se
			// nenhuma parte ficasse fora da regra, deixaria mais de R$ 100 mil
			// sem uso.
			JsonNode simulacaoDaAlternativa = simulacaoDa(job, alternativa);
			assertThat(simulacaoDaAlternativa.path("veredito").asString()).isEqualTo("viavel");
			assertThat(job.path("simulacao").path("regra_id").asString()).isEqualTo(id(alternativa).toString());
			BigDecimal simuladoDaAlternativa = simulacaoDaAlternativa.path("resultado")
				.path("totais")
				.path("simulado")
				.decimalValue();
			assertThat(simuladoDaAlternativa).isLessThanOrEqualTo(new BigDecimal("527000"))
				.isGreaterThan(new BigDecimal("521730"));

			// A alternativa coube com margem, então o codegen procura a maior meta em que
			// ela ainda cabe, com o código já gerado e sem chamar o modelo.
			JsonNode metaSugerida = aguardarMetaSugerida(jobId).path("meta_sugerida");
			BigDecimal meta = metaSugerida.path("meta_venda").decimalValue();
			assertThat(meta).as("busca sem solução: %s", metaSugerida).isGreaterThan(new BigDecimal(META_DO_TEXTO));
			assertThat(metaSugerida.path("orcamento").decimalValue()).isEqualByComparingTo("527000");
			assertThat(metaSugerida.path("total_simulado").decimalValue())
				.isLessThanOrEqualTo(new BigDecimal("527000"));

			JsonNode aceita = executarAcao(jobId, "aceitar_meta");
			assertThat(aceita.path("status").asString()).isEqualTo("aguardando_decisao_usuario");
			JsonNode vigente = aceita.path("simulacao");
			assertThat(vigente.path("regra_id").asString()).isEqualTo(id(alternativa).toString());
			assertThat(vigente.path("meta_venda").decimalValue()).isEqualByComparingTo(meta);
			assertThat(vigente.has("meta_sugerida_aceita_em")).isTrue();
			assertThat(vigente.path("resultado").path("totais").path("simulado").decimalValue())
				.isEqualByComparingTo(metaSugerida.path("total_simulado").decimalValue());

			JsonNode salvo = executarAcao(jobId, "salvar");
			assertThat(salvo.path("status").asString()).isEqualTo("liberado");

			// `liberado` é terminal, então o servidor encerra o stream.
			stream.aguardarFimDoStream(Duration.ofSeconds(15));
			validarStream(stream);
			assertThat(stream.conteudo()).contains("\"etapa\":\"sugestao_adaptacao\"")
				.doesNotContain("\"status\":\"sem_alternativa\"");
			// O resultado da regra original, o da alternativa e o da meta aceita. As
			// simulações da busca não são desfecho do job e não chegam ao cliente.
			assertThat(stream.contarOcorrencias("event:resultado")).isEqualTo(3);
		}
		finally {
			stream.fechar();
		}

		assertThat(transicoes(jobId)).containsExactly("gerando_regra", "simulando", "simulacao_inviavel",
				"gerando_regra", "simulando", "aguardando_decisao_usuario", "liberado");
		assertThat(jdbc.queryForList("SELECT tentativa FROM regras WHERE job_id = ? ORDER BY versao", Integer.class,
				jobId))
			.containsExactly(null, 1);
		// Um código por versão: a busca da meta reaproveita o da alternativa.
		assertThat(contar("codigos_gerados", jobId)).isEqualTo(2);
		assertThat(contarResultados(jobId, "simulacao")).isEqualTo(2);
		assertThat(contarResultados(jobId, "busca_meta")).isPositive();

		String codegenDepois = metricas(urlDoCodegen());
		assertThat(variacao(codegenAntes, codegenDepois, "codegen_sugestao_adaptacao_tentativas_total",
				"tentativa=\"1\"", "desfecho=\"viavel\""))
			.isEqualTo(1.0);
		assertThat(variacao(codegenAntes, codegenDepois, "codegen_busca_meta_total", "desfecho=\"sugerida\"",
				"motivo=\"encontrada\""))
			.isEqualTo(1.0);
		String apiDepois = metricas(urlDaApi());
		assertThat(variacao(apiAntes, apiDepois, "sugestao_adaptacao_proposta_consumo_total", "resultado=\"aplicada\"",
				"tentativa=\"1\""))
			.isEqualTo(1.0);
		assertThat(variacao(apiAntes, apiDepois, "meta_venda_aceita_total")).isEqualTo(1.0);
	}

	/**
	 * O código de cada alternativa é o da regra original com as taxas trocadas, sem
	 * passar pelo modelo. Com R$ 1,2 mi a busca chega a uma taxa que cabe. Com R$ 1 mi a
	 * comissão fora da regra já passa do orçamento: a alternativa da sondagem ainda é
	 * simulada e fica na tela, com a razão de nenhuma taxa caber.
	 */
	@ParameterizedTest(name = "orçamento de R$ {0}")
	@ValueSource(strings = { "1.200.000,00", "1.000.000,00" })
	void regraDaDemonstracaoTerminaComAAlternativaSimulada(String orcamento) throws Exception {
		String codegenAntes = metricas(urlDoCodegen());
		boolean cabe = orcamento.startsWith("1.200");
		UUID jobId = submeterTexto(REGRA_DA_DEMONSTRACAO.replace("{orcamento}", orcamento));
		StreamCliente stream = conectarAoStream(jobId);
		try {
			if (cabe) {
				aguardarStatus(jobId, "aguardando_decisao_usuario", Duration.ofMinutes(10));
			}
			else {
				await().atMost(Duration.ofMinutes(10))
					.pollInterval(Duration.ofSeconds(2))
					.untilAsserted(() -> assertThat(transicoes(jobId)).as(() -> diagnostico(jobId))
						.containsSubsequence("simulacao_inviavel", "gerando_regra", "simulando", "simulacao_inviavel"));
			}
			JsonNode job = consultar(jobId);
			JsonNode original = versao(job, 1);
			assertThat(simulacaoDa(job, original).path("resultado").path("totais").path("simulado").decimalValue())
				.isEqualByComparingTo("1227664.86");
			JsonNode ultima = versao(job, job.path("regras").size());
			assertThat(ultima.path("origem").asString()).isEqualTo("sugestao_adaptacao");
			JsonNode simulacao = job.path("simulacao");
			assertThat(simulacao.path("regra_id").asString()).isEqualTo(id(ultima).toString());
			assertThat(simulacao.path("status").asString()).isEqualTo("sucesso");
			if (cabe) {
				assertThat(simulacao.path("veredito").asString()).isEqualTo("viavel");
				assertThat(simulacao.path("resultado").path("totais").path("simulado").decimalValue())
					.isLessThanOrEqualTo(new BigDecimal("1200000"));
			}
			else {
				assertThat(job.path("regras").size()).isEqualTo(2);
				assertThat(simulacao.path("veredito").asString()).isEqualTo("inviavel");
				assertThat(job.path("status").asString()).isEqualTo("simulacao_inviavel");
				assertThat(job.path("motivo").asString()).contains("lojas fora da regra (R$ 1.140.409,88)");
			}
		}
		finally {
			stream.fechar();
		}

		int alternativas = consultar(jobId).path("regras").size() - 1;
		// Só a regra original passou pelo modelo; cada alternativa tem um código,
		// derivado.
		assertThat(jdbc.queryForObject("SELECT count(*) FROM prompts WHERE job_id = ? AND no = 'geracao_codigo'",
				Integer.class, jobId))
			.isEqualTo(1);
		assertThat(contar("codigos_gerados", jobId)).isEqualTo(1 + alternativas);
		assertThat(variacao(codegenAntes, metricas(urlDoCodegen()), "codegen_derivacao_codigo_total",
				"desfecho=\"derivado\""))
			.isEqualTo(alternativas);
	}

	@Test
	void textoSemMetaPausaParaCorrecaoEACorrecaoSegueAteASimulacaoSalva() throws Exception {
		UUID jobId = submeterTexto(REGRA_SEM_META);
		StreamCliente stream = conectarAoStream(jobId);
		try {
			aguardarStatus(jobId, "aguardando_confirmacao_parametros", Duration.ofMinutes(5));
			JsonNode rodadas = consultarRodadas(jobId);
			assertThat(rodadas.size()).isEqualTo(1);
			assertThat(rodadas.get(0).path("estado").asString()).isEqualTo("pendente");
			assertThat(elementosDosConflitos(rodadas.get(0))).contains("parametros.meta_venda");
			// O chatbot abre pela transição que chega no stream.
			conforme("estado",
					stream.aguardarBloco("\"status\":\"aguardando_confirmacao_parametros\"", Duration.ofSeconds(30)));

			corrigir(jobId, CORRECAO_COM_A_META);
			aguardarStatus(jobId, "aguardando_decisao_usuario", Duration.ofMinutes(10));

			JsonNode job = consultar(jobId);
			assertThat(job.path("meta_venda").decimalValue()).isEqualByComparingTo(META_DO_TEXTO);
			assertThat(job.path("orcamento").decimalValue()).isEqualByComparingTo("600000");
			assertThat(textos(job.path("competencias"))).containsExactly("2025-11");
			JsonNode corrigida = versao(job, 2);
			assertThat(job.path("regras").size()).isEqualTo(2);
			assertThat(versao(job, 1).path("origem").asString()).isEqualTo("extracao");
			assertThat(corrigida.path("origem").asString()).isEqualTo("correcao");
			conferirNucleoDosVendedoresDeLoja(corrigida.path("representacao").path("nucleo"));
			assertThat(corrigida.path("representacao").path("nucleo").path("percentual").decimalValue())
				.isEqualByComparingTo("0.03");

			JsonNode rodada = consultarRodadas(jobId).get(0);
			assertThat(rodada.path("estado").asString()).isEqualTo("corrigida");
			assertThat(rodada.path("regra_resultante_id").asString()).isEqualTo(id(corrigida).toString());

			JsonNode simulacao = job.path("simulacao");
			assertThat(simulacao.path("regra_id").asString()).isEqualTo(id(corrigida).toString());
			assertThat(simulacao.path("veredito").asString()).isEqualTo("viavel");
			assertThat(simulacao.path("meta_venda").decimalValue()).isEqualByComparingTo(META_DO_TEXTO);
			assertThat(simulacao.path("resultado").path("totais").path("simulado").decimalValue())
				.isLessThanOrEqualTo(new BigDecimal("600000"));

			JsonNode metaSugerida = aguardarMetaSugerida(jobId).path("meta_sugerida");
			assertThat(metaSugerida.path("meta_venda").decimalValue()).as("busca sem solução: %s", metaSugerida)
				.isGreaterThan(new BigDecimal(META_DO_TEXTO));

			// Salvar sem aceitar a meta mantém a simulação na meta dita pelo usuário.
			JsonNode salvo = executarAcao(jobId, "salvar");
			assertThat(salvo.path("status").asString()).isEqualTo("liberado");
			assertThat(salvo.path("simulacao").path("meta_venda").decimalValue()).isEqualByComparingTo(META_DO_TEXTO);
			assertThat(salvo.path("simulacao").has("meta_sugerida_aceita_em")).isFalse();

			stream.aguardarFimDoStream(Duration.ofSeconds(15));
			validarStream(stream);
		}
		finally {
			stream.fechar();
		}

		assertThat(transicoes(jobId)).containsExactly("gerando_regra", "aguardando_confirmacao_parametros",
				"gerando_regra", "simulando", "aguardando_decisao_usuario", "liberado");
		assertThat(contar("codigos_gerados", jobId)).isEqualTo(1);
		assertThat(contarResultados(jobId, "simulacao")).isEqualTo(1);
	}

	// --- O que a tela faz ----------------------------------------------------------

	private static UUID submeterTexto(String texto) throws Exception {
		HttpResponse<String> resposta = enviar("POST", "/submissoes",
				JSON.writeValueAsString(Map.of("finalidade", "entrada_inicial", "tipo", "texto", "texto", texto)));
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(201);
		ContratoDeEvento.validarRespostaHttp("SubmissaoCriada", resposta.body());
		JsonNode criada = JSON.readTree(resposta.body());
		assertThat(criada.path("job").path("status").asString()).isEqualTo("gerando_regra");
		return UUID.fromString(criada.path("job").path("id").asString());
	}

	private static void corrigir(UUID jobId, String texto) throws Exception {
		HttpResponse<String> resposta = enviar("POST", "/submissoes", JSON.writeValueAsString(
				Map.of("finalidade", "correcao", "tipo", "texto", "job_id", jobId.toString(), "texto", texto)));
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(201);
	}

	private static JsonNode executarAcao(UUID jobId, String acao) throws Exception {
		HttpResponse<String> resposta = enviar("POST", "/jobs/" + jobId + "/actions", "{\"acao\":\"" + acao + "\"}");
		assertThat(resposta.statusCode()).as("%s: %s", acao, resposta.body()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("JobDetalhado", resposta.body());
		return JSON.readTree(resposta.body());
	}

	private static JsonNode consultar(UUID jobId) throws Exception {
		HttpResponse<String> resposta = enviar("GET", "/jobs/" + jobId, null);
		assertThat(resposta.statusCode()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("JobDetalhado", resposta.body());
		return JSON.readTree(resposta.body());
	}

	private static JsonNode consultarRodadas(UUID jobId) throws Exception {
		HttpResponse<String> resposta = enviar("GET", "/jobs/" + jobId + "/rodadas", null);
		assertThat(resposta.statusCode()).isEqualTo(200);
		JsonNode rodadas = JSON.readTree(resposta.body());
		for (JsonNode rodada : rodadas) {
			ContratoDeEvento.validarRespostaHttp("Rodada", JSON.writeValueAsString(rodada));
		}
		return rodadas;
	}

	private static StreamCliente conectarAoStream(UUID jobId) throws Exception {
		return new StreamCliente(
				HTTP.send(HttpRequest.newBuilder(URI.create(urlDaApi() + "/jobs/" + jobId + "/events")).GET().build(),
						HttpResponse.BodyHandlers.ofInputStream()));
	}

	private static HttpResponse<String> enviar(String metodo, String caminho, @Nullable String corpo) throws Exception {
		HttpRequest.Builder requisicao = HttpRequest.newBuilder(URI.create(urlDaApi() + caminho));
		if (corpo == null) {
			requisicao.GET();
		}
		else {
			requisicao.header("Content-Type", "application/json")
				.method(metodo, HttpRequest.BodyPublishers.ofString(corpo));
		}
		return HTTP.send(requisicao.build(), HttpResponse.BodyHandlers.ofString());
	}

	// --- Espera e leitura ----------------------------------------------------------

	/**
	 * Espera o estado e desiste ao ver o job parado em outro. A mensagem da falha leva o
	 * motivo e os conflitos da última rodada, que dizem se a extração ou a geração do
	 * modelo levou o job para outro caminho.
	 */
	private static void aguardarStatus(UUID jobId, String esperado, Duration limite) {
		await().atMost(limite)
			.pollInterval(Duration.ofSeconds(2))
			.failFast("o job parou antes de chegar a " + esperado,
					() -> assertThat(parado(jobId, esperado)).as(() -> diagnostico(jobId)).isFalse())
			.untilAsserted(() -> assertThat(status(jobId)).as(() -> diagnostico(jobId)).isEqualTo(esperado));
	}

	private static boolean parado(UUID jobId, String esperado) {
		String atual = status(jobId);
		if (atual.equals(esperado) || !PARADAS.contains(atual)) {
			return false;
		}
		return !atual.equals("aguardando_confirmacao_parametros") || "pendente".equals(estadoDaUltimaRodada(jobId));
	}

	private static @Nullable String estadoDaUltimaRodada(UUID jobId) {
		List<String> estados = jdbc.queryForList(
				"SELECT estado FROM rodadas_correcao WHERE job_id = ? ORDER BY criada_em DESC LIMIT 1", String.class,
				jobId);
		return estados.isEmpty() ? null : estados.getFirst();
	}

	/** A busca termina com {@code meta_sugerida}; enquanto corre, o job a anuncia. */
	private static JsonNode aguardarMetaSugerida(UUID jobId) throws Exception {
		await().atMost(Duration.ofMinutes(15))
			.pollInterval(Duration.ofSeconds(3))
			.untilAsserted(
					() -> assertThat(consultar(jobId).path("meta_sugerida").isObject()).as(() -> diagnostico(jobId))
						.isTrue());
		JsonNode job = consultar(jobId);
		assertThat(job.path("busca_meta_em_curso").asBoolean(false)).isFalse();
		return job;
	}

	private static String diagnostico(UUID jobId) {
		try {
			JsonNode job = consultar(jobId);
			List<String> conflitos = new ArrayList<>();
			JsonNode rodadas = consultarRodadas(jobId);
			if (!rodadas.isEmpty()) {
				for (JsonNode conflito : rodadas.get(rodadas.size() - 1).path("conflitos")) {
					conflitos.add(textos(conflito.path("elementos")) + ": " + conflito.path("motivo").asString());
				}
			}
			List<String> especificacoes = new ArrayList<>();
			JsonNode regras = job.path("regras");
			for (JsonNode regra : regras) {
				for (JsonNode especificacao : regra.path("representacao").path("especificacoes")) {
					especificacoes.add("v%d %s:%s \"%s\"".formatted(regra.path("versao").asInt(),
							especificacao.path("ref").asString(), especificacao.path("construto").asString(),
							especificacao.path("descricao").asString("")));
				}
			}
			return "status=%s motivo=%s versoes=%d especificacoes=%s conflitos=%s execucao=%s".formatted(
					job.path("status").asString(), job.path("motivo").asString(""), regras.size(), especificacoes,
					conflitos, ultimaExecucao(jobId));
		}
		catch (Exception ex) {
			return "job não consultado: " + ex.getClass().getSimpleName();
		}
	}

	/**
	 * A causa que o worker gravou na última execução, sem a mensagem nem o traceback, que
	 * vêm do código gerado.
	 */
	private static String ultimaExecucao(UUID jobId) {
		return jdbc.queryForList("""
				SELECT status, diagnostico->>'causa' AS causa, diagnostico->'falha'->>'tipo' AS falha,
				       diagnostico->'elementos_ausentes' AS ausentes,
				       diagnostico->'elementos_fora_da_regra' AS fora_da_regra
				FROM resultados_simulacao WHERE job_id = ? ORDER BY criado_em DESC LIMIT 1
				""", jobId).toString();
	}

	private static String status(UUID jobId) {
		return Objects.requireNonNull(jdbc.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId));
	}

	private static JsonNode versao(JsonNode job, int versao) {
		for (JsonNode regra : job.path("regras")) {
			if (regra.path("versao").asInt() == versao) {
				return regra;
			}
		}
		throw new AssertionError("versão " + versao + " ausente: " + diagnosticoDasVersoes(job));
	}

	private static String diagnosticoDasVersoes(JsonNode job) {
		List<String> versoes = new ArrayList<>();
		for (JsonNode regra : job.path("regras")) {
			versoes.add(regra.path("versao").asInt() + ":" + regra.path("origem").asString());
		}
		return versoes.toString();
	}

	private static JsonNode simulacaoDa(JsonNode job, JsonNode regra) {
		for (JsonNode simulacao : job.path("simulacoes")) {
			if (simulacao.path("regra_id").asString().equals(regra.path("id").asString())) {
				return simulacao;
			}
		}
		throw new AssertionError("versão " + regra.path("versao").asInt() + " sem simulação");
	}

	private static UUID id(JsonNode regra) {
		return UUID.fromString(regra.path("id").asString());
	}

	/**
	 * O escopo que o texto descreve: todas as lojas e marcas, só o cargo 100. Lista vazia
	 * é o "todos" do contrato.
	 */
	private static void conferirNucleoDosVendedoresDeLoja(JsonNode nucleo) {
		assertThat(textos(nucleo.path("loja"))).as("loja: %s", nucleo).isEmpty();
		assertThat(textos(nucleo.path("marca"))).as("marca: %s", nucleo).isEmpty();
		assertThat(textos(nucleo.path("cargo"))).as("cargo: %s", nucleo).containsExactly("100");
	}

	private static List<String> elementosDosConflitos(JsonNode rodada) {
		List<String> elementos = new ArrayList<>();
		for (JsonNode conflito : rodada.path("conflitos")) {
			elementos.addAll(textos(conflito.path("elementos")));
		}
		return elementos;
	}

	private static List<String> textos(JsonNode lista) {
		return lista.valueStream().map(JsonNode::asString).toList();
	}

	private static List<String> transicoes(UUID jobId) {
		return jdbc.queryForList("SELECT status_novo FROM job_transicoes WHERE job_id = ? ORDER BY ocorrido_em, id",
				String.class, jobId);
	}

	private static int contar(String tabela, UUID jobId) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT count(*) FROM " + tabela + " WHERE job_id = ?", Integer.class, jobId));
	}

	private static int contarResultados(UUID jobId, String proposito) {
		return Objects.requireNonNull(
				jdbc.queryForObject("SELECT count(*) FROM resultados_simulacao WHERE job_id = ? AND proposito = ?",
						Integer.class, jobId, proposito));
	}

	// --- Contratos e métricas ------------------------------------------------------

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

	private static void validarStream(StreamCliente stream) throws IOException {
		for (String bloco : stream.conteudo().split("\\n\\n")) {
			Matcher nome = Pattern.compile("(?m)^event:(.+)$").matcher(bloco);
			Matcher dados = Pattern.compile("(?m)^data:(.+)$").matcher(bloco);
			if (nome.find() && dados.find()) {
				ContratoDeEvento.validarEventoDoStream(nome.group(1).strip(), dados.group(1).strip());
			}
		}
	}

	private static String metricas(String base) throws Exception {
		HttpResponse<String> resposta = HTTP.send(HttpRequest.newBuilder(URI.create(base + "/metrics")).GET().build(),
				HttpResponse.BodyHandlers.ofString());
		assertThat(resposta.statusCode()).isEqualTo(200);
		return resposta.body();
	}

	/**
	 * A diferença de uma amostra entre duas leituras. Os dois testes dividem os serviços,
	 * então só a diferença é do teste; os rótulos valem em qualquer ordem, porque cada
	 * serviço os escreve na sua.
	 */
	private static double variacao(String antes, String depois, String nome, String... rotulos) {
		return amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos);
	}

	private static double amostra(String exposicao, String nome, String... rotulos) {
		double soma = 0;
		Matcher linha = AMOSTRA.matcher(exposicao);
		while (linha.find()) {
			String rotulosDaLinha = Objects.requireNonNullElse(linha.group(2), "");
			if (linha.group(1).equals(nome) && List.of(rotulosDaLinha.split(",")).containsAll(List.of(rotulos))) {
				soma += Double.parseDouble(linha.group(3));
			}
		}
		return soma;
	}

	// --- Ambiente ------------------------------------------------------------------

	private static String urlDaApi() {
		return "http://localhost:" + porta;
	}

	private static String urlDoCodegen() {
		return "http://" + codegen.getHost() + ":" + codegen.getMappedPort(8000);
	}

	/**
	 * Variáveis que codegen e worker compartilham: o mesmo Postgres e o mesmo RabbitMQ,
	 * pelos apelidos de rede, com o usuário de banco próprio de cada serviço.
	 */
	private static Map<String, String> ambienteDeBanco(String variavelDoUsuario, String usuario) {
		return Map.of("POSTGRES_HOST", "postgres", "POSTGRES_PORT", "5432", "POSTGRES_DB", postgres.getDatabaseName(),
				variavelDoUsuario, usuario, variavelDoUsuario.replace("_USER", "_PASSWORD"), SENHA, "RABBITMQ_HOST",
				"rabbitmq", "RABBITMQ_PORT", "5672", "RABBITMQ_USER", rabbitmq.getAdminUsername(), "RABBITMQ_PASSWORD",
				rabbitmq.getAdminPassword());
	}

	private static @Nullable String chaveDoProvedor() {
		String chave = System.getenv("GOOGLE_API_KEY");
		return chave == null || chave.isBlank() ? null : chave;
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
