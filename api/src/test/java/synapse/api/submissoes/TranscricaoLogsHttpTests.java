package synapse.api.submissoes;

import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import synapse.api.core.config.AppProperties;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(properties = "logging.level.root=DEBUG")
@ActiveProfiles("test")
class TranscricaoLogsHttpTests {

	@ParameterizedTest
	@ValueSource(ints = { 200, 401 })
	void transporteEmDebugNaoRegistraCredencialNemConteudo(int status) throws Exception {
		String chave = "credencial-ficticia-privada";
		String texto = "texto-transcrito-privado";
		String audio = "audio-privado";
		var servidor = HttpServer
			.create(new InetSocketAddress(InetAddress.getByAddress(new byte[] { 127, 0, 0, 1 }), 0), 0);
		servidor.createContext("/v1/listen", exchange -> {
			exchange.getRequestBody().readAllBytes();
			byte[] resposta = ("{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":\"" + texto + "\"}]}]}}")
				.getBytes(StandardCharsets.UTF_8);
			exchange.sendResponseHeaders(status, resposta.length);
			try (var output = exchange.getResponseBody()) {
				output.write(resposta);
			}
			finally {
				exchange.close();
			}
		});
		servidor.start();
		try (var logs = new CapturaDeLog(org.slf4j.Logger.ROOT_LOGGER_NAME)) {
			var cliente = new ClienteDeepgram(new AppProperties.Transcription(chave,
					"http://127.0.0.1:" + servidor.getAddress().getPort(), 1000, 1000,
					new AppProperties.Transcription.Processor(false, Duration.ofSeconds(1), Duration.ofHours(1))));
			if (status == 200) {
				assertThat(cliente.transcrever(audio.getBytes(StandardCharsets.UTF_8), "audio/wav")).isEqualTo(texto);
			}
			else {
				assertThatThrownBy(() -> cliente.transcrever(audio.getBytes(StandardCharsets.UTF_8), "audio/wav"))
					.isInstanceOf(TranscricaoPermanenteException.class);
			}
			assertThat(logs.eventos()).isNotEmpty();
			for (var evento : logs.eventos()) {
				assertThat(CapturaDeLog.emJson(evento)).doesNotContain(chave, texto, audio);
			}
		}
		finally {
			servidor.stop(0);
		}
	}

}
