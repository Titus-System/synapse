package synapse.api.job;

import java.io.IOException;
import java.math.BigDecimal;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ParametrosConfirmadosDtoTests {

	private static final UUID JOB_ID = UUID.fromString("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021");

	private static final UUID REGRA_ID = UUID.fromString("9c7d3e21-4a6b-4c8d-9e0f-1a2b3c4d5e6f");

	private static final String LEGADO = """
			{"job_id":"3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021",
			"regra_id":"9c7d3e21-4a6b-4c8d-9e0f-1a2b3c4d5e6f"}
			""";

	private static final JsonMapper JSON = new JsonMapper();

	private static final JsonMapper DECIMAL = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	@Test
	void serializaTodosOsCamposComOsNomesDoContratoEPrecisaoDecimal() throws IOException {
		String completo = comParametros("""
				"competencias":["2025-08","2025-11"],
				"orcamento":485000.1234567890123456789,"meta_venda":12000000.9876543210987654321
				""");

		String produzido = serializarEValidar(completo);

		assertThat(DECIMAL.readTree(produzido)).isEqualTo(DECIMAL.readTree(completo));
		assertThat(DECIMAL.readTree(produzido).path("orcamento").decimalValue())
			.isEqualByComparingTo(new BigDecimal("485000.1234567890123456789"));
		assertThat(DECIMAL.readTree(produzido).path("meta_venda").decimalValue())
			.isEqualByComparingTo(new BigDecimal("12000000.9876543210987654321"));
	}

	@ParameterizedTest
	@ValueSource(strings = { "\"competencias\":[\"2025-08\"],\"meta_venda\":12000000.1234567890123456789",
			"\"competencias\":[\"2025-08\"],\"orcamento\":485000.1234567890123456789",
			"\"competencias\":[\"2025-08\"]" })
	void omiteParametrosAusentesSemTransformaLosEmZeroOuNull(String parametros) throws IOException {
		String entrada = comParametros(parametros);

		String produzido = serializarEValidar(entrada);

		assertThat(DECIMAL.readTree(produzido)).isEqualTo(DECIMAL.readTree(entrada));
		assertThat(produzido).doesNotContain("null");
	}

	@Test
	void preservaOFormatoLegadoNaLeituraENoConstrutorDeDoisArgumentos() throws IOException {
		String lido = serializarEValidar(LEGADO);
		String construido = JSON.writeValueAsString(new ParametrosConfirmadosDto(JOB_ID, REGRA_ID));

		ContratoDeEvento.validar("parametros-confirmados", construido);
		assertThat(JSON.readTree(lido)).isEqualTo(JSON.readTree(LEGADO));
		assertThat(JSON.readTree(construido)).isEqualTo(JSON.readTree(LEGADO));
	}

	@Test
	void preservaValoresQueDependemDaValidacaoDeDominio() throws IOException {
		String entrada = comParametros("\"orcamento\":-1,\"meta_venda\":0,\"competencias\":[\"2099-01\"]");

		assertThat(JSON.readTree(serializarEValidar(entrada))).isEqualTo(JSON.readTree(entrada));
	}

	@ParameterizedTest
	@ValueSource(strings = { "job_id", "regra_id" })
	void contratoRejeitaNomeIncorretoDeCampoObrigatorio(String campo) {
		String invalido = LEGADO.replace(campo, campo + "_incorreto");

		assertThatThrownBy(() -> ContratoDeEvento.validar("parametros-confirmados", invalido))
			.isInstanceOf(AssertionError.class)
			.hasMessageContaining(campo);
	}

	@ParameterizedTest
	@ValueSource(strings = { "\"orcamento\":null", "\"orcamento\":\"100\"", "\"meta_venda\":null",
			"\"meta_venda\":\"100\"", "\"competencias\":null", "\"competencias\":[]", "\"competencias\":\"2025-08\"",
			"\"competencias\":[\"2025-13\"]" })
	void contratoRejeitaParametrosForaDoFormato(String parametros) {
		String invalido = comParametros(parametros);

		assertThatThrownBy(() -> ContratoDeEvento.validar("parametros-confirmados", invalido))
			.isInstanceOf(AssertionError.class)
			.hasMessageContaining("não conforme ao schema");
	}

	private static String serializarEValidar(String entrada) throws IOException {
		ParametrosConfirmadosDto dto = JSON.readValue(entrada, ParametrosConfirmadosDto.class);
		String produzido = JSON.writeValueAsString(dto);
		ContratoDeEvento.validar("parametros-confirmados", produzido);
		return produzido;
	}

	private static String comParametros(String parametros) {
		return LEGADO.stripTrailing().replace("}", "," + parametros + "}");
	}

}
