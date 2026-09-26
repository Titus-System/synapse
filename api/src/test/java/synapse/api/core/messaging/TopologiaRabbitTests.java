package synapse.api.core.messaging;

import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.containers.Container.ExecResult;
import org.testcontainers.rabbitmq.RabbitMQContainer;

import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;

import synapse.api.ApiApplication;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Sobe a aplicação contra um RabbitMQ e lê a topologia de volta pelo
 * {@code rabbitmqadmin} embutido na imagem.
 */
@EnabledIf("dockerIsAvailable")
class TopologiaRabbitTests {

	private static final List<String> FILAS_SIMPLES = List.of(RabbitTopologyConfig.REGRA_SUBMETIDA,
			RabbitTopologyConfig.PARAMETROS_CONFIRMADOS, RabbitTopologyConfig.ETAPA_ALTERADA,
			RabbitTopologyConfig.NO_CONCLUIDO);

	private static final String FILA_CODEGEN_SIMULADA = "simulacao-concluida.codegen";

	private static final ObjectMapper MAPPER = new ObjectMapper();

	private static RabbitMQContainer rabbitmq;

	private @Nullable ConfigurableApplicationContext contexto;

	static boolean dockerIsAvailable() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	@BeforeAll
	static void subirOBroker() {
		rabbitmq = new RabbitMQContainer("rabbitmq:3.13-management-alpine");
		rabbitmq.start();
	}

	@AfterAll
	static void derrubarOBroker() {
		if (rabbitmq != null) {
			rabbitmq.stop();
		}
	}

	@BeforeEach
	void limparOBroker() throws Exception {
		for (String fila : List.of(RabbitTopologyConfig.REGRA_SUBMETIDA, RabbitTopologyConfig.PARAMETROS_CONFIRMADOS,
				RabbitTopologyConfig.ETAPA_ALTERADA, RabbitTopologyConfig.NO_CONCLUIDO,
				RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API, FILA_CODEGEN_SIMULADA)) {
			manter("delete", "queue", "name=" + fila);
		}
		manter("delete", "exchange", "name=" + RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE);
	}

	@AfterEach
	void derrubarOContexto() {
		if (this.contexto != null) {
			this.contexto.close();
		}
	}

	// --- Cenários ---------------------------------------------------------------------

	@Test
	void declaraAsQuatroFilasSimplesDuraveis() throws Exception {
		this.contexto = subirAApi();

		for (String fila : FILAS_SIMPLES) {
			JsonNode info = filaInfo(fila);
			assertThat(info.path("durable").asBoolean()).as("%s durável", fila).isTrue();
			assertThat(info.path("auto_delete").asBoolean()).as("%s não auto-delete", fila).isFalse();
		}
	}

	@Test
	void declaraAExchangeFanoutComAFilaDaApiLigada() throws Exception {
		this.contexto = subirAApi();

		JsonNode exchange = exchangeInfo(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE);
		assertThat(exchange.path("type").asText()).isEqualTo("fanout");
		assertThat(exchange.path("durable").asBoolean()).isTrue();

		JsonNode fila = filaInfo(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API);
		assertThat(fila.path("durable").asBoolean()).isTrue();

		assertThat(bindingExiste(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE,
				RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API))
			.as("simulacao-concluida.api ligada à exchange")
			.isTrue();
	}

	@Test
	void subirDuasVezesSeguidasNaoFalhaNemDuplica() throws Exception {
		this.contexto = subirAApi();
		this.contexto.close();

		this.contexto = subirAApi();

		for (String fila : FILAS_SIMPLES) {
			assertThat(filaInfo(fila).path("durable").asBoolean()).isTrue();
		}
		assertThat(bindingExiste(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE,
				RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API))
			.isTrue();
	}

