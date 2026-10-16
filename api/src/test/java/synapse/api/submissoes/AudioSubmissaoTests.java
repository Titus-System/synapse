package synapse.api.submissoes;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.web.MockMultipartFile;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AudioSubmissaoTests {

	@ParameterizedTest
	@ValueSource(strings = { "wav", "mp4", "webm" })
	void cabecalhosCoerentesPreservamBytes(String formato) throws Exception {
		byte[] bytes = switch (formato) {
			case "wav" -> AudioDeTeste.wav();
			case "mp4" -> AudioDeTeste.mp4();
			default -> AudioDeTeste.webm();
		};
		assertThat(AudioSubmissao.ler(new MockMultipartFile("audio", "regra", "audio/" + formato, bytes)).bytes())
			.containsExactly(bytes);
	}

	@ParameterizedTest
	@ValueSource(ints = { 4, 16, 24, 28, 32, 40 })
	void wavComTamanhosOuFormatoIncoerentesEhRecusado(int offset) {
		byte[] bytes = AudioDeTeste.wav();
		java.nio.ByteBuffer.wrap(bytes).order(java.nio.ByteOrder.LITTLE_ENDIAN).putInt(offset, -1);
		assertThatThrownBy(() -> AudioSubmissao.ler(new MockMultipartFile("audio", "regra", "audio/wav", bytes)))
			.isInstanceOf(SubmissaoException.class);
	}

	@ParameterizedTest
	@ValueSource(strings = { "doc_type", "trilhas", "cluster", "tamanho" })
	void webmPrecisaDoTipoEDosCabecalhosDoSegmento(String defeito) {
		byte[] bytes = AudioDeTeste.webm();
		int offset = switch (defeito) {
			case "doc_type" -> 8;
			case "trilhas" -> 17;
			case "cluster" -> 23;
			default -> 16;
		};
		bytes[offset] = 0;
		assertThatThrownBy(() -> AudioSubmissao.ler(new MockMultipartFile("audio", "regra", "audio/webm", bytes)))
			.isInstanceOf(SubmissaoException.class);
	}

	@ParameterizedTest
	@ValueSource(ints = { 16, 20, 32, 36 })
	void mp4PrecisaDeMetadadosEDadosComTamanhoValido(int offset) {
		byte[] bytes = AudioDeTeste.mp4();
		bytes[offset] = (byte) 0xff;
		assertThatThrownBy(() -> AudioSubmissao.ler(new MockMultipartFile("audio", "regra", "audio/mp4", bytes)))
			.isInstanceOf(SubmissaoException.class);
	}

	@Test
	void wavSoComAssinaturaNaoEhAudioValido() {
		byte[] bytes = new byte[] { 'R', 'I', 'F', 'F', 0, 0, 0, 0, 'W', 'A', 'V', 'E' };
		assertThatThrownBy(() -> AudioSubmissao.ler(new MockMultipartFile("audio", "regra.wav", "audio/wav", bytes)))
			.isInstanceOf(SubmissaoException.class);
	}

	@Test
	void mp4SoComFtypNaoEhAudioValido() {
		byte[] bytes = new byte[] { 0, 0, 0, 16, 'f', 't', 'y', 'p', 'M', '4', 'A', ' ', 0, 0, 0, 0 };
		assertThatThrownBy(() -> AudioSubmissao.ler(new MockMultipartFile("audio", "regra.mp4", "audio/mp4", bytes)))
			.isInstanceOf(SubmissaoException.class);
	}

}
