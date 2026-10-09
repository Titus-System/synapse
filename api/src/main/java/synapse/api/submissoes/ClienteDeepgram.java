package synapse.api.submissoes;

import java.time.Duration;
import java.time.Instant;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Locale;
import java.util.Set;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.ObjectMapper;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

import synapse.api.core.config.AppProperties;

@Component
class ClienteDeepgram {

	private static final Logger log = LoggerFactory.getLogger(ClienteDeepgram.class);

	private static final Set<String> FORMATOS = Set.of("audio/webm", "audio/ogg", "audio/wav", "audio/mp4");

	private final AppProperties.Transcription properties;

	private final RestClient http;

	private final ObjectMapper json = new ObjectMapper();

	@Autowired
	ClienteDeepgram(AppProperties properties) {
		this(properties.transcription());
	}

	ClienteDeepgram(AppProperties.Transcription properties) {
		this.properties = properties;
		var factory = new SimpleClientHttpRequestFactory();
		factory.setConnectTimeout(Duration.ofMillis(properties.connectTimeoutMs()));
		factory.setReadTimeout(Duration.ofMillis(properties.readTimeoutMs()));
		this.http = RestClient.builder().requestFactory(factory).baseUrl(properties.baseUrl()).build();
	}

	boolean configurado() {
		return !this.properties.apiKey().isBlank();
	}

	String transcrever(byte[] audio, String formato) {
		return transcrever(audio, formato, false);
	}

	/** A T-237 preserva este sinal na tentativa do mesmo áudio, sem estado global. */
	String transcrever(byte[] audio, String formato, boolean respostaInvalidaAnterior) {
		log.info("transcription started");
		try {
			if (!configurado()) {
				throw permanente(0, "nao_configurado");
			}
			if (this.properties.apiKey().chars().anyMatch(Character::isISOControl)) {
				throw permanente(0, "credencial_invalida");
			}
			MediaType mime = formatoAceito(formato);
			if (audio.length == 0) {
				throw permanente(0, "audio_vazio");
			}
			String texto = this.http.post()
				.uri("/v1/listen?model=nova-3&language=pt-BR&smart_format=false&mip_opt_out=true")
				.header("Authorization", "Token " + this.properties.apiKey())
				.contentType(mime)
				.body(audio)
				.exchange((request, response) -> {
					int codigo = response.getStatusCode().value();
					if (codigo == 429) {
						throw transitoria(codigo, "limite_taxa",
								retryAfter(response.getHeaders().getFirst("Retry-After")), false);
					}
					if (codigo == 408 || codigo >= 500) {
						throw transitoria(codigo, "indisponibilidade", Duration.ZERO, false);
					}
					if (codigo != 200) {
						throw permanente(codigo, "recusado");
					}
					byte[] corpo = response.getBody().readAllBytes();
					String transcricao;
					try {
						var raiz = this.json.readTree(corpo);
						var campo = raiz.path("results")
							.path("channels")
							.path(0)
							.path("alternatives")
							.path(0)
							.path("transcript");
						if (!campo.isString()) {
							throw new IllegalArgumentException("Campo ausente");
						}
						transcricao = campo.asString();
					}
					catch (RuntimeException ex) {
						if (respostaInvalidaAnterior) {
							throw permanente(codigo, "resposta_invalida");
						}
						throw transitoria(codigo, "resposta_invalida", Duration.ZERO, true);
					}
					return transcricao;
				});
			log.info("transcription finished");
			return texto;
		}
		catch (ResourceAccessException ex) {
			throw transitoria(0, "transporte", Duration.ZERO, false);
		}
	}

	private MediaType formatoAceito(String formato) {
		MediaType tipo;
		try {
			tipo = MediaType.parseMediaType(formato);
		}
		catch (IllegalArgumentException ex) {
			throw permanente(0, "formato_invalido");
		}
		String mime = tipo.getType().toLowerCase(Locale.ROOT) + "/" + tipo.getSubtype().toLowerCase(Locale.ROOT);
		if (!FORMATOS.contains(mime)) {
			throw permanente(0, "formato_nao_suportado");
		}
		return MediaType.parseMediaType(mime);
	}

	private static Duration retryAfter(@Nullable String valor) {
		if (valor == null) {
			return Duration.ZERO;
		}
		try {
			return Duration.ofSeconds(Math.max(0, Long.parseLong(valor.trim())));
		}
		catch (NumberFormatException ex) {
			try {
				Duration prazo = Duration.between(Instant.now(),
						ZonedDateTime.parse(valor, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant());
				return prazo.isNegative() ? Duration.ZERO : prazo;
			}
			catch (DateTimeParseException invalida) {
				return Duration.ZERO;
			}
		}
	}

	private static TranscricaoPermanenteException permanente(int codigo, String motivo) {
		log.atWarn()
			.addKeyValue("status_code", codigo)
			.addKeyValue("failure_class", "permanente")
			.addKeyValue("reason", motivo)
			.log("transcription failed");
		return new TranscricaoPermanenteException();
	}

	private static TranscricaoTransitoriaException transitoria(int codigo, String motivo, Duration prazo,
			boolean respostaInvalida) {
		log.atWarn()
			.addKeyValue("status_code", codigo)
			.addKeyValue("failure_class", "transitoria")
			.addKeyValue("reason", motivo)
			.log("transcription failed");
		return new TranscricaoTransitoriaException(prazo, respostaInvalida);
	}

}
