package synapse.api.job;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Lê um job pelo HTTP da aplicação que o teste subiu - a mesma consulta que a tela faz ao
 * recarregar - e confere o corpo contra {@code JobDetalhado}. Também extrai o
 * {@code motivo} de um bloco {@code estado} do stream, para comparar as duas saídas.
 */
final class ClienteDoJob {

	private static final HttpClient HTTP = HttpClient.newHttpClient();

	private static final JsonMapper JSON = new JsonMapper();

	private ClienteDoJob() {
	}

	static JsonNode consultar(int porta, UUID jobId) throws IOException, InterruptedException {
		HttpRequest requisicao = HttpRequest.newBuilder(URI.create("http://localhost:" + porta + "/jobs/" + jobId))
			.header("Accept", "application/json")
			.GET()
			.build();
		HttpResponse<String> resposta = HTTP.send(requisicao,
				HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
		assertThat(resposta.statusCode()).as(resposta.body()).isEqualTo(200);
		ContratoDeEvento.validarRespostaHttp("JobDetalhado", resposta.body());
		return JSON.readTree(resposta.body());
	}

	/** O JSON da linha {@code data:} de um bloco do stream. */
	static JsonNode dadosDoBloco(String bloco) {
		for (String linha : bloco.split("\n")) {
			if (linha.startsWith("data:")) {
				return JSON.readTree(linha.substring("data:".length()).strip());
			}
		}
		throw new AssertionError("bloco sem linha data: " + bloco);
	}

}
