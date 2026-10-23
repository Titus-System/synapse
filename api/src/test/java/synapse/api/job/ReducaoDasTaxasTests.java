package synapse.api.job;

import java.util.stream.Stream;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;

class ReducaoDasTaxasTests {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	static final String ORIGEM = """
			{"nucleo":{"vigencia":{"inicio":"2025-08","fim":"2025-11"},"loja":["13","58"],"marca":["10"],
			"cargo":["100","150","300"],"percentual":0.02,"taxas_por_cargo":[{"cargo":"100","percentual":0.03},
			{"cargo":"150","percentual":0.05},{"cargo":"300","percentual":0}]},
			"especificacoes":[
			{"ref":"elem.1","construto":"janela_datas","data_inicial":"2025-11-20","data_final":"2025-11-30",
			"efeito":{"tipo":"substituicao_pct","valor":0.04}},
			{"ref":"elem.2","construto":"faixa_valor","limite_inferior":50000,"limite_superior":100000,
			"efeito":{"tipo":"acrescimo_pct","valor":-0.01}},
			{"ref":"elem.3","construto":"bonus_fixo","alvo":{"tipo":"filtro","valor":{"cargo":"100"}},"valor":350},
			{"ref":"elem.4","construto":"condicao_limiar","metrica":"vendas","escopo_agregacao":"individual",
			"operador":">=","limiar":40000},
			{"ref":"elem.5","construto":"generico","descricao":"Bônus de R$ 350 acima de R$ 40.000 em vendas."}]}
			""";

	static final String PROPOSTA = """
			{"nucleo":{"vigencia":{"inicio":"2025-08","fim":"2025-11"},"loja":["13","58"],"marca":["10"],
			"cargo":["100","150","300"],"percentual":0.0162,"taxas_por_cargo":[{"cargo":"100","percentual":0.0243},
			{"cargo":"150","percentual":0.0405},{"cargo":"300","percentual":0}]},
			"especificacoes":[
			{"ref":"elem.1","construto":"janela_datas","data_inicial":"2025-11-20","data_final":"2025-11-30",
			"efeito":{"tipo":"substituicao_pct","valor":0.0324}},
			{"ref":"elem.2","construto":"faixa_valor","limite_inferior":50000,"limite_superior":100000,
			"efeito":{"tipo":"acrescimo_pct","valor":-0.0081}},
			{"ref":"elem.3","construto":"bonus_fixo","alvo":{"tipo":"filtro","valor":{"cargo":"100"}},"valor":350.00},
			{"ref":"elem.4","construto":"condicao_limiar","metrica":"vendas","escopo_agregacao":"individual",
			"operador":">=","limiar":40000},
			{"ref":"elem.5","construto":"generico","descricao":"Bônus de R$ 350 acima de R$ 40.000 em vendas."}]}
			""";

	@Test
	void aceitaTodasAsTaxasReduzidasComORestoDaRegraIntacto() {
		assertThat(reduz(ORIGEM, PROPOSTA)).isTrue();
	}

	@Test
	void aceitaUmaRegraSoDePercentualUniforme() {
		String origem = """
				{"nucleo":{"loja":["13"],"cargo":["100"],"percentual":0.025},"especificacoes":[]}
				""";
		assertThat(reduz(origem, origem.replace("0.025", "0.0099"))).isTrue();
	}

	@Test
	void recusaAPropostaQueNaoMudaNenhumaTaxa() {
		assertThat(reduz(ORIGEM, ORIGEM)).isFalse();
	}

	@ParameterizedTest(name = "{0}")
	@MethodSource("alteracoesAlemDaReducao")
	void recusaQualquerAlteracaoAlemDeReduzirAsTaxas(String caso, String de, String para) {
		assertThat(PROPOSTA).contains(de);
		assertThat(reduz(ORIGEM, PROPOSTA.replace(de, para))).isFalse();
	}

	static Stream<Arguments> alteracoesAlemDaReducao() {
		return Stream.of(Arguments.of("taxa por cargo maior", "\"percentual\":0.0243", "\"percentual\":0.031"),
				Arguments.of("taxa zerada", "\"percentual\":0.0405", "\"percentual\":0"),
				Arguments.of("taxa zero que deixa de ser zero", "\"300\",\"percentual\":0}",
						"\"300\",\"percentual\":0.001}"),
				Arguments.of("acréscimo negativo que troca de sinal", "-0.0081", "0.0081"),
				Arguments.of("percentual uniforme igual ao de origem", "\"percentual\":0.0162", "\"percentual\":0.02"),
				Arguments.of("percentual uniforme removido", "\"percentual\":0.0162,", ""),
				Arguments.of("cargo da taxa trocado", "{\"cargo\":\"150\",\"percentual\"",
						"{\"cargo\":\"200\",\"percentual\""),
				Arguments.of("bônus em reais alterado", "\"valor\":350.00", "\"valor\":300"),
				Arguments.of("limiar alterado", "\"limiar\":40000", "\"limiar\":30000"),
				Arguments.of("texto genérico alterado", "acima de R$ 40.000", "acima de R$ 30.000"),
				Arguments.of("loja alterada", "\"loja\":[\"13\",\"58\"]", "\"loja\":[\"13\"]"),
				Arguments.of("vigência alterada", "\"inicio\":\"2025-08\"", "\"inicio\":\"2025-09\""),
				Arguments.of("tipo do efeito trocado", "\"tipo\":\"substituicao_pct\"", "\"tipo\":\"acrescimo_pct\""),
				Arguments.of("limite da faixa alterado", "\"limite_inferior\":50000", "\"limite_inferior\":40000"),
				Arguments.of("referência do elemento trocada", "\"ref\":\"elem.4\"", "\"ref\":\"elem.9\""),
				Arguments.of("especificação removida",
						"{\"ref\":\"elem.4\",\"construto\":\"condicao_limiar\",\"metrica\":\"vendas\","
								+ "\"escopo_agregacao\":\"individual\",\n\"operador\":\">=\",\"limiar\":40000},\n",
						""));
	}

	private static boolean reduz(String origem, String proposta) {
		return ReducaoDasTaxas.reduzSoAsTaxas(JSON.readValue(origem, RepresentacaoRegraDto.class),
				JSON.readValue(proposta, RepresentacaoRegraDto.class));
	}

}
