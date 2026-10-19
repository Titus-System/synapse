package synapse.api.job;

import java.math.BigDecimal;
import java.util.List;

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
	void nucleoSemPercentualTemHashProprio() {
		RepresentacaoRegraDto semPercentual = JSON.readValue("""
				{"nucleo":{"marca":["10"]},"especificacoes":[]}
				""", RepresentacaoRegraDto.class);
		RepresentacaoRegraDto comPercentual = JSON.readValue("""
				{"nucleo":{"marca":["10"],"percentual":0.025},"especificacoes":[]}
				""", RepresentacaoRegraDto.class);

		assertThat(HashDaRegra.calcular(semPercentual)).hasSize(64)
			.isEqualTo(HashDaRegra.calcular(semPercentual))
			.isNotEqualTo(HashDaRegra.calcular(comPercentual));
	}

	/**
	 * O hash de uma versão sem parâmetros é o de antes da coluna existir - o valor fixo
	 * em {@link #ignoraOrdemDasPropriedadesEscalaDecimalEConteudoForaDaRegra} -, e um
	 * objeto de parâmetros vazio já é outra coisa: a versão nascida de um texto que não
	 * disse parâmetro algum tem {@code parametros = {}}, não nulo.
	 */
	@Test
	void versaoSemParametrosConservaOHashEUmObjetoVazioJaDaOutro() {
		RepresentacaoRegraDto regra = CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao();

		assertThat(HashDaRegra.calcular(regra, null)).isEqualTo(HashDaRegra.calcular(regra))
			.isEqualTo("a3e1ca57848e2dbecfac958034a64bb1106f24a345e3dd4181d77dc8b8de71bc");
		assertThat(HashDaRegra.calcular(regra, ParametrosDaSimulacao.NENHUM)).hasSize(64)
			.isEqualTo(HashDaRegra.calcular(regra, ParametrosDaSimulacao.NENHUM))
			.isNotEqualTo(HashDaRegra.calcular(regra));
	}

	/**
	 * Cada parâmetro muda o hash por conta própria, e dois valores monetários que só
	 * diferem em zeros à direita são o mesmo valor. É o que faz uma correção que muda só
	 * o orçamento gerar versão nova, e uma que repete o mesmo valor não gerar.
	 */
	@Test
	void cadaParametroMudaOHashEEscalaDecimalNao() {
		RepresentacaoRegraDto regra = CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao();
		var completos = parametros("500000", "12000000", "2025-09", "2025-10");

		assertThat(HashDaRegra.calcular(regra, completos))
			.isEqualTo(HashDaRegra.calcular(regra, parametros("500000.00", "12000000.0", "2025-09", "2025-10")))
			.isNotEqualTo(HashDaRegra.calcular(regra, parametros("600000", "12000000", "2025-09", "2025-10")))
			.isNotEqualTo(HashDaRegra.calcular(regra, parametros("500000", "26000000", "2025-09", "2025-10")))
			.isNotEqualTo(HashDaRegra.calcular(regra, parametros("500000", "12000000", "2025-09")))
			.isNotEqualTo(HashDaRegra.calcular(regra,
					new ParametrosDaSimulacao(new BigDecimal("500000"), null, List.of("2025-09", "2025-10"))));
	}

	private static ParametrosDaSimulacao parametros(String orcamento, String metaVenda, String... competencias) {
		return new ParametrosDaSimulacao(new BigDecimal(orcamento), new BigDecimal(metaVenda), List.of(competencias));
	}

	/**
	 * O período entra no hash pela forma canônica, como o orçamento e a meta: ordem e
	 * repetição não mudam o hash, e um mês a mais ou a menos muda.
	 */
	@Test
	void periodoEntraNoHashPelaFormaCanonica() {
		RepresentacaoRegraDto regra = CriarJobRequisicao.deJson(CriarJobControllerTests.FORMULARIO).representacao();
		var ordemCrescente = parametros("500000", "12000000", "2025-09", "2025-10");

		assertThat(HashDaRegra.calcular(regra, ordemCrescente))
			.isEqualTo(HashDaRegra.calcular(regra, parametros("500000", "12000000", "2025-10", "2025-09")))
			.isEqualTo(HashDaRegra.calcular(regra, parametros("500000", "12000000", "2025-09", "2025-10", "2025-09")))
			.isNotEqualTo(
					HashDaRegra.calcular(regra, parametros("500000", "12000000", "2025-09", "2025-10", "2025-11")));
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
