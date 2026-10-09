package synapse.api.submissoes;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

import org.springframework.http.InvalidMediaTypeException;
import org.springframework.http.MediaType;
import org.springframework.web.multipart.MultipartFile;

final class AudioSubmissao {

	private final byte[] bytes;

	private final String formato;

	private AudioSubmissao(byte[] bytes, String formato) {
		this.bytes = bytes;
		this.formato = formato;
	}

	byte[] bytes() {
		return this.bytes;
	}

	String formato() {
		return this.formato;
	}

	static final int LIMITE = 5 * 1024 * 1024;

	static AudioSubmissao ler(MultipartFile audio) throws IOException {
		if (audio.getSize() > LIMITE) {
			throw SubmissaoException.audioMuitoGrande();
		}
		String declarado = audio.getContentType();
		if (declarado == null) {
			throw SubmissaoException.audioInvalido();
		}
		MediaType tipo;
		try {
			tipo = MediaType.parseMediaType(declarado);
		}
		catch (InvalidMediaTypeException ex) {
			throw SubmissaoException.audioInvalido();
		}
		if (!"audio".equalsIgnoreCase(tipo.getType())) {
			throw SubmissaoException.audioInvalido();
		}
		byte[] bytes = audio.getBytes();
		String formato = tipo.getSubtype().toLowerCase(java.util.Locale.ROOT);
		boolean valido = switch (formato) {
			case "webm" -> comeca(bytes, 0, new byte[] { 0x1a, 0x45, (byte) 0xdf, (byte) 0xa3 });
			case "ogg" -> contem(bytes, 0, "OggS");
			case "wav" -> contem(bytes, 0, "RIFF") && contem(bytes, 8, "WAVE");
			case "mp4" -> mp4(bytes);
			default -> false;
		};
		if (!valido) {
			throw SubmissaoException.audioInvalido();
		}
		return new AudioSubmissao(bytes, formato);
	}

	private static boolean mp4(byte[] bytes) {
		if (bytes.length < 16 || !contem(bytes, 4, "ftyp")) {
			return false;
		}
		long tamanho = Integer.toUnsignedLong(ByteBuffer.wrap(bytes, 0, 4).getInt());
		return tamanho >= 16 && tamanho <= bytes.length;
	}

	private static boolean contem(byte[] bytes, int offset, String assinatura) {
		return comeca(bytes, offset, assinatura.getBytes(StandardCharsets.US_ASCII));
	}

	private static boolean comeca(byte[] bytes, int offset, byte[] assinatura) {
		return bytes.length >= offset + assinatura.length
				&& Arrays.equals(bytes, offset, offset + assinatura.length, assinatura, 0, assinatura.length);
	}

	String faixa() {
		return bytes.length <= 1024 * 1024 ? "ate_1_mb" : "de_1_a_5_mb";
	}

}
