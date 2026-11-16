package synapse.api.auditoria;

import org.springframework.http.MediaType;

/**
 * O áudio gravado de uma entrada por voz. Classe, e não record: um record com componente
 * de array é recusado na revisão. O tipo e o formato vêm da lista fechada aceita no
 * envio, nunca do texto gravado.
 */
final class AudioAuditoria {

	private static final MediaType WEBM = new MediaType("audio", "webm");

	private static final MediaType OGG = new MediaType("audio", "ogg");

	private static final MediaType WAV = new MediaType("audio", "wav");

	private static final MediaType MP4 = new MediaType("audio", "mp4");

	private final byte[] bytes;

	private final MediaType tipo;

	private AudioAuditoria(byte[] bytes, MediaType tipo) {
		this.bytes = bytes;
		this.tipo = tipo;
	}

	/** Um formato fora da lista é falha, e a mensagem não repete o valor gravado. */
	static AudioAuditoria gravado(byte[] bytes, String formatoGravado) {
		MediaType tipo = switch (formatoGravado) {
			case "webm" -> WEBM;
			case "ogg" -> OGG;
			case "wav" -> WAV;
			case "mp4" -> MP4;
			default -> throw new IllegalStateException("formato de áudio fora da lista aceita no envio");
		};
		return new AudioAuditoria(bytes, tipo);
	}

	byte[] bytes() {
		return this.bytes;
	}

	MediaType tipo() {
		return this.tipo;
	}

	String formato() {
		return this.tipo.getSubtype();
	}

}
