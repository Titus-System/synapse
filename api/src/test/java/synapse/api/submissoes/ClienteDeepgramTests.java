package synapse.api.submissoes;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.net.InetSocketAddress;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.UUID;

import com.sun.net.httpserver.HttpServer;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion.VersionFlag;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import synapse.api.core.config.AppProperties;
import synapse.api.core.logging.CorrelationContext;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.catchThrowable;

class ClienteDeepgramTests {

	private static final String CHAVE = "chave-ficticia-do-teste";

	private static final String TEXTO = "  Comissão de 5% sobre vendas.  ";

	private static final String SUCESSO = "{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":\"" + TEXTO
			+ "\"}]}]}}";

	private final AtomicInteger chamadas = new AtomicInteger();

	private final ExecutorService executor = Executors.newCachedThreadPool();

	private HttpServer servidor;

	private int status = 200;

	private String resposta = SUCESSO;

	private String retryAfter = "";

	private long atraso;

	private long atrasoCorpo;

	private byte[] recebido = new byte[0];

	private String autorizacao = "";

	private String contentType = "";

	private String consulta = "";

	private String metodo = "";

	@BeforeEach
	void iniciar() throws IOException {
		this.servidor = HttpServer
			.create(new InetSocketAddress(InetAddress.getByAddress(new byte[] { 127, 0, 0, 1 }), 0), 0);
		this.servidor.setExecutor(this.executor);
		this.servidor.createContext("/v1/listen", (exchange) -> {
			this.chamadas.incrementAndGet();
			this.recebido = exchange.getRequestBody().readAllBytes();
			this.autorizacao = exchange.getRequestHeaders().getFirst("Authorization");
			this.contentType = exchange.getRequestHeaders().getFirst("Content-Type");
			this.consulta = exchange.getRequestURI().getRawQuery();
			this.metodo = exchange.getRequestMethod();
			if (this.atraso > 0) {
				try {
					Thread.sleep(this.atraso);
				}
				catch (InterruptedException ex) {
					Thread.currentThread().interrupt();
					exchange.close();
					return;
				}
			}
			if (!this.retryAfter.isEmpty()) {
				exchange.getResponseHeaders().add("Retry-After", this.retryAfter);
			}
			exchange.getResponseHeaders().add("Content-Type", "application/json");
			byte[] corpo = this.resposta.getBytes(StandardCharsets.UTF_8);
			exchange.sendResponseHeaders(this.status, corpo.length);
			try (var output = exchange.getResponseBody()) {
				if (this.atrasoCorpo > 0) {
					try {
						Thread.sleep(this.atrasoCorpo);
					}
					catch (InterruptedException ex) {
						Thread.currentThread().interrupt();
						return;
					}
				}
				output.write(corpo);
			}
			finally {
				exchange.close();
			}
		});
		this.servidor.start();
	}

	@AfterEach
	void fechar() {
		this.servidor.stop(0);
		this.executor.shutdownNow();
	}

	private AppProperties.Transcription configuracao(String chave, int timeout) {
		return new AppProperties.Transcription(chave, "http://127.0.0.1:" + this.servidor.getAddress().getPort(), 1000,
				timeout);
	}

	private ClienteDeepgram cliente() {
		return new ClienteDeepgram(configuracao(CHAVE, 2000));
	}

	@ParameterizedTest
	@CsvSource({ "audio/webm,audio/webm", "audio/ogg,audio/ogg", "audio/wav,audio/wav", "audio/mp4,audio/mp4",
			"audio/webm;codecs=opus,audio/webm", "audio/ogg; codecs=opus,audio/ogg" })
	void enviaAudioBinarioComConfiguracaoFixaEPreservaTexto(String formato, String mime) {
		byte[] audio = new byte[] { 0, 1, -1, 42 };
		assertThat(cliente().transcrever(audio, formato)).isEqualTo(TEXTO);
		assertThat(this.recebido).containsExactly(audio);
		assertThat(this.contentType).isEqualTo(mime);
		assertThat(this.autorizacao).isEqualTo("Token " + CHAVE);
		assertThat(this.metodo).isEqualTo("POST");
		assertThat(this.consulta).isEqualTo("model=nova-3&language=pt-BR&smart_format=false&mip_opt_out=true");
		assertThat(this.chamadas.get()).isEqualTo(1);
	}

	@ParameterizedTest
	@ValueSource(strings = { "audio/nao-suportado", "application/octet-stream", "" })
	void recusaFormatoAntesDeEnviar(String formato) {
		assertThatThrownBy(() -> cliente().transcrever(new byte[] { 1 }, formato))
			.isInstanceOf(TranscricaoPermanenteException.class);
		assertThat(this.chamadas.get()).isZero();
	}

