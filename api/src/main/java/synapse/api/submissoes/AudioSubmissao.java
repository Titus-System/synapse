package synapse.api.submissoes;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
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
			case "webm" -> webm(bytes);
			case "ogg" -> contem(bytes, 0, "OggS");
			case "wav" -> wav(bytes);
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
		long ftyp = Integer.toUnsignedLong(ByteBuffer.wrap(bytes, 0, 4).getInt());
		if (ftyp < 16 || ftyp > bytes.length) {
			return false;
		}
		boolean moov = false;
		boolean mdat = false;
		int offset = 0;
		while (offset + 8 <= bytes.length) {
			long tamanho = Integer.toUnsignedLong(ByteBuffer.wrap(bytes, offset, 4).getInt());
			int cabecalho = 8;
			if (tamanho == 1) {
				if (offset + 16 > bytes.length) {
					return false;
				}
				tamanho = ByteBuffer.wrap(bytes, offset + 8, 8).getLong();
				cabecalho = 16;
			}
			else if (tamanho == 0) {
				tamanho = bytes.length - offset;
			}
			if (tamanho < cabecalho || tamanho > bytes.length - offset) {
				return false;
			}
			moov |= contem(bytes, offset + 4, "moov") && tamanho > cabecalho;
			mdat |= contem(bytes, offset + 4, "mdat") && tamanho > cabecalho;
			offset += (int) tamanho;
		}
		return offset == bytes.length && moov && mdat;
	}

	private static boolean wav(byte[] bytes) {
		if (bytes.length < 44 || !contem(bytes, 0, "RIFF") || !contem(bytes, 8, "WAVE")) {
			return false;
		}
		var buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
		if (Integer.toUnsignedLong(buffer.getInt(4)) != bytes.length - 8L) {
			return false;
		}
		boolean formato = false;
		boolean dados = false;
		int alinhamento = 1;
		int offset = 12;
		while (offset + 8 <= bytes.length) {
			long tamanho = Integer.toUnsignedLong(buffer.getInt(offset + 4));
			if (tamanho > bytes.length - offset - 8L) {
				return false;
			}
			if (contem(bytes, offset, "fmt ")) {
				if (tamanho < 16 || buffer.getShort(offset + 8) == 0 || buffer.getShort(offset + 10) <= 0
						|| buffer.getInt(offset + 12) <= 0 || buffer.getInt(offset + 16) <= 0
						|| buffer.getShort(offset + 20) <= 0) {
					return false;
				}
				formato = true;
				int codigo = Short.toUnsignedInt(buffer.getShort(offset + 8));
				if (codigo == 1 || codigo == 3) {
					int bits = Short.toUnsignedInt(buffer.getShort(offset + 22));
					alinhamento = Short.toUnsignedInt(buffer.getShort(offset + 20));
					if (bits == 0 || bits % 8 != 0
							|| alinhamento != Short.toUnsignedInt(buffer.getShort(offset + 10)) * (bits / 8)
							|| buffer.getInt(offset + 16) != (long) buffer.getInt(offset + 12) * alinhamento) {
						return false;
					}
				}
				if (codigo == 0xfffe && tamanho < 40) {
					return false;
				}
			}
			if (contem(bytes, offset, "data")) {
				dados = formato && tamanho > 0 && tamanho % alinhamento == 0;
			}
			offset += 8 + (int) tamanho + (int) (tamanho % 2);
		}
		return offset == bytes.length && formato && dados;
	}

	private static boolean webm(byte[] bytes) {
		if (!comeca(bytes, 0, new byte[] { 0x1a, 0x45, (byte) 0xdf, (byte) 0xa3 })) {
			return false;
		}
		long cabecalho = tamanhoEbml(bytes, 4);
		int inicio = fimDoTamanhoEbml(bytes, 4);
		if (cabecalho < 0 || inicio < 0 || cabecalho > bytes.length - inicio) {
			return false;
		}
		int fim = inicio + (int) cabecalho;
		boolean tipo = false;
		for (int offset = inicio; offset + 2 < fim; offset++) {
			if (comeca(bytes, offset, new byte[] { 0x42, (byte) 0x82 })) {
				int valor = fimDoTamanhoEbml(bytes, offset + 2);
				tipo = tamanhoEbml(bytes, offset + 2) == 4 && valor >= 0 && valor + 4 <= fim
						&& contem(bytes, valor, "webm");
				break;
			}
		}
		if (!tipo || !comeca(bytes, fim, new byte[] { 0x18, 0x53, (byte) 0x80, 0x67 })) {
			return false;
		}
		int offset = fimDoTamanhoEbml(bytes, fim + 4);
		long segmento = tamanhoEbml(bytes, fim + 4);
		if (offset < 0 || (segmento > bytes.length - offset && !tamanhoDesconhecido(bytes, fim + 4))) {
			return false;
		}
		int limite = tamanhoDesconhecido(bytes, fim + 4) ? bytes.length : offset + (int) segmento;
		boolean trilhas = false;
		while (offset < limite) {
			int idFim = fimDoTamanhoEbml(bytes, offset);
			if (idFim < 0 || idFim - offset > 4) {
				return false;
			}
			int conteudo = fimDoTamanhoEbml(bytes, idFim);
			long tamanho = tamanhoEbml(bytes, idFim);
			if (conteudo < 0 || conteudo >= limite) {
				return false;
			}
			if (comeca(bytes, offset, new byte[] { 0x1f, 0x43, (byte) 0xb6, 0x75 })) {
				// Só inspeciona cabeçalhos; o conteúdo dos blocos não é decodificado.
				return trilhas && tamanho > 0 && (tamanho <= limite - conteudo || tamanhoDesconhecido(bytes, idFim));
			}
			if (tamanho < 0 || tamanho > limite - conteudo) {
				return false;
			}
			trilhas |= comeca(bytes, offset, new byte[] { 0x16, 0x54, (byte) 0xae, 0x6b }) && tamanho > 0;
			offset = conteudo + (int) tamanho;
		}
		return false;
	}

	private static boolean tamanhoDesconhecido(byte[] bytes, int offset) {
		int fim = fimDoTamanhoEbml(bytes, offset);
		return fim > 0 && tamanhoEbml(bytes, offset) == (1L << (7 * (fim - offset))) - 1;
	}

	private static int fimDoTamanhoEbml(byte[] bytes, int offset) {
		if (offset >= bytes.length) {
			return -1;
		}
		int tamanho = Integer.numberOfLeadingZeros(Byte.toUnsignedInt(bytes[offset])) - 23;
		return tamanho >= 1 && tamanho <= 8 && offset + tamanho <= bytes.length ? offset + tamanho : -1;
	}

	private static long tamanhoEbml(byte[] bytes, int offset) {
		int fim = fimDoTamanhoEbml(bytes, offset);
		if (fim < 0) {
			return -1;
		}
		long valor = Byte.toUnsignedInt(bytes[offset]) & (0xff >>> (fim - offset));
		for (int i = offset + 1; i < fim; i++) {
			valor = (valor << 8) | Byte.toUnsignedInt(bytes[i]);
		}
		return valor;
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
