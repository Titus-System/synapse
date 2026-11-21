package synapse.api.auditoria;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import synapse.api.job.ContratoDeEvento;

import static org.assertj.core.api.Assertions.assertThat;

class ResultadoAuditoriaTests {

	private static final JsonMapper JSON = new JsonMapper();

	@Test
	void serializaFontesComoObjetoConformeOContrato() throws Exception {
		String fontes = Files.readString(Path.of("../contracts/examples/domain/resultado-fontes.json"));
		ResultadoAuditoriaDto resultado = new ResultadoAuditoriaDto(UUID.randomUUID(), UUID.randomUUID(), "sucesso",
				"simulacao", null, null, null, "[]", null, null, fontes, Instant.now());

		String resposta = JSON.writeValueAsString(resultado);

		ContratoDeEvento.validarRespostaHttp("ResultadoAuditoria", resposta);
		JsonNode registro = JSON.readTree(resposta);
		assertThat(registro.path("fontes").isObject()).isTrue();
		assertThat(registro.path("fontes")).isEqualTo(JSON.readTree(fontes));
	}

	@ParameterizedTest
	@ValueSource(strings = { "sucesso", "erro_codigo", "assercao_violada", "erro_infra" })
	void omiteFontesQuandoNulasPreservandoOContratoLegado(String status) throws Exception {
		ResultadoAuditoriaDto resultado = new ResultadoAuditoriaDto(UUID.randomUUID(), UUID.randomUUID(), status,
				"simulacao", null, null, null, "[]", null, null, null, Instant.now());

		String resposta = JSON.writeValueAsString(resultado);

		ContratoDeEvento.validarRespostaHttp("ResultadoAuditoria", resposta);
		assertThat(JSON.readTree(resposta).has("fontes")).isFalse();
	}

}
