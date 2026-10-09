package synapse.api.submissoes;

import java.time.Duration;

import jakarta.validation.Validation;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

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

	@Test
	void processadorTemIntervaloEPrazoDeReservaPadrao() {
		// O perfil de teste desliga o agendamento; os prazos continuam os do default.
		var processor = this.properties.transcription().processor();
		assertThat(processor.pollInterval()).isEqualTo(Duration.ofSeconds(1));
		assertThat(processor.reservationTimeout()).isEqualTo(Duration.ofMinutes(5));
	}

	@ParameterizedTest
	@CsvSource({ "300000,true", "65001,true", "65000,false", "1000,false" })
	void prazoDeReservaMenorQueAChamadaEhRecusado(long prazoMs, boolean valido) {
		// Conexão + resposta somam 65 s: uma reserva que vence antes disso deixaria
		// outra instância mandar o mesmo áudio ao provedor.
		var configuracao = new AppProperties.Transcription("", "https://api.eu.deepgram.com", 5000, 60000,
				new AppProperties.Transcription.Processor(true, Duration.ofSeconds(1), Duration.ofMillis(prazoMs)));
		try (var factory = Validation.buildDefaultValidatorFactory()) {
			assertThat(factory.getValidator().validate(configuracao)).as("prazo de %d ms", prazoMs)
				.hasSize(valido ? 0 : 1);
		}
	}

}
