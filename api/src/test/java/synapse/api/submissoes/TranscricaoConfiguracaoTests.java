package synapse.api.submissoes;

import org.junit.jupiter.api.Test;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import synapse.api.core.config.AppProperties;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(properties = "app.transcription.api-key=")
@ActiveProfiles("test")
class TranscricaoConfiguracaoTests {

	@Autowired
	private ClienteDeepgram cliente;

	@Autowired
	private AppProperties properties;

	@Test
	void apiIniciaSemChaveEClienteFicaNaoConfigurado() {
		assertThat(this.cliente.configurado()).isFalse();
		assertThat(this.properties.transcription().baseUrl()).isEqualTo("https://api.eu.deepgram.com");
		assertThat(this.properties.transcription().connectTimeoutMs()).isEqualTo(5000);
		assertThat(this.properties.transcription().readTimeoutMs()).isEqualTo(60000);
	}

}