	/** Como o codegen declararia o próprio lado da mesma exchange fanout. */
	@Test
	void naoFalhaQuandoOutroServicoJaDeclarouAExchangeEAFilaDele() throws Exception {
		manter("declare", "exchange", "name=" + RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE, "type=fanout",
				"durable=true");
		manter("declare", "queue", "name=" + FILA_CODEGEN_SIMULADA, "durable=true");
		manter("declare", "binding", "source=" + RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE,
				"destination=" + FILA_CODEGEN_SIMULADA);

		this.contexto = subirAApi();

		assertThat(bindingExiste(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE, FILA_CODEGEN_SIMULADA))
			.as("binding de outro serviço preservado")
			.isTrue();
		assertThat(bindingExiste(RabbitTopologyConfig.SIMULACAO_CONCLUIDA_EXCHANGE,
				RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API))
			.as("binding da api declarado ao lado do de outro serviço")
			.isTrue();
	}

	@Test
	void brokerInalcancavelDerrubaASubida() {
		assertThatThrownBy(() -> subirAApi(rabbitmq.getHost(), 1)).isInstanceOf(Exception.class);
	}

	// --- Apoio ---------------------------------------------------------------------

	private ConfigurableApplicationContext subirAApi() {
		return subirAApi(rabbitmq.getHost(), rabbitmq.getAmqpPort());
	}

	/**
	 * Sobe a aplicação pelo mesmo caminho de partida do compose - perfil {@code test}
	 * para o resto do contexto (sem Postgres), com o RabbitMQ religado a este broker de
	 * teste e a declaração de topologia (desligada no perfil de teste) ligada de volta.
	 */
	private ConfigurableApplicationContext subirAApi(String host, int port) {
		return new SpringApplicationBuilder(ApiApplication.class).web(WebApplicationType.NONE)
			.profiles("test")
			.run("--app.rabbitmq.host=" + host, "--app.rabbitmq.port=" + port,
					"--app.rabbitmq.user=" + rabbitmq.getAdminUsername(),
					"--app.rabbitmq.password=" + rabbitmq.getAdminPassword(), "--spring.rabbitmq.dynamic=true");
	}

	private static JsonNode filaInfo(String nome) throws Exception {
		return encontrar(listar("queues", "name", "durable", "auto_delete"), nome);
	}

	private static JsonNode exchangeInfo(String nome) throws Exception {
		return encontrar(listar("exchanges", "name", "type", "durable"), nome);
	}

	private static JsonNode encontrar(JsonNode lista, String nome) {
		for (JsonNode item : lista) {
			if (nome.equals(item.path("name").asText())) {
				return item;
			}
		}
		throw new AssertionError("'%s' não encontrado(a) no broker".formatted(nome));
	}

	private static boolean bindingExiste(String exchange, String fila) throws Exception {
		JsonNode bindings = listar("bindings", "source", "destination", "destination_type");
		for (JsonNode binding : bindings) {
			if (exchange.equals(binding.path("source").asText()) && fila.equals(binding.path("destination").asText())
					&& "queue".equals(binding.path("destination_type").asText())) {
				return true;
			}
		}
		return false;
	}

	/** {@code rabbitmqadmin list <tipo> --format=raw_json}: a mesma leitura do painel. */
	private static JsonNode listar(String tipo, String... campos) throws Exception {
		List<String> comando = new ArrayList<>(List.of("rabbitmqadmin", "--format=raw_json", "list", tipo));
		comando.addAll(List.of(campos));

		ExecResult resultado = rabbitmq.execInContainer(comando.toArray(new String[0]));
		return MAPPER.readTree(resultado.getStdout());
	}

	/**
	 * {@code rabbitmqadmin declare/delete}, para preparar o broker antes de cada cenário.
	 * Apagar algo que não existe termina em erro - esperado e ignorado aqui, porque a
	 * limpeza é best-effort, não a asserção do teste.
	 */
	private static void manter(String... argumentos) throws Exception {
		String[] comando = new String[argumentos.length + 1];
		comando[0] = "rabbitmqadmin";
		System.arraycopy(argumentos, 0, comando, 1, argumentos.length);
		rabbitmq.execInContainer(comando);
	}

}