	@Test
	void recusaAudioVazioAntesDeEnviar() {
		assertThatThrownBy(() -> cliente().transcrever(new byte[0], "audio/wav"))
			.isInstanceOf(TranscricaoPermanenteException.class);
		assertThat(this.chamadas.get()).isZero();
	}

	@ParameterizedTest
	@ValueSource(strings = { "", "  " })
	void semChaveInformaNaoConfiguradoENaoChamaProvedor(String chave) {
		var cliente = new ClienteDeepgram(configuracao(chave, 2000));
		assertThat(cliente.configurado()).isFalse();
		assertThatThrownBy(() -> cliente.transcrever(new byte[] { 1 }, "audio/wav"))
			.isInstanceOf(TranscricaoPermanenteException.class);
		assertThat(this.chamadas.get()).isZero();
	}

	@Test
	void comChaveInformaConfiguradoESegredoNaoApareceNaConfiguracao() {
		assertThat(cliente().configurado()).isTrue();
		assertThat(configuracao(CHAVE, 2000).toString()).doesNotContain(CHAVE);
	}

	@Test
	void chaveComQuebraDeLinhaNaoVazaEmExcecaoDeCabecalho() {
		var cliente = new ClienteDeepgram(configuracao(CHAVE + "\r\nvalor-privado", 2000));
		assertThatThrownBy(() -> cliente.transcrever(new byte[] { 1 }, "audio/wav"))
			.isInstanceOf(TranscricaoPermanenteException.class)
			.hasMessage("Falha permanente na transcrição.")
			.hasNoCause();
		assertThat(this.chamadas.get()).isZero();
	}

	@ParameterizedTest
	@ValueSource(ints = { 408, 429, 500, 502, 503, 504 })
	void errosRecuperaveisSaoTransitoriosSemRepetirAutomaticamente(int codigo) {
		this.status = codigo;
		this.resposta = CHAVE + TEXTO;
		Throwable erro = catchThrowable(() -> cliente().transcrever(new byte[] { 1 }, "audio/wav"));
		assertThat(erro).isInstanceOf(TranscricaoTransitoriaException.class);
		assertThat(erro).hasMessage("Falha transitória na transcrição.").hasNoCause();
		assertThat(this.chamadas.get()).isEqualTo(1);
	}

	@ParameterizedTest
	@ValueSource(ints = { 400, 401, 403, 404, 413, 415, 422, 302 })
	void errosDefinitivosSaoPermanentesSemExporCorpo(int codigo) {
		this.status = codigo;
		this.resposta = CHAVE + TEXTO;
		assertThatThrownBy(() -> cliente().transcrever(new byte[] { 1 }, "audio/wav"))
			.isInstanceOf(TranscricaoPermanenteException.class)
			.hasMessage("Falha permanente na transcrição.")
			.hasNoCause();
		assertThat(this.chamadas.get()).isEqualTo(1);
	}

	@Test
	void limiteDeTaxaCarregaSegundosDoRetryAfter() {
		this.status = 429;
		this.retryAfter = "12";
		var erro = (TranscricaoTransitoriaException) catchThrowable(
				() -> cliente().transcrever(new byte[] { 1 }, "audio/wav"));
		assertThat(erro.prazoParaNovaTentativa()).isEqualTo(Duration.ofSeconds(12));
		assertThat(erro.respostaInvalida()).isFalse();
	}

	@Test
	void limiteDeTaxaCarregaDataDoRetryAfter() {
		this.status = 429;
		this.retryAfter = ZonedDateTime.now(java.time.ZoneOffset.UTC)
			.plusSeconds(30)
			.format(DateTimeFormatter.RFC_1123_DATE_TIME);
		var erro = (TranscricaoTransitoriaException) catchThrowable(
				() -> cliente().transcrever(new byte[] { 1 }, "audio/wav"));
		assertThat(erro.prazoParaNovaTentativa()).isBetween(Duration.ofSeconds(25), Duration.ofSeconds(30));
	}

	@ParameterizedTest
	@ValueSource(
			strings = { "", "-1", "inválido", "999999999999999999999999999999999", "Wed, 01 Jan 2020 00:00:00 GMT" })
	void retryAfterAusenteOuInvalidoNaoQuebraClassificacao(String valor) {
		this.status = 429;
		this.retryAfter = valor;
		var erro = (TranscricaoTransitoriaException) catchThrowable(
				() -> cliente().transcrever(new byte[] { 1 }, "audio/wav"));
		assertThat(erro.prazoParaNovaTentativa()).isEqualTo(Duration.ZERO);
	}

