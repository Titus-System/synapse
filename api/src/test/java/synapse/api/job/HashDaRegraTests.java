package synapse.api.job;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class HashDaRegraTests {

	@Test
	void ignoraOrdemDasPropriedadesEscalaDecimalEConteudoForaDaRegra() {
		String original = CriarJobControllerTests.FORMULARIO;
		String equivalente = original.replace("0.025", "0.02500")
			.replace("\"inicio\":\"2025-11\",\"fim\":\"2025-11\"", "\"fim\":\"2025-11\",\"inicio\":\"2025-11\"")
			.replace("485000.1234567890123456789", "123")
			.replace("\"texto_livre\":null", "\"texto_livre\":\"observação original\"");
		String hash = HashDaRegra.calcular(CriarJobRequisicao.deJson(original).representacao());
		assertThat(hash).isEqualTo("a3e1ca57848e2dbecfac958034a64bb1106f24a345e3dd4181d77dc8b8de71bc")
			.isEqualTo(HashDaRegra.calcular(CriarJobRequisicao.deJson(equivalente).representacao()));
		assertThat(hash).isNotEqualTo(
				HashDaRegra.calcular(CriarJobRequisicao.deJson(original.replace("0.025", "0.03")).representacao()));
	}

	@Test
	void preservaPrecisaoDecimalDoPercentual() {
		String original = CriarJobControllerTests.FORMULARIO.replace("0.025", "0.025000000000000000001");
		assertThat(CriarJobRequisicao.deJson(original).representacao().nucleo().percentual())
			.isEqualByComparingTo("0.025000000000000000001");
		assertThat(HashDaRegra.calcular(CriarJobRequisicao.deJson(original).representacao())).isNotEqualTo(
				HashDaRegra.calcular(CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao()));
	}

}
