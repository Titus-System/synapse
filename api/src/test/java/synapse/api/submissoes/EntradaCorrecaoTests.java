package synapse.api.submissoes;

import java.util.List;
import java.util.UUID;
import java.util.stream.Stream;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class EntradaCorrecaoTests {

	private static final UUID JOB = UUID.randomUUID();

	private static final JsonMapper JSON = new JsonMapper();

	static String corpo(String texto) {
		return "{\"finalidade\":\"correcao\",\"tipo\":\"texto\",\"job_id\":\"" + JOB + "\",\"texto\":"
				+ JSON.writeValueAsString(texto) + "}";
	}

	@Test
	void preservaTextoEContaPontosUnicodeNoLimiteDoContrato() {
		String texto = " 😀".repeat(2000);
		var entrada = EntradaSubmissao.ler(corpo(texto), "texto");
		assertThat(entrada.jobId()).isEqualTo(JOB);
		assertThat(entrada.texto()).isEqualTo(texto);
		assertThat(EntradaSubmissao.ler(corpo(" x "), "texto").texto()).isEqualTo(" x ");
	}

	@ParameterizedTest
	@MethodSource("invalidos")
	void recusaEntradaForaDoContrato(String corpo) {
		assertThatThrownBy(() -> EntradaSubmissao.ler(corpo, "texto")).isInstanceOfSatisfying(SubmissaoException.class,
				ex -> {
					assertThat(ex.status().value()).isEqualTo(400);
					assertThat(ex.codigo()).isEqualTo("requisicao_invalida");
				});
	}

	static Stream<String> invalidos() {
		String valido = corpo("correção privada");
		return Stream.of(corpo(""), corpo(" \n\t"), corpo("\u00a0\u3000"), corpo("a".repeat(4001)),
				corpo("😀".repeat(4001)), "null", "[]", "{", valido + " {}",
				valido.replace("\"correção privada\"", "null"), valido.replace("\"correção privada\"", "5"),
				valido.replace("\"texto\":\"correção privada\"", "\"outro\":true"),
				valido.replace(JOB.toString(), "1-1-1-1-1"), valido.replace(JOB.toString(), "não-é-uuid"),
				valido.replace("\"job_id\"", "\"outro_id\""), valido.replace("\"" + JOB + "\"", "null"),
				valido.replace("correcao", "outra"), valido.replace("\"tipo\":\"texto\"", "\"tipo\":\"voz\""));
	}

	@Test
	void entradaInicialMantemLimite() {
		String inicial = corpo("a".repeat(8000)).replace("correcao", "entrada_inicial");
		assertThat(EntradaSubmissao.ler(inicial, "texto").jobId()).isNull();
		assertThat(EntradaSubmissao.ler(inicial, "texto").texto()).hasSize(8000);
	}

	@Test
	void parametrosDaCorrecaoPorVozLevamSoOJob() {
		var entrada = EntradaSubmissao.ler("{\"finalidade\":\"correcao\",\"tipo\":\"voz\",\"job_id\":\"" + JOB + "\"}",
				"voz");
		assertThat(entrada.jobId()).isEqualTo(JOB);
		assertThat(entrada.texto()).isEmpty();
		for (String invalido : List.of("{\"finalidade\":\"correcao\",\"tipo\":\"voz\"}",
				"{\"finalidade\":\"correcao\",\"tipo\":\"voz\",\"job_id\":\"não-é-uuid\"}",
				"{\"finalidade\":\"correcao\",\"tipo\":\"texto\",\"job_id\":\"" + JOB + "\"}")) {
			assertThatThrownBy(() -> EntradaSubmissao.ler(invalido, "voz")).isInstanceOf(SubmissaoException.class);
		}
	}

}
