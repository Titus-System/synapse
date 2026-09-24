package synapse.api.job;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;

class HashDaRegraTests {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	@Test
	void hashIncluiCamposExtensiveisSemPerderPrecisao() {
		String especificacoes = """
				[{"ref":"elem.1","construto":"faixa_valor","efeito":{"tipo":"bonus_fixo",
				"valor":3500.1234567890123456789},"extensao":{"ativo":true}}]
				""";
		String hash = HashDaRegra.calcular(comEspecificacoes(especificacoes));
		assertThat(hash).isNotEqualTo(HashDaRegra.calcular(comEspecificacoes(especificacoes.replace("true", "false"))))
			.isNotEqualTo(HashDaRegra.calcular(comEspecificacoes(especificacoes.replace("6789", "6788"))));
	}

	@Test
	void ordemDeCamposExtensiveisNaoCriaUmaRepresentacaoDiferente() {
		String primeira = """
				[{"ref":"elem.1","construto":"faixa_valor","efeito":{"tipo":"bonus_fixo","valor":3500.125},
				"extensao":{"criterios":["a","b"],"ativo":true}}]
				""";
		String equivalente = """
				[{"extensao":{"ativo":true,"criterios":["a","b"]},"efeito":{"valor":3500.125,"tipo":"bonus_fixo"},
				"construto":"faixa_valor","ref":"elem.1"}]
				""";
		assertThat(HashDaRegra.calcular(comEspecificacoes(primeira)))
			.isEqualTo(HashDaRegra.calcular(comEspecificacoes(equivalente)));
	}

	private static RepresentacaoRegraDto comEspecificacoes(String especificacoes) {
		var nucleo = CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao().nucleo();
		return JSON.readValue(
				"{\"nucleo\":" + JSON.writeValueAsString(nucleo) + ",\"especificacoes\":" + especificacoes + "}",
				RepresentacaoRegraDto.class);
	}

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