	@ParameterizedTest
	@ValueSource(strings = { "não é json", "{}", "{\"results\":{\"channels\":[]}}",
			"{\"results\":{\"channels\":[{\"alternatives\":[]}]}}",
			"{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":null}]}]}}",
			"{\"results\":{\"channels\":[{\"alternatives\":[{\"transcript\":123}]}]}}" })
	void respostaInvalidaETransitoriaUmaVezEPermanenteSeRepetir(String respostaInvalida) {
		this.resposta = respostaInvalida;
		var cliente = cliente();
		var erro = (TranscricaoTransitoriaException) catchThrowable(
				() -> cliente.transcrever(new byte[] { 1 }, "audio/wav"));
		assertThat(erro.respostaInvalida()).isTrue();
		assertThatThrownBy(() -> cliente.transcrever(new byte[] { 1 }, "audio/wav", erro.respostaInvalida()))
			.isInstanceOf(TranscricaoPermanenteException.class);
		this.resposta = SUCESSO;
		assertThat(cliente.transcrever(new byte[] { 1 }, "audio/wav", true)).isEqualTo(TEXTO);
		this.resposta = respostaInvalida;
		assertThatThrownBy(() -> cliente.transcrever(new byte[] { 2 }, "audio/wav"))
			.isInstanceOf(TranscricaoTransitoriaException.class);
	}

	@Test
	void textoVazioValidoFicaParaOProcessamentoDecidir() {
		this.resposta = SUCESSO.replace(TEXTO, "");
		assertThat(cliente().transcrever(new byte[] { 1 }, "audio/wav")).isEmpty();
	}

	@Test
	void timeoutDeRespostaETransitorio() {
		this.atraso = 2000;
		var cliente = new ClienteDeepgram(configuracao(CHAVE, 200));
		assertThatThrownBy(() -> cliente.transcrever(new byte[] { 1 }, "audio/wav"))
			.isInstanceOf(TranscricaoTransitoriaException.class)
			.hasNoCause();
	}

	@Test
	void timeoutDuranteLeituraDoCorpoETransitorio() {
		this.atrasoCorpo = 2000;
		var cliente = new ClienteDeepgram(configuracao(CHAVE, 200));
		assertThatThrownBy(() -> cliente.transcrever(new byte[] { 1 }, "audio/wav"))
			.isInstanceOf(TranscricaoTransitoriaException.class)
			.hasNoCause();
	}

	@Test
	void falhaDeConexaoETransitoria() {
		var cliente = cliente();
		this.servidor.stop(0);
		assertThatThrownBy(() -> cliente.transcrever(new byte[] { 1 }, "audio/wav"))
			.isInstanceOf(TranscricaoTransitoriaException.class)
			.hasNoCause();
	}

	@ParameterizedTest
	@ValueSource(ints = { 200, 401, 429, 503 })
	void logsSerializadosPreservamCorrelacaoSemAudioTextoOuChave(int codigo) throws IOException {
		this.status = codigo;
		if (codigo != 200) {
			this.resposta = CHAVE + TEXTO;
		}
		String audioPrivado = "conteudo-privado-do-audio";
		UUID jobId = UUID.randomUUID();
		try (var logs = new CapturaDeLog(ClienteDeepgram.class);
				var scope = new CorrelationContext().abrir(jobId.toString(), UUID.randomUUID().toString())) {
			if (codigo == 200) {
				cliente().transcrever(audioPrivado.getBytes(StandardCharsets.UTF_8), "audio/wav");
			}
			else {
				Throwable erro = catchThrowable(
						() -> cliente().transcrever(audioPrivado.getBytes(StandardCharsets.UTF_8), "audio/wav"));
				assertThat(erro).hasNoCause();
				assertThat(erro.toString()).doesNotContain(CHAVE, TEXTO, audioPrivado);
			}
			assertThat(logs.eventos()).hasSize(2);
			for (var evento : logs.eventos()) {
				String serializado = CapturaDeLog.emJson(evento);
				var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
				var schema = JsonSchemaFactory.getInstance(VersionFlag.V202012)
					.getSchema(
							mapper.readTree(Files.readString(Path.of("../contracts/observability/log.schema.json"))));
				assertThat(schema.validate(mapper.readTree(serializado))).isEmpty();
				assertThat(serializado).contains(jobId.toString(), "synapse-api")
					.doesNotContain(CHAVE, TEXTO, audioPrivado, "exception");
			}
			assertThat(logs.eventos().getLast().getFormattedMessage())
				.isEqualTo(codigo == 200 ? "transcription finished" : "transcription failed");
		}
	}

}
