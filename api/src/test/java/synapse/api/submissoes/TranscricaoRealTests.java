package synapse.api.submissoes;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

@SpringBootTest
@ActiveProfiles("test")
@EnabledIfEnvironmentVariable(named = "TRANSCRIPTION_REAL_TEST", matches = "true")
class TranscricaoRealTests {

	@Autowired
	private ClienteDeepgram cliente;

	@Test
	void transcreveFraseDeNucleoDaFixtureLocal() throws Exception {
		assumeTrue(this.cliente.configurado(), "Teste real não executado: chave não configurada.");
		String arquivo = System.getenv("TRANSCRIPTION_TEST_AUDIO_PATH");
		String formato = System.getenv("TRANSCRIPTION_TEST_AUDIO_FORMAT");
		String esperado = System.getenv("TRANSCRIPTION_TEST_EXPECTED_TEXT");
		assumeTrue(arquivo != null && formato != null && esperado != null,
				"Informe a fixture local, o formato e a frase de núcleo esperada.");
		String texto = this.cliente.transcrever(Files.readAllBytes(Path.of(arquivo)), formato);
		// Evita que uma asserção malsucedida exponha a transcrição nos relatórios.
		assertThat(texto.toLowerCase(Locale.ROOT).contains(esperado.toLowerCase(Locale.ROOT))).isTrue();
	}

}
